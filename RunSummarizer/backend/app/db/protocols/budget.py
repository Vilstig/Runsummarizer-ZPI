from abc import abstractmethod
from datetime import datetime
from typing import Protocol

from app.domain.enums import ImportPriority
from app.domain.models import BudgetPolicy, RateLimitUsage


class AsyncProviderBudgetRepository(Protocol):
    """Each provider's app-wide rate-limit budget.

    It holds the calls made or reserved in each of the windows of the provider's
    ``BudgetPolicy``, counted in buckets, the limits the provider reported, and a pause
    on all the provider's calls. ``provider`` is a ``Provider`` value. A provider whose
    budget holds nothing yet has no usage, its policy's default limits, and no pause.
    Every method takes the current time as ``now`` (timezone-aware).
    """

    @abstractmethod
    async def reserve(
        self,
        provider: str,
        cost: int,
        *,
        policy: BudgetPolicy,
        priority: ImportPriority,
        now: datetime,
    ) -> bool:
        """Count ``cost`` more calls in every window, unless the provider's calls are
        paused or a window would pass the ceiling of ``priority``. Returns whether the
        calls were counted.

        Reservations of one provider are serialized until the transaction ends. A
        ``cost`` of 0 needs no calls and always succeeds.
        """

    @abstractmethod
    async def resumes_at(
        self,
        provider: str,
        cost: int,
        *,
        policy: BudgetPolicy,
        priority: ImportPriority,
        now: datetime,
    ) -> datetime | None:
        """The earliest time ``reserve`` of ``cost`` can succeed, or None if it can now.

        That is the latest of: the end of the pause; for each FIXED window too full,
        its next start; and for each ROLLING window too full, the time enough of its
        calls have left it.
        """

    @abstractmethod
    async def record_usage(
        self,
        provider: str,
        usage: RateLimitUsage,
        *,
        policy: BudgetPolicy,
        sent_at: datetime | None = None,
        now: datetime,
    ) -> None:
        """Store the limits the provider reported, and raise the FIXED windows' counters
        to the usage it reported.

        Counters are never lowered: they may include reservations the provider hasn't
        seen yet. ``sent_at`` is when the request the usage came with was sent (``now``
        when None). A window ``sent_at`` is not in the current bucket of is left as it
        is: the usage may be from the earlier one. Windows the policy doesn't have are
        ignored.
        """

    @abstractmethod
    async def pause(self, provider: str, until: datetime) -> None:
        """Pause all the provider's calls until ``until``. A pause that ends later is kept."""

    @abstractmethod
    async def paused_until(self, provider: str, *, now: datetime) -> datetime | None:
        """The end of the pause on the provider's calls, or None if they aren't paused
        at ``now``."""

    @abstractmethod
    async def get_usage(
        self, provider: str, *, policy: BudgetPolicy, now: datetime
    ) -> RateLimitUsage:
        """The calls counted in each window at ``now``, and each window's limit."""

    @abstractmethod
    async def delete_old_buckets(
        self, provider: str, *, policy: BudgetPolicy, now: datetime
    ) -> int:
        """Delete the buckets no window of ``policy`` counts at ``now`` any more.
        Returns how many were deleted."""
