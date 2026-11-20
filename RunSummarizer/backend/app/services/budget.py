"""The generic side of each provider's app-wide rate-limit budget: recording the usage a
provider's responses report, and pausing its calls after a 429.
"""

import logging
from collections.abc import Callable
from datetime import datetime

import httpx

from app.core.clock import utc_now
from app.db.factory import RepositoriesFactory, transaction
from app.domain.enums import Provider
from app.domain.models import BudgetPolicy
from app.providers.base import ResponseObserver

logger = logging.getLogger(__name__)


def usage_recorder(
    provider: Provider,
    policy: BudgetPolicy,
    *,
    transaction: RepositoriesFactory = transaction,
    clock: Callable[[], datetime] = utc_now,
) -> ResponseObserver:
    """A ``ResponseObserver`` that records the usage ``policy.observe`` reads from each
    of the provider's responses in its budget, each in a transaction of its own, at
    ``clock()``. Responses that report no usage are ignored.
    """

    async def record_usage(response: httpx.Response, sent_at: datetime) -> None:
        if policy.observe is None:
            return
        usage = policy.observe(response)
        if usage is None:
            return
        async with transaction() as repos:
            await repos.budgets.record_usage(
                provider, usage, policy=policy, sent_at=sent_at, now=clock()
            )

    return record_usage


async def pause_provider_calls(
    provider: Provider, until: datetime, *, transaction: RepositoriesFactory = transaction
) -> None:
    """Pause all the provider's calls until ``until``, e.g. after a 429."""
    async with transaction() as repos:
        await repos.budgets.pause(provider, until)
    logger.warning("%s: calls paused until %s", provider, until)
