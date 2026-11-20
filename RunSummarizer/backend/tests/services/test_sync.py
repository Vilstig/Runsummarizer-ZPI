"""start_sync and sync_status for any provider, through a fake syncer: the window, the
connection check, queueing listed activities, requested ones, and the status.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.domain.enums import ImportPriority, ImportStatus, Provider, SyncState
from app.domain.errors import (
    InvalidSyncLimitError,
    InvalidSyncWindowError,
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    ProviderPausedError,
    ProviderUnavailableError,
    RateLimitedError,
    SyncNotSupportedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import (
    Listed,
    ListedActivity,
    ProviderDefinition,
    Requested,
    ResponseObserver,
    SyncStart,
    SyncWindow,
)
from app.providers.registry import PROVIDERS
from app.services import sync
from app.services.sync import (
    SYNC_REQUEST_TIMEOUT,
    SYNC_SPACING,
    SYNC_WINDOW,
    ProviderStatus,
    SyncStarted,
    sync_window,
)
from tests.helpers import configure_strava, unconfigure_garmin
from tests.services.fakes import stored_run, strava_usage

pytestmark = pytest.mark.anyio

USER_ID = "user-1"
OTHER_USER_ID = "user-2"

NOW = datetime(2026, 10, 11, 12, 7, tzinfo=UTC)
PAUSED_UNTIL = datetime(2026, 10, 11, 12, 15, tzinfo=UTC)

# A provider other than Strava, for which the fake database holds credentials.
OTHER = Provider.GARMIN
OTHER_CREDENTIALS = ProviderCredentials("garmin-token", None, None)
STORED = ProviderCredentials("access-1", "refresh-1", 0)  # the user's Strava credentials
REFRESHED = ProviderCredentials("access-2", "refresh-2", 4_102_444_800)


class FakeSyncer:
    """A ``ProviderSyncer`` that records each call, and returns or raises ``outcome``."""

    def __init__(self, outcome: SyncStart | Exception | None = None):
        self.outcome = outcome if outcome is not None else Listed([])
        self.calls: list[tuple[ProviderCredentials, SyncWindow | None, int | None]] = []
        self.observers: list[ResponseObserver] = []  # the on_response of each call

    async def start(
        self,
        credentials: ProviderCredentials,
        window: SyncWindow | None,
        limit: int | None,
        on_response: ResponseObserver,
    ) -> SyncStart:
        self.calls.append((credentials, window, limit))
        self.observers.append(on_response)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeRefresher:
    """A ``TokenRefresher`` that returns ``REFRESHED``, or raises ``error``."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.refreshed: list[ProviderCredentials] = []

    async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
        self.refreshed.append(credentials)
        if self.error is not None:
            raise self.error
        return REFRESHED


def listed(*activities: tuple[str, str]) -> Listed:
    """``Listed`` with each (activity key, ISO start time)."""
    return Listed([ListedActivity(key, datetime.fromisoformat(start)) for key, start in activities])


@pytest.fixture(autouse=True)
def connected(db):
    """The user, connected to Strava."""
    db.add_strava_user(USER_ID, 101, "refresh-1")


@pytest.fixture
def syncer() -> FakeSyncer:
    return FakeSyncer()


async def start_sync(
    db,
    syncer: FakeSyncer,
    *,
    provider: Provider = Provider.STRAVA,
    after: date | None = None,
    before: date | None = None,
    limit: int | None = None,
    refresher: FakeRefresher | None = None,
) -> SyncStarted:
    definition = replace(
        PROVIDERS[Provider.STRAVA],
        provider=provider,
        syncer=lambda: syncer,
        token_refresher=refresher,
    )
    return await sync.start_sync(
        provider,
        USER_ID,
        after,
        before,
        limit,
        definition=definition,
        transaction=db.transaction,
        clock=lambda: NOW,
    )


async def sync_status(db, *, provider: Provider = Provider.STRAVA, now: datetime = NOW):
    return await sync.sync_status(provider, USER_ID, transaction=db.transaction, clock=lambda: now)


