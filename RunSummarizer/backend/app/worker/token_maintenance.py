"""The worker's token maintenance loop: refreshes the tokens of provider connections
nothing uses, so they don't run out."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

import anyio

from app.config.loader import CONFIG
from app.core.clock import utc_now
from app.core.request_context import log_context_var
from app.db.factory import RepositoriesFactory, transaction
from app.domain.enums import Provider
from app.providers.base import ProviderDefinition
from app.services.credentials import refresh_idle_credentials

logger = logging.getLogger(__name__)

INTERVAL = timedelta(seconds=CONFIG.get("TOKEN_MAINTENANCE_INTERVAL_SECONDS", 86400))
REFRESH_TIMEOUT = timedelta(
    seconds=CONFIG.get("TOKEN_MAINTENANCE_REFRESH_TIMEOUT_SECONDS", 60)
)  # for one user's token refresh
# users whose unused tokens one pass refreshes, per provider, at most
USERS_PER_PASS = CONFIG.get("TOKEN_MAINTENANCE_USERS_PER_PASS", 100)


def maintained(definitions: Sequence[ProviderDefinition]) -> list[ProviderDefinition]:
    """The ``definitions`` whose unused tokens are refreshed: those with a
    ``refresh_idle_after`` and a ``token_refresher``."""
    return [
        definition
        for definition in definitions
        if definition.refresh_idle_after is not None and definition.token_refresher is not None
    ]


class TokenMaintenance:
    """Refreshes, every ``interval``, the unused tokens of each provider in ``definitions``
    that ``maintained`` keeps, through ``refresh_idle_credentials``: at most
    ``users_per_pass`` users a provider, each refresh cut off after ``refresh_timeout``.

    ``transaction`` and ``clock`` replace the database and the current time
    (timezone-aware).
    """

    def __init__(
        self,
        definitions: Sequence[ProviderDefinition],
        *,
        transaction: RepositoriesFactory = transaction,
        clock: Callable[[], datetime] = utc_now,
        interval: timedelta = INTERVAL,
        refresh_timeout: timedelta = REFRESH_TIMEOUT,
        users_per_pass: int = USERS_PER_PASS,
    ):
        self._definitions = maintained(definitions)
        self._transaction = transaction
        self._clock = clock
        self._interval = interval
        self._refresh_timeout = refresh_timeout
        self._users_per_pass = users_per_pass

    @property
    def providers(self) -> list[Provider]:
        """The providers whose unused tokens are refreshed."""
        return [definition.provider for definition in self._definitions]

    async def run(self, stop: anyio.Event) -> None:
        """Run a pass at once, then one every ``interval``, until ``stop`` is set.

        ``stop`` is checked between passes and between providers; a pass being made
        when it is set finishes the provider it is at.
        """
        while not stop.is_set():
            await self.run_once(stop)
            with anyio.move_on_after(self._interval.total_seconds()):
                await stop.wait()

    async def run_once(self, stop: anyio.Event | None = None) -> None:
        """Refresh each provider's unused tokens. A provider whose pass raises is logged
        and tried again at the next pass; the other providers' passes still run. Each
        provider's log lines carry the log context ``token-maintenance:<provider>``."""
        for definition in self._definitions:
            if stop is not None and stop.is_set():
                return
            provider = definition.provider
            context_token = log_context_var.set(f"token-maintenance:{provider}")
            try:
                await self._run_provider(definition)
            finally:
                log_context_var.reset(context_token)

    async def _run_provider(self, definition: ProviderDefinition) -> None:
        provider = definition.provider
        try:
            result = await refresh_idle_credentials(
                provider,
                definition.token_refresher,
                definition.refresh_idle_after,
                self._users_per_pass,
                refresh_timeout=self._refresh_timeout,
                transaction=self._transaction,
                clock=self._clock,
            )
        except Exception:
            logger.exception("%s token maintenance: pass failed", provider)
            return
        if result.refreshed or result.cleared or result.failed:
            logger.info(
                "%s token maintenance: unused tokens refreshed for %d users, "
                "cleared for %d, failed for %d",
                provider,
                result.refreshed,
                result.cleared,
                result.failed,
            )
