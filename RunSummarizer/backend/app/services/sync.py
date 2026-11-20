"""Syncs, which queue a user's activities from a provider for the import worker, and
their status.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.config.loader import CONFIG
from app.core.clock import utc_now
from app.db.factory import RepositoriesFactory, transaction
from app.domain.enums import ImportStatus, Provider, SyncState
from app.domain.errors import (
    InvalidSyncLimitError,
    InvalidSyncWindowError,
    ProviderPausedError,
    RateLimitedError,
    SyncNotSupportedError,
)
from app.providers.base import (
    Listed,
    ListedActivity,
    ProviderDefinition,
    Requested,
    SyncWindow,
)
from app.providers.registry import PROVIDERS
from app.services import budget
from app.services.credentials import fresh_credentials, not_connected
from app.services.sync_state import sync_state

logger = logging.getLogger(__name__)

SYNC_WINDOW = timedelta(days=CONFIG.get("IMPORT_SYNC_WINDOW_DAYS", 30))
SYNC_SPACING = timedelta(seconds=CONFIG.get("IMPORT_SYNC_SPACING_SECONDS", 10))
SYNC_REQUEST_TIMEOUT = timedelta(seconds=CONFIG.get("IMPORT_SYNC_REQUEST_TIMEOUT_SECONDS", 900))


@dataclass(frozen=True)
class SyncStarted:
    queued: int  # items queued: new ones, and dead ones queued again
    requested: bool  # the provider was asked to send the activities later, by webhook


def sync_window(after: date | None, before: date | None, *, now: datetime) -> SyncWindow:
    """The window from the start of ``after`` to the start of ``before``, both in UTC.

    Without ``before`` the window ends at ``now``; without ``after`` it starts
    ``SYNC_WINDOW`` before its end. Raises ``InvalidSyncWindowError`` when it doesn't
    start before it ends.
    """
    end = _start_of_utc_day(before) if before is not None else now
    start = _start_of_utc_day(after) if after is not None else end - SYNC_WINDOW
    if start >= end:
        raise InvalidSyncWindowError(
            "'after' must be earlier than 'before'"
            if before is not None
            else "'after' must be in the past"
        )
    return SyncWindow(start, end)


def _start_of_utc_day(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


async def start_sync(
    provider: Provider,
    user_id: str,
    after: date | None = None,
    before: date | None = None,
    limit: int | None = None,
    *,
    definition: ProviderDefinition | None = None,
    transaction: RepositoriesFactory = transaction,
    clock: Callable[[], datetime] = utc_now,
) -> SyncStarted:
    """Start a sync of the user's ``provider`` activities in ``sync_window(after,
    before)``, or with ``limit`` and no window of the newest ``limit`` activities.

    ``definition`` defaults to the registered provider's; its syncer is given the user's
    ``fresh_credentials``, and the usage the provider's responses report is recorded in
    its budget. When it lists the activities,
    they are queued newest first, ``SYNC_SPACING`` apart: an activity that is stored,
    or already has an item, gets no new item, and a dead item of a listed activity is
    queued again. When it requests them instead, nothing is queued, and the status
    reports ``syncing`` until some arrive or ``SYNC_REQUEST_TIMEOUT`` passes.

    Nothing is queued when it raises:

    - ``SyncNotSupportedError`` when the provider has no syncer, before anything else;
    - ``InvalidSyncWindowError``, or ``InvalidSyncLimitError`` when ``limit`` comes
      with ``after`` or ``before``, before the syncer is called;
    - ``ProviderNotConnectedError`` when the user holds no ``provider`` credentials,
      before any provider call;
    - ``ProviderPausedError`` while the provider's calls are paused, before any
      provider call;
    - ``ProviderPausedError`` when the token refresh or the syncer raises
      ``RateLimitedError``, which pauses the provider's calls until it ends;
    - any other error the token refresh or the syncer raises
      (``ProviderAuthorizationError``, ``ProviderUnavailableError``).
    """
    if definition is None:
        definition = PROVIDERS[provider]
    if definition.syncer is None:
        raise SyncNotSupportedError(f"{provider} has no syncer")
    if limit is not None and (after is not None or before is not None):
        raise InvalidSyncLimitError("'limit' can't be combined with 'after' or 'before'")
    window = None if limit is not None else sync_window(after, before, now=clock())

    async with transaction() as repos:
        stored = await repos.providers.get_provider_credentials(provider=provider, user_id=user_id)
        paused_until = await repos.budgets.paused_until(provider, now=clock())
    if stored is None:
        raise not_connected(provider, user_id)
    if paused_until is not None:
        raise ProviderPausedError(provider, paused_until)
    try:
        credentials = await fresh_credentials(
            provider, user_id, definition.token_refresher, transaction=transaction, clock=clock
        )
        on_response = budget.usage_recorder(
            provider, definition.budget_policy, transaction=transaction, clock=clock
        )
        started = await definition.syncer().start(credentials, window, limit, on_response)
    except RateLimitedError as exc:
        await budget.pause_provider_calls(provider, exc.until, transaction=transaction)
        raise ProviderPausedError(provider, exc.until) from exc

    match started:
        case Listed(activities=activities):
            queued = await _queue(
                provider, user_id, activities, transaction=transaction, now=clock()
            )
            logger.info(
                "%s sync for user %s: %d activities listed, %d queued",
                provider,
                user_id,
                len(activities),
                queued,
            )
            return SyncStarted(queued=queued, requested=False)
        case Requested():
            async with transaction() as repos:
                await repos.providers.request_sync(provider=provider, user_id=user_id, now=clock())
            logger.info("%s sync for user %s: activities requested", provider, user_id)
            return SyncStarted(queued=0, requested=True)
        case _:
            raise TypeError(f"{provider} syncer returned {started!r}, not Listed or Requested")


async def _queue(
    provider: Provider,
    user_id: str,
    activities: Sequence[ListedActivity],
    *,
    transaction: RepositoriesFactory,
    now: datetime,
) -> int:
    """Queue ``activities``, newest first, in one transaction. Returns the number of
    items queued: dead items queued again, and new items.
    """
    newest_first = sorted(activities, key=lambda activity: activity.start_time, reverse=True)
    keys = [activity.activity_key for activity in newest_first]
    async with transaction() as repos:
        retried = await repos.import_queue.retry_failures(
            user_id, provider, activity_keys=keys, now=now
        )
        added = await repos.import_queue.enqueue_sync(
            user_id, provider, keys, spacing=SYNC_SPACING, now=now
        )
    return retried + added


async def sync_status(
    provider: Provider,
    user_id: str,
    *,
    transaction: RepositoriesFactory = transaction,
    clock: Callable[[], datetime] = utc_now,
) -> SyncState:
    """The ``SyncState`` of the user's ``provider`` items. With no items waiting, a
    sync request made less than ``SYNC_REQUEST_TIMEOUT`` ago is ``syncing``.
    """
    async with transaction() as repos:
        counts = await repos.import_queue.count_by_status(user_id, provider)
        requested_at = await repos.providers.get_sync_requested_at(
            provider=provider, user_id=user_id
        )
    return _sync_state(counts, requested_at, now=clock())


@dataclass(frozen=True)
class ProviderStatus:
    """Where a user stands with one registered provider."""

    provider: Provider
    configured: bool  # whether the app has the provider's settings
    can_sync: bool  # whether the provider has a syncer; without one it only sends activities
    connected: bool
    sync_state: SyncState


async def provider_statuses(
    user_id: str,
    *,
    transaction: RepositoriesFactory = transaction,
    clock: Callable[[], datetime] = utc_now,
) -> list[ProviderStatus]:
    """The user's ``ProviderStatus`` with every registered provider, in registry order,
    read in one transaction with a fixed number of queries.

    Each ``sync_state`` is the one ``sync_status`` reports.
    """
    async with transaction() as repos:
        counts = await repos.import_queue.count_by_status_per_provider(user_id)
        accounts = {
            account.provider: account for account in await repos.providers.list_accounts(user_id)
        }
    now = clock()
    statuses = []
    for provider, definition in PROVIDERS.items():
        account = accounts.get(provider)
        statuses.append(
            ProviderStatus(
                provider=provider,
                configured=definition.is_configured(),
                can_sync=definition.syncer is not None,
                connected=account is not None and account.connected,
                sync_state=_sync_state(
                    counts.get(provider, {}),
                    account.sync_requested_at if account is not None else None,
                    now=now,
                ),
            )
        )
    return statuses


def _sync_state(
    counts: Mapping[ImportStatus, int], requested_at: datetime | None, *, now: datetime
) -> SyncState:
    """``sync_state(counts)``, except that with no items waiting a sync request made less
    than ``SYNC_REQUEST_TIMEOUT`` before ``now`` is ``syncing``.
    """
    state = sync_state(counts)
    if (
        state is SyncState.IDLE
        and requested_at is not None
        and now < requested_at + SYNC_REQUEST_TIMEOUT
    ):
        return SyncState.SYNCING
    return state