def queue_order(db) -> list[tuple[str, datetime]]:
    """The items' keys and sort keys, in the order the worker claims them."""
    items = sorted(db.import_items.values(), key=lambda item: (item.priority, item.sort_key))
    return [(item.activity_key, item.sort_key) for item in items]


# ---------- sync_window ----------


def test_the_default_window_ends_now():
    assert sync_window(None, None, now=NOW) == SyncWindow(NOW - SYNC_WINDOW, NOW)


def test_after_and_before_are_the_starts_of_their_days_in_utc():
    window = sync_window(date(2026, 9, 1), date(2026, 10, 1), now=NOW)

    assert window == SyncWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))


def test_a_window_with_only_after_ends_now():
    window = sync_window(date(2026, 9, 1), None, now=NOW)

    assert window == SyncWindow(datetime(2026, 9, 1, tzinfo=UTC), NOW)


def test_a_window_with_only_before_ends_there():
    end = datetime(2026, 1, 1, tzinfo=UTC)

    assert sync_window(None, date(2026, 1, 1), now=NOW) == SyncWindow(end - SYNC_WINDOW, end)


@pytest.mark.parametrize(
    ("after", "before", "message"),
    [
        (date(2026, 10, 1), date(2026, 10, 1), "'after' must be earlier than 'before'"),
        (date(2026, 10, 2), date(2026, 10, 1), "'after' must be earlier than 'before'"),
        (date(2026, 10, 12), None, "'after' must be in the past"),
    ],
    ids=["same-day", "after-past-before", "after-in-the-future"],
)
def test_a_window_that_does_not_start_before_it_ends_is_invalid(after, before, message):
    with pytest.raises(InvalidSyncWindowError, match=message):
        sync_window(after, before, now=NOW)


# ---------- start_sync: what the syncer is asked ----------


async def test_the_syncer_lists_the_requested_days_for_the_user(db, syncer):
    await start_sync(db, syncer, after=date(2026, 9, 1), before=date(2026, 10, 1))

    window = SyncWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    assert syncer.calls == [(STORED, window, None)]


async def test_without_days_the_syncer_lists_the_default_window(db, syncer):
    await start_sync(db, syncer)

    assert syncer.calls == [(STORED, SyncWindow(NOW - SYNC_WINDOW, NOW), None)]


async def test_a_limit_is_passed_to_the_syncer_without_a_window(db, syncer):
    await start_sync(db, syncer, limit=25)

    assert syncer.calls == [(STORED, None, 25)]


async def test_an_invalid_window_raises_without_calling_the_syncer(db, syncer):
    with pytest.raises(InvalidSyncWindowError):
        await start_sync(db, syncer, after=date(2026, 10, 2), before=date(2026, 10, 1))

    assert syncer.calls == []


@pytest.mark.parametrize(
    ("after", "before"),
    [(date(2026, 9, 1), None), (None, date(2026, 10, 1))],
    ids=["after", "before"],
)
async def test_a_limit_with_a_window_raises_without_calling_the_syncer(db, syncer, after, before):
    with pytest.raises(InvalidSyncLimitError):
        await start_sync(db, syncer, after=after, before=before, limit=25)

    assert syncer.calls == []


async def test_a_user_without_credentials_is_not_connected(db, syncer):
    del db.credentials[USER_ID]

    with pytest.raises(ProviderNotConnectedError):
        await start_sync(db, syncer)

    assert syncer.calls == []


async def test_a_provider_that_is_not_the_users_connected_one_is_not_connected(db, syncer):
    with pytest.raises(ProviderNotConnectedError):
        await start_sync(db, syncer, provider=OTHER)

    assert syncer.calls == []


async def test_the_syncer_gets_credentials_refreshed_through_the_refresher(db, syncer):
    refresher = FakeRefresher()

    await start_sync(db, syncer, refresher=refresher)

    assert refresher.refreshed == [STORED]
    assert syncer.calls[0][0] == REFRESHED
    assert db.credentials[USER_ID] == REFRESHED


