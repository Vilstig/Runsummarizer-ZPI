"""Importing queued activities, one import queue item at a time, for any provider.

A provider takes part through a ``ProviderImporter``: it says what fetching an item
costs, fetches its payload and normalizes it. Claiming, reserving the provider's budget,
recording its usage, pausing it after a 429, attempts, backoff, building the activity
(``activity_pipeline``) and every write to the queue are shared.
"""

import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import anyio

from app.config.loader import CONFIG
from app.core.clock import elapsed_ms, utc_now
from app.core.request_context import log_context_var
from app.db.factory import RepositoriesFactory, transaction
from app.db.protocols.import_queue import Claim, FinishOutcome
from app.domain.enums import ImportErrorCode, Provider
from app.domain.errors import (
    FetchError,
    ProviderActivityNotFoundError,
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import BudgetPolicy, HeartRateZonesRecord
from app.providers.base import ProviderImporter, TokenRefresher, describe_error
from app.services import activity_pipeline
from app.services.activity_pipeline import ImportedActivity
from app.services.budget import pause_provider_calls, usage_recorder
from app.services.credentials import fresh_credentials

logger = logging.getLogger(__name__)

LEASE = timedelta(seconds=CONFIG.get("IMPORT_LEASE_SECONDS", 300))
PROCESSING_MAX_ATTEMPTS = CONFIG.get("IMPORT_PROCESSING_MAX_ATTEMPTS", 2)
BACKOFF_BASE = timedelta(seconds=CONFIG.get("IMPORT_BACKOFF_BASE_SECONDS", 60))
BACKOFF_MAX = timedelta(seconds=CONFIG.get("IMPORT_BACKOFF_MAX_SECONDS", 3600))
BACKOFF_JITTER = 0.2  # share of the delay it may vary by, either way


@dataclass(frozen=True)
class OverBudget:
    """No item was claimed: the next one needs provider calls the budget can't take yet."""

    resumes_at: datetime | None  # when the budget can take them; None if it already can


class ItemOutcome(StrEnum):
    """What became of a claimed item."""

    IMPORTED = "imported"  # saved; the item is deleted
    ALREADY_STORED = "already_stored"  # the stored activity is left untouched; the item is deleted
    SKIPPED = "skipped"  # not an activity to import; the item is deleted
    REQUEUED = "requeued"  # finished, but a webhook queued the item again during the run
    RATE_LIMITED = "rate_limited"  # queued until provider calls resume, the attempt given back
    RETRYING = "retrying"  # failed; queued again after a backoff
    DEAD = "dead"  # failed for good
    BLOCKED = "blocked"  # the authorization was revoked; the user's queued items are blocked
    LOST = "lost"  # the lease was lost to another claim, or the item deleted; nothing written


@dataclass(frozen=True)
class ItemResult:
    provider: str
    user_id: str
    activity_key: str
    outcome: ItemOutcome


def retry_delay(attempts: int, *, rand: Callable[[], float] = random.random) -> timedelta:
    """How long an item that failed its ``attempts``-th attempt waits before the next one.

    ``BACKOFF_BASE``, doubled for every attempt after the first, varied by up to
    ``BACKOFF_JITTER`` either way, and capped at ``BACKOFF_MAX``. ``rand`` returns a
    number in [0, 1).
    """
    seconds = BACKOFF_BASE.total_seconds() * 2 ** (attempts - 1)
    seconds *= 1 + BACKOFF_JITTER * (2 * rand() - 1)
    return timedelta(seconds=min(seconds, BACKOFF_MAX.total_seconds()))


async def import_next_item(
    importer: ProviderImporter,
    *,
    budget_policy: BudgetPolicy,
    token_refresher: TokenRefresher | None = None,
    transaction: RepositoriesFactory = transaction,
    clock: Callable[[], datetime] = utc_now,
) -> ItemResult | OverBudget | None:
    """Claim the next claimable item of ``importer``'s provider and import its activity,
    fetched with the user's ``fresh_credentials``, refreshed through ``token_refresher``.

    The claim and the reservation of the item's ``importer.cost`` in the provider's
    budget, under ``budget_policy`` and the item's priority, are one transaction,
    committed before any provider call; an item with a saved payload needs no
    reservation. When the budget can't take the next item, the next item with a saved
    payload is claimed instead. The usage the provider's responses report is recorded.
    Returns None when no item is claimable, and ``OverBudget`` when the budget can't take
    the next item and none has a saved payload; neither claims an item. Otherwise the
    activity is saved unless the user already has it stored, or the failure recorded on
    the item, as the result's ``outcome`` says:

    - ``RateLimitedError``, from the fetch or the token refresh, pauses the provider's
      calls until it ends, gives the attempt back and queues the item until then;
    - ``ProviderAuthorizationError``, or a user without credentials, blocks the user's
      items;
    - ``ProviderActivityNotFoundError`` makes the item dead;
    - ``ProviderUnavailableError`` retries the item, until ``importer.max_attempts``;
    - a failure to build or save the activity saves the payload on the item and retries
      it, until ``PROCESSING_MAX_ATTEMPTS``.

    When ``importer.single_use_fetch``, the fetched payload is saved on the item before
    the activity is built, so a later claim imports it without fetching it again.

    Any other error, a database one included, propagates, and the item stays running
    until its lease ends. ``clock`` gives the current time.
    """
    now = clock()
    async with transaction() as repos:
        item = await repos.import_queue.lock_next(importer.provider, now=now)
        if item is None:
            return None
        if item.raw_payload is None:
            cost, priority = importer.cost(item), item.priority
            reserved = await repos.budgets.reserve(
                importer.provider, cost, policy=budget_policy, priority=priority, now=now
            )
            if not reserved:
                item = await repos.import_queue.lock_next(
                    importer.provider, now=now, saved_payload_only=True
                )
                if item is None:
                    resumes_at = await repos.budgets.resumes_at(
                        importer.provider, cost, policy=budget_policy, priority=priority, now=now
                    )
                    return OverBudget(resumes_at)
        claim = await repos.import_queue.claim(item, lease=LEASE, now=now)

    context_token = log_context_var.set(f"{claim.provider}:{claim.activity_key}")
    try:
        item_import = _ItemImport(
            importer,
            claim,
            budget_policy=budget_policy,
            token_refresher=token_refresher,
            transaction=transaction,
            clock=clock,
        )
        outcome = await item_import.run(item.raw_payload)
        logger.info(
            "%s item %s for user %s: %s (attempt %d)",
            claim.provider,
            claim.activity_key,
            claim.user_id,
            outcome,
            claim.attempts,
        )
        return ItemResult(claim.provider, claim.user_id, claim.activity_key, outcome)
    finally:
        log_context_var.reset(context_token)


class _LeaseLostError(Exception):
    """Rolls back a transaction whose item turned out to belong to another claim."""


class _ItemImport:
    """The import of one claimed item."""

    def __init__(
        self,
        importer: ProviderImporter,
        claim: Claim,
        *,
        budget_policy: BudgetPolicy,
        token_refresher: TokenRefresher | None,
        transaction: RepositoriesFactory,
        clock: Callable[[], datetime],
    ):
        self._importer = importer
        self._claim = claim
        self._provider = Provider(claim.provider)
        self._budget_policy = budget_policy
        self._token_refresher = token_refresher
        self._transaction = transaction
        self._clock = clock

    async def run(self, raw_payload: dict | None) -> ItemOutcome:
        """Import the activity from ``raw_payload``, or from the provider when it is None."""
        payload = raw_payload
        if payload is None:
            try:
                credentials = await fresh_credentials(
                    self._provider,
                    self._claim.user_id,
                    self._token_refresher,
                    transaction=self._transaction,
                    clock=self._clock,
                )
                on_response = usage_recorder(
                    self._provider,
                    self._budget_policy,
                    transaction=self._transaction,
                    clock=self._clock,
                )
                payload = await self._importer.fetch(self._claim, credentials, on_response)
            except RateLimitedError as exc:
                await pause_provider_calls(self._provider, exc.until, transaction=self._transaction)
                return await self._release(exc.until)
            except ProviderAuthorizationError as exc:
                return await self._block(str(exc))
            except ProviderNotConnectedError as exc:
                return await self._block(describe_error(exc))
            except ProviderActivityNotFoundError as exc:
                return await self._fail(exc, ImportErrorCode.NOT_FOUND, dead=True)
            except ProviderUnavailableError as exc:
                dead = self._claim.attempts >= self._importer.max_attempts
                return await self._fail(exc, ImportErrorCode.UNAVAILABLE, dead=dead)
            if payload is None:
                return await self._finish(None)
            if self._importer.single_use_fetch and not await self._save_payload(payload):
                return ItemOutcome.LOST

        async with self._transaction() as repos:
            hr_zones = await repos.hr_zones.list_history(self._claim.user_id)
        try:
            t0 = time.perf_counter()
            # CPU-bound (the sklearn classifier): runs in a worker thread.
            imported = await anyio.to_thread.run_sync(self._build, payload, hr_zones)
            logger.debug(
                "%s item %s: normalize/classify/summary %.0fms",
                self._claim.provider,
                self._claim.activity_key,
                elapsed_ms(t0),
            )
            return await self._finish(imported)
        except Exception as exc:
            logger.warning(
                "%s item %s: processing failed",
                self._claim.provider,
                self._claim.activity_key,
                exc_info=True,
            )
            dead = self._claim.attempts >= PROCESSING_MAX_ATTEMPTS
            return await self._fail(
                exc, ImportErrorCode.PROCESSING_FAILED, dead=dead, raw_payload=payload
            )

    def _build(
        self, payload: dict, hr_zones: Sequence[HeartRateZonesRecord]
    ) -> ImportedActivity | None:
        """The activity built from ``payload``; None when the importer skips it."""
        normalized = self._importer.normalize(payload)
        if normalized is None:
            return None
        return activity_pipeline.build_import(normalized, self._claim.user_id, hr_zones)

    async def _finish(self, imported: ImportedActivity | None) -> ItemOutcome:
        """Save ``imported``, when there is one and its activity isn't stored, and finish
        the item, in one transaction.
        """
        try:
            async with self._transaction() as repos:
                saved = (
                    await repos.activities.save(
                        imported.record,
                        raw_payload=imported.raw_payload,
                        payload_kind=imported.payload_kind,
                        streams=imported.streams,
                    )
                    if imported is not None
                    else False
                )
                finished = await repos.import_queue.finish(self._claim, now=self._clock())
                if finished is FinishOutcome.LOST:
                    raise _LeaseLostError
        except _LeaseLostError:
            return ItemOutcome.LOST
        if finished is FinishOutcome.REQUEUED:
            return ItemOutcome.REQUEUED
        if imported is None:
            return ItemOutcome.SKIPPED
        return ItemOutcome.IMPORTED if saved else ItemOutcome.ALREADY_STORED

    async def _save_payload(self, payload: dict) -> bool:
        """Save the fetched ``payload`` on the item. Returns whether the lease was held."""
        async with self._transaction() as repos:
            return await repos.import_queue.save_payload(self._claim, payload, now=self._clock())

    async def _release(self, until: datetime) -> ItemOutcome:
        async with self._transaction() as repos:
            held = await repos.import_queue.release(self._claim, run_after=until, now=self._clock())
        return ItemOutcome.RATE_LIMITED if held else ItemOutcome.LOST

    async def _block(self, last_error: str) -> ItemOutcome:
        async with self._transaction() as repos:
            await repos.import_queue.block(self._claim, last_error=last_error, now=self._clock())
        logger.warning(
            "%s item %s: blocked: %s", self._claim.provider, self._claim.activity_key, last_error
        )
        return ItemOutcome.BLOCKED

    async def _fail(
        self,
        exc: Exception,
        error_code: ImportErrorCode,
        *,
        dead: bool,
        raw_payload: dict | None = None,
    ) -> ItemOutcome:
        """Make the item dead, or queue it again after a backoff, with ``error_code``."""
        now = self._clock()
        last_error = str(exc) if isinstance(exc, FetchError) else describe_error(exc)
        async with self._transaction() as repos:
            if dead:
                held = await repos.import_queue.mark_dead(
                    self._claim,
                    error_code=error_code,
                    last_error=last_error,
                    raw_payload=raw_payload,
                    now=now,
                )
            else:
                held = await repos.import_queue.retry_later(
                    self._claim,
                    run_after=now + retry_delay(self._claim.attempts),
                    error_code=error_code,
                    last_error=last_error,
                    raw_payload=raw_payload,
                    now=now,
                )
        if not held:
            return ItemOutcome.LOST
        logger.warning(
            "%s item %s: %s (%s): %s",
            self._claim.provider,
            self._claim.activity_key,
            error_code,
            "dead" if dead else "retrying",
            last_error,
        )
        return ItemOutcome.DEAD if dead else ItemOutcome.RETRYING
