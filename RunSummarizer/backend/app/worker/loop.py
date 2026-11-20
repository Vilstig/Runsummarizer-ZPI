"""The import worker's loop: import a provider's queued items one at a time."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import anyio

from app.config.loader import CONFIG
from app.core.clock import utc_now
from app.db.factory import RepositoriesFactory, transaction
from app.domain.models import BudgetPolicy
from app.providers.base import ProviderImporter, TokenRefresher
from app.services.activity_import import ItemResult, OverBudget, import_next_item

logger = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(seconds=CONFIG.get("IMPORT_POLL_INTERVAL_SECONDS", 2))
SWEEP_INTERVAL = timedelta(seconds=CONFIG.get("IMPORT_SWEEP_INTERVAL_SECONDS", 60))
PURGE_AFTER = timedelta(days=CONFIG.get("IMPORT_PURGE_AFTER_DAYS", 30))


class ImportWorker:
    """Imports the queued items of ``importer``'s provider one at a time, with
    ``import_next_item``, the provider's ``budget_policy`` and its ``token_refresher``,
    and sweeps the provider's items and budget every ``sweep_interval``.

    ``transaction`` and ``clock`` replace the database and the current time
    (timezone-aware).
    """

    def __init__(
        self,
        importer: ProviderImporter,
        *,
        budget_policy: BudgetPolicy,
        token_refresher: TokenRefresher | None = None,
        transaction: RepositoriesFactory = transaction,
        clock: Callable[[], datetime] = utc_now,
        poll_interval: timedelta = POLL_INTERVAL,
        sweep_interval: timedelta = SWEEP_INTERVAL,
    ):
        self._importer = importer
        self._budget_policy = budget_policy
        self._token_refresher = token_refresher
        self._provider = importer.provider
        self._transaction = transaction
        self._clock = clock
        self._poll_interval = poll_interval
        self._sweep_interval = sweep_interval
        self._hold: OverBudget | None = None  # the budget hold last logged

    async def run(self, stop: anyio.Event) -> None:
        """Import items until ``stop`` is set.

        ``stop`` is checked between items, so an item being imported when it is set is
        finished first. When no item can be claimed, the loop waits ``poll_interval``.
        A round that raises is logged, and the loop goes on; a failed sweep is tried
        again at the next ``sweep_interval``.
        """
        next_sweep = self._clock()
        while not stop.is_set():
            claimed = False
            try:
                if self._clock() >= next_sweep:
                    next_sweep = self._clock() + self._sweep_interval
                    await self.sweep()
                claimed = await self.run_once()
            except Exception:
                logger.exception("%s import: round failed", self._provider)
            if not claimed:
                wait = min(self._poll_interval, next_sweep - self._clock())
                with anyio.move_on_after(wait.total_seconds()):
                    await stop.wait()

    async def run_once(self) -> bool:
        """Import the next claimable item. Returns whether an item was claimed."""
        result = await import_next_item(
            self._importer,
            budget_policy=self._budget_policy,
            token_refresher=self._token_refresher,
            transaction=self._transaction,
            clock=self._clock,
        )
        if isinstance(result, OverBudget):
            if result != self._hold:
                logger.info(
                    "%s import: the budget holds the next item back until %s",
                    self._provider,
                    result.resumes_at,
                )
            self._hold = result
            return False
        self._hold = None
        return isinstance(result, ItemResult)

    async def sweep(self) -> None:
        """Queue the items of workers that stopped mid-import again, or make them dead
        once they used the importer's ``max_attempts``, delete failures older than
        ``PURGE_AFTER``, and delete the budget buckets no window counts any more."""
        now = self._clock()
        async with self._transaction() as repos:
            expired = await repos.import_queue.expire_leases(
                self._provider, max_attempts=self._importer.max_attempts, now=now
            )
            purged = await repos.import_queue.purge_failures(
                self._provider, max_age=PURGE_AFTER, now=now
            )
            buckets = await repos.budgets.delete_old_buckets(
                self._provider, policy=self._budget_policy, now=now
            )
        if expired:
            logger.warning(
                "%s import: %d items with an expired lease taken back", self._provider, expired
            )
        if purged:
            logger.info("%s import: %d old dead or blocked items deleted", self._provider, purged)
        if buckets:
            logger.debug("%s import: %d old budget buckets deleted", self._provider, buckets)