async def test_a_rate_limited_refresh_pauses_the_sync_without_calling_the_syncer(db, syncer):
    refresher = FakeRefresher(RateLimitedError("429", until=PAUSED_UNTIL))

    with pytest.raises(ProviderPausedError) as raised:
        await start_sync(db, syncer, refresher=refresher)

    assert raised.value.until == PAUSED_UNTIL
    assert syncer.calls == []
    assert db.budget("strava").paused_until == PAUSED_UNTIL


async def test_a_rejected_refresh_propagates_without_calling_the_syncer(db, syncer):
    refresher = FakeRefresher(ProviderAuthorizationError("rejected"))

    with pytest.raises(ProviderAuthorizationError):
        await start_sync(db, syncer, refresher=refresher)

    assert syncer.calls == []


async def test_the_registered_syncer_is_used_by_default(db, monkeypatch):
    registered = FakeSyncer(listed(("strava_1", "2026-10-01T06:00:00Z")))
    definition = sync.PROVIDERS[Provider.STRAVA]
    monkeypatch.setitem(sync.PROVIDERS, Provider.STRAVA, _with_syncer(definition, registered))

    started = await sync.start_sync(
        Provider.STRAVA, USER_ID, transaction=db.transaction, clock=lambda: NOW
    )

    assert started.queued == 1
    assert registered.calls == [(STORED, SyncWindow(NOW - SYNC_WINDOW, NOW), None)]


def _with_syncer(definition: ProviderDefinition, syncer: FakeSyncer) -> ProviderDefinition:
    return replace(definition, syncer=lambda: syncer, token_refresher=None)


async def start_sync_without_syncer(db, **params) -> SyncStarted:
    """``start_sync`` of ``OTHER``, registered without a syncer."""
    definition = replace(PROVIDERS[Provider.STRAVA], provider=OTHER, syncer=None)
    return await sync.start_sync(
        OTHER,
        USER_ID,
        definition=definition,
        transaction=db.transaction,
        clock=lambda: NOW,
        **params,
    )


async def test_a_provider_without_a_syncer_is_not_synced(db):
    db.provider_credentials[OTHER, USER_ID] = OTHER_CREDENTIALS
    db.budget(OTHER).paused_until = PAUSED_UNTIL

    with pytest.raises(SyncNotSupportedError):
        await start_sync_without_syncer(db)

    assert db.blocks_opened == 0
    assert db.import_items == {}
    assert db.sync_requests == {}


async def test_a_provider_without_a_syncer_is_reported_before_the_window_or_connection(db):
    with pytest.raises(SyncNotSupportedError):
        await start_sync_without_syncer(db, after=date(2026, 10, 12), limit=5)

    assert db.blocks_opened == 0


# ---------- start_sync: Listed ----------


async def test_an_item_is_queued_for_each_listed_activity(db, syncer):
    syncer.outcome = listed(
        ("strava_1", "2026-10-01T06:00:00Z"), ("strava_2", "2026-10-02T06:00:00Z")
    )

    started = await start_sync(db, syncer)

    assert started == SyncStarted(queued=2, requested=False)
    assert {key for _, _, key in db.import_items} == {"strava_1", "strava_2"}
    assert all(item.run_after == NOW for item in db.import_items.values())


async def test_the_newest_activity_is_queued_first_spaced_apart(db, syncer):
    syncer.outcome = listed(
        ("strava_1", "2026-10-01T06:00:00Z"),
        ("strava_2", "2026-10-09T06:00:00Z"),
        ("strava_3", "2026-10-05T06:00:00+02:00"),
    )

    await start_sync(db, syncer)

    assert queue_order(db) == [
        ("strava_2", NOW + SYNC_SPACING),
        ("strava_3", NOW + 2 * SYNC_SPACING),
        ("strava_1", NOW + 3 * SYNC_SPACING),
    ]


async def test_listed_activities_are_queued_under_the_syncs_provider(db, syncer):
    db.provider_credentials[OTHER, USER_ID] = OTHER_CREDENTIALS
    syncer.outcome = listed(("garmin_1", "2026-10-01T06:00:00Z"))

    await start_sync(db, syncer, provider=OTHER)

    assert list(db.import_items) == [(USER_ID, "garmin", "garmin_1")]


async def test_activities_already_stored_or_queued_get_no_new_item(db, syncer):
    syncer.outcome = listed(
        ("strava_1", "2026-10-01T06:00:00Z"),
        ("strava_2", "2026-10-02T06:00:00Z"),
        ("strava_3", "2026-10-03T06:00:00Z"),
    )
    db.activities["strava_1"] = stored_run(1, user_id=USER_ID)
    db.queue_item(USER_ID, "strava_2", priority=ImportPriority.WEBHOOK)

    assert (await start_sync(db, syncer)).queued == 1

    assert {key for _, _, key in db.import_items} == {"strava_2", "strava_3"}
    assert db.import_item(USER_ID, "strava_2").priority == ImportPriority.WEBHOOK


async def test_a_dead_item_of_a_listed_activity_is_queued_again_with_its_payload(db, syncer):
    syncer.outcome = listed(("strava_1", "2026-10-01T06:00:00Z"))
    db.queue_item(USER_ID, "strava_1", status=ImportStatus.DEAD, attempts=5, raw_payload={"a": 1})

    assert (await start_sync(db, syncer)).queued == 1

    retried = db.import_item(USER_ID, "strava_1")
    assert (retried.status, retried.attempts, retried.run_after) == (ImportStatus.QUEUED, 0, NOW)
    assert retried.raw_payload == {"a": 1}


async def test_a_dead_item_of_an_activity_that_is_not_listed_stays_dead(db, syncer):
    db.queue_item(USER_ID, "strava_9", status=ImportStatus.DEAD)

    assert (await start_sync(db, syncer)).queued == 0

    assert db.import_item(USER_ID, "strava_9").status == ImportStatus.DEAD


async def test_a_listed_sync_requests_nothing(db, syncer):
    await start_sync(db, syncer)

    assert db.sync_requests == {}


# ---------- start_sync: Requested ----------


async def test_a_requested_sync_queues_nothing_and_records_the_request(db, syncer):
    syncer.outcome = Requested()

    started = await start_sync(db, syncer)

    assert started == SyncStarted(queued=0, requested=True)
    assert db.import_items == {}
    assert db.sync_requests == {(Provider.STRAVA, USER_ID): NOW}


async def test_a_requested_sync_is_recorded_under_the_syncs_provider(db, syncer):
    db.provider_credentials[OTHER, USER_ID] = OTHER_CREDENTIALS
    syncer.outcome = Requested()

    await start_sync(db, syncer, provider=OTHER)

    assert db.sync_requests == {(OTHER, USER_ID): NOW}


# ---------- start_sync: errors ----------


async def test_a_rate_limited_syncer_pauses_the_sync_and_queues_nothing(db, syncer):
    syncer.outcome = RateLimitedError("429", until=PAUSED_UNTIL)

    with pytest.raises(ProviderPausedError) as raised:
        await start_sync(db, syncer)

    assert (raised.value.provider, raised.value.until) == (Provider.STRAVA, PAUSED_UNTIL)
    assert db.import_items == {}
    assert db.budget("strava").paused_until == PAUSED_UNTIL


async def test_a_rate_limited_syncer_pauses_only_the_syncs_provider(db, syncer):
    db.provider_credentials[OTHER, USER_ID] = OTHER_CREDENTIALS
    syncer.outcome = RateLimitedError("429", until=PAUSED_UNTIL)

    with pytest.raises(ProviderPausedError):
        await start_sync(db, syncer, provider=OTHER)

    assert db.budget(OTHER).paused_until == PAUSED_UNTIL
    assert db.budget("strava").paused_until is None


async def test_paused_provider_calls_hold_the_sync_back_before_the_token_refresh(db, syncer):
    db.budget("strava").paused_until = PAUSED_UNTIL
    refresher = FakeRefresher()

    with pytest.raises(ProviderPausedError) as raised:
        await start_sync(db, syncer, refresher=refresher)

    assert (raised.value.provider, raised.value.until) == (Provider.STRAVA, PAUSED_UNTIL)
    assert refresher.refreshed == []
    assert syncer.calls == []


async def test_a_user_without_credentials_is_not_connected_even_while_paused(db, syncer):
    db.budget("strava").paused_until = PAUSED_UNTIL
    del db.credentials[USER_ID]

    with pytest.raises(ProviderNotConnectedError):
        await start_sync(db, syncer)

    assert syncer.calls == []


async def test_a_pause_that_has_ended_does_not_hold_the_sync_back(db, syncer):
    db.budget("strava").paused_until = NOW

    await start_sync(db, syncer)

    assert len(syncer.calls) == 1


async def test_the_syncer_records_the_usage_of_its_responses_in_the_providers_budget(db, syncer):
    db.provider_credentials[OTHER, USER_ID] = OTHER_CREDENTIALS
    await start_sync(db, syncer, provider=OTHER)
    headers = {"X-ReadRateLimit-Limit": "100,1000", "X-ReadRateLimit-Usage": "37,512"}

    [on_response] = syncer.observers
    await on_response(httpx.Response(200, headers=headers), NOW)

    assert db.budget(OTHER).usage_reports == [strava_usage(37, 512, 100, 1000)]


@pytest.mark.parametrize(
    "error",
    [
        ProviderAuthorizationError("401"),
        ProviderUnavailableError("500"),
        ProviderNotConnectedError("no tokens"),
    ],
    ids=["authorization", "unavailable", "not-connected"],
)
async def test_other_syncer_errors_propagate_and_queue_nothing(db, syncer, error):
    syncer.outcome = error

    with pytest.raises(type(error)):
        await start_sync(db, syncer)

    assert db.import_items == {}
    assert db.sync_requests == {}


async def test_a_syncer_result_that_is_neither_listed_nor_requested_is_an_error(db, syncer):
    syncer.outcome = ["strava_1"]

    with pytest.raises(TypeError):
        await start_sync(db, syncer)

    assert db.import_items == {}


# ---------- sync_status ----------


async def test_the_status_reads_the_users_items_in_one_transaction(db):
    db.queue_item(USER_ID, "strava_1", status=ImportStatus.RUNNING)

    assert await sync_status(db) == SyncState.SYNCING
    assert db.blocks_opened == 1


async def test_the_status_leaves_out_other_users_and_other_providers(db):
    db.queue_item(USER_ID, "strava_1")
    db.queue_item(OTHER_USER_ID, "strava_2", status=ImportStatus.BLOCKED)
    db.queue_item(USER_ID, "garmin_3", provider="garmin", status=ImportStatus.BLOCKED)

    assert await sync_status(db) == SyncState.SYNCING


async def test_a_user_without_items_is_idle_while_others_sync(db):
    db.queue_item(OTHER_USER_ID, "strava_2")
    db.queue_item(USER_ID, "garmin_3", provider="garmin", status=ImportStatus.RUNNING)

    assert await sync_status(db) == SyncState.IDLE


async def test_a_pending_request_is_syncing_until_the_timeout(db):
    db.sync_requests[Provider.STRAVA, USER_ID] = NOW

    assert await sync_status(db, now=NOW + SYNC_REQUEST_TIMEOUT - timedelta(seconds=1)) == (
        SyncState.SYNCING
    )
    assert await sync_status(db, now=NOW + SYNC_REQUEST_TIMEOUT) == SyncState.IDLE


async def test_a_pending_request_does_not_hide_a_needed_reconnect(db):
    db.sync_requests[Provider.STRAVA, USER_ID] = NOW
    db.queue_item(USER_ID, "strava_1", status=ImportStatus.BLOCKED)

    assert await sync_status(db) == SyncState.NEEDS_RECONNECT


async def test_a_pending_request_is_read_for_the_statuss_provider_only(db):
    db.sync_requests[OTHER, USER_ID] = NOW

    assert await sync_status(db) == SyncState.IDLE
    assert await sync_status(db, provider=OTHER) == SyncState.SYNCING


# ---------- provider_statuses ----------


@pytest.fixture
def registry(monkeypatch):
    """Exactly Strava, configured, and OTHER registered after it without its settings or a
    syncer: the whole registry replaced, so the test doesn't depend on how many providers
    are really registered.
    """
    configure_strava(monkeypatch, client_id="client-id", client_secret="client-secret")
    other = replace(
        PROVIDERS[Provider.STRAVA], provider=OTHER, is_configured=lambda: False, syncer=None
    )
    monkeypatch.setattr(
        sync, "PROVIDERS", {Provider.STRAVA: PROVIDERS[Provider.STRAVA], OTHER: other}
    )


async def provider_statuses(db, *, user_id: str = USER_ID, now: datetime = NOW):
    return await sync.provider_statuses(user_id, transaction=db.transaction, clock=lambda: now)


@pytest.mark.usefixtures("registry")
async def test_every_registered_provider_gets_a_status_in_registry_order(db):
    assert await provider_statuses(db) == [
        ProviderStatus(
            Provider.STRAVA,
            configured=True,
            can_sync=True,
            connected=True,
            sync_state=SyncState.IDLE,
        ),
        ProviderStatus(
            OTHER, configured=False, can_sync=False, connected=False, sync_state=SyncState.IDLE
        ),
    ]


@pytest.mark.usefixtures("registry")
async def test_the_statuses_are_read_in_one_transaction(db):
    db.queue_item(USER_ID, "strava_1")
    db.queue_item(USER_ID, "garmin_1", provider="garmin")

    await provider_statuses(db)

    assert db.blocks_opened == 1


async def test_garmin_is_listed_unconfigured_without_its_settings(db, monkeypatch):
    unconfigure_garmin(monkeypatch)

    garmin = next(s for s in await provider_statuses(db) if s.provider is Provider.GARMIN)

    assert (garmin.configured, garmin.can_sync, garmin.connected) == (False, False, False)


@pytest.mark.usefixtures("registry")
async def test_each_providers_items_give_its_own_sync_state(db):
    db.queue_item(USER_ID, "strava_1", status=ImportStatus.BLOCKED)
    db.queue_item(USER_ID, "garmin_1", provider="garmin", status=ImportStatus.RUNNING)
    db.queue_item(OTHER_USER_ID, "strava_2")

    states = [status.sync_state for status in await provider_statuses(db)]

    assert states == [SyncState.NEEDS_RECONNECT, SyncState.SYNCING]


@pytest.mark.usefixtures("registry")
async def test_a_pending_sync_request_is_syncing_until_the_timeout(db):
    db.sync_requests[Provider.STRAVA, USER_ID] = NOW

    before = await provider_statuses(db, now=NOW + SYNC_REQUEST_TIMEOUT - timedelta(seconds=1))
    after = await provider_statuses(db, now=NOW + SYNC_REQUEST_TIMEOUT)

    assert before[0].sync_state == SyncState.SYNCING
    assert after[0].sync_state == SyncState.IDLE


@pytest.mark.usefixtures("registry")
async def test_a_disconnected_account_is_listed_as_not_connected(db):
    del db.credentials[USER_ID]  # still linked to the athlete

    assert [status.connected for status in await provider_statuses(db)] == [False, False]


@pytest.mark.usefixtures("registry")
async def test_the_connected_provider_is_the_only_one_connected(db):
    del db.credentials[USER_ID]
    db.provider_credentials[OTHER, USER_ID] = OTHER_CREDENTIALS

    assert [status.connected for status in await provider_statuses(db)] == [False, True]


@pytest.mark.usefixtures("registry")
async def test_a_user_without_accounts_or_items_is_idle_everywhere(db):
    statuses = await provider_statuses(db, user_id="nobody")

    assert [(s.connected, s.sync_state) for s in statuses] == [
        (False, SyncState.IDLE),
        (False, SyncState.IDLE),
    ]


@pytest.mark.usefixtures("registry")
async def test_each_status_agrees_with_sync_status(db):
    db.queue_item(USER_ID, "strava_1", status=ImportStatus.BLOCKED)
    db.provider_credentials[OTHER, USER_ID] = OTHER_CREDENTIALS
    db.sync_requests[OTHER, USER_ID] = NOW

    statuses = await provider_statuses(db)

    for status in statuses:
        assert status.sync_state == await sync_status(db, provider=status.provider)
