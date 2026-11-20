from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, Row, and_, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderBudget, ProviderBudgetUsage
from app.db.protocols import AsyncProviderBudgetRepository
from app.domain.enums import ImportPriority, WindowKind
from app.domain.models import BudgetPolicy, BudgetWindow, RateLimitUsage, WindowUsage

budgets = ProviderBudget.__table__
budget_usage = ProviderBudgetUsage.__table__


def _fits(used: int, cost: int, limit: int, percent: int) -> bool:
    """Whether ``cost`` more calls keep ``used`` within ``percent`` of ``limit``."""
    return (used + cost) * 100 <= limit * percent


def _limit(budget: Row | None, window: BudgetWindow) -> int:
    """The window's limit: the one the provider reported, or the window's default."""
    limits = budget.limits if budget is not None else {}
    return int(limits.get(window.name, window.default_limit))


def _counted(window: BudgetWindow, now: datetime) -> ColumnElement[bool]:
    """The buckets of ``window`` that count at ``now``: for a FIXED window its current
    bucket, for a ROLLING one every bucket overlapping (now - length, now].
    """
    u = budget_usage.c
    if window.kind is WindowKind.FIXED:
        return u.bucket_start == window.bucket_start(now)
    return and_(u.bucket_start > now - window.length - window.bucket, u.bucket_start <= now)


class PostgresProviderBudgetRepository(AsyncProviderBudgetRepository):
    """Postgres store for ``AsyncProviderBudgetRepository``: one ``provider_budgets`` row
    per provider, and its calls per window and bucket in ``provider_budget_usage``.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def reserve(
        self,
        provider: str,
        cost: int,
        *,
        policy: BudgetPolicy,
        priority: ImportPriority,
        now: datetime,
    ) -> bool:
        if cost == 0:
            return True
        budget = await self._lock(provider)
        if budget.paused_until is not None and budget.paused_until > now:
            return False
        for window in policy.windows:
            used = sum(b.used for b in await self._buckets(provider, window, now))
            if not _fits(used, cost, _limit(budget, window), policy.ceiling(priority, window)):
                return False
        for window in policy.windows:
            stmt = insert(budget_usage).values(
                provider=provider,
                window=window.name,
                bucket_start=window.bucket_start(now),
                used=cost,
            )
            await self._session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[
                        budget_usage.c.provider,
                        budget_usage.c.window,
                        budget_usage.c.bucket_start,
                    ],
                    set_={"used": budget_usage.c.used + stmt.excluded.used},
                )
            )
        return True

    async def resumes_at(
        self,
        provider: str,
        cost: int,
        *,
        policy: BudgetPolicy,
        priority: ImportPriority,
        now: datetime,
    ) -> datetime | None:
        if cost == 0:
            return None
        budget = await self._load(provider)
        waits = []
        if budget is not None and budget.paused_until is not None and budget.paused_until > now:
            waits.append(budget.paused_until)
        for window in policy.windows:
            limit, percent = _limit(budget, window), policy.ceiling(priority, window)
            buckets = await self._buckets(provider, window, now)
            used = sum(b.used for b in buckets)
            if _fits(used, cost, limit, percent):
                continue
            if window.kind is WindowKind.FIXED:
                waits.append(window.bucket_start(now) + window.length)
                continue
            # The oldest bucket leaves the window first, at its end plus the window length.
            leaves = window.bucket_start(now) + window.bucket
            for bucket in buckets:
                used -= bucket.used
                leaves = bucket.bucket_start + window.bucket + window.length
                if _fits(used, cost, limit, percent):
                    break
            waits.append(leaves)
        return max(waits, default=None)

    async def record_usage(
        self,
        provider: str,
        usage: RateLimitUsage,
        *,
        policy: BudgetPolicy,
        sent_at: datetime | None = None,
        now: datetime,
    ) -> None:
        sent_at = sent_at or now
        reported = [
            (window, usage.windows[window.name])
            for window in policy.windows
            if window.name in usage.windows
        ]
        if not reported:
            return
        # Upserting the budget row also locks it, so this waits for a reservation in
        # progress, and the next one sees the raised counters.
        stmt = insert(budgets).values(
            provider=provider,
            limits={window.name: window_usage.limit for window, window_usage in reported},
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[budgets.c.provider],
                set_={
                    "limits": budgets.c.limits.op("||", return_type=JSONB)(stmt.excluded.limits),
                    "updated_at": func.now(),
                },
            )
        )
        for window, window_usage in reported:
            if window.kind is not WindowKind.FIXED:
                continue
            if window.bucket_start(sent_at) != window.bucket_start(now):
                continue
            usage_stmt = insert(budget_usage).values(
                provider=provider,
                window=window.name,
                bucket_start=window.bucket_start(now),
                used=window_usage.used,
            )
            await self._session.execute(
                usage_stmt.on_conflict_do_update(
                    index_elements=[
                        budget_usage.c.provider,
                        budget_usage.c.window,
                        budget_usage.c.bucket_start,
                    ],
                    set_={"used": func.greatest(budget_usage.c.used, usage_stmt.excluded.used)},
                )
            )

    async def pause(self, provider: str, until: datetime) -> None:
        stmt = insert(budgets).values(provider=provider, paused_until=until)
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[budgets.c.provider],
                set_={
                    "paused_until": func.greatest(
                        budgets.c.paused_until, stmt.excluded.paused_until
                    ),
                    "updated_at": func.now(),
                },
            )
        )

    async def paused_until(self, provider: str, *, now: datetime) -> datetime | None:
        budget = await self._load(provider)
        if budget is not None and budget.paused_until is not None and budget.paused_until > now:
            return budget.paused_until
        return None

    async def get_usage(
        self, provider: str, *, policy: BudgetPolicy, now: datetime
    ) -> RateLimitUsage:
        budget = await self._load(provider)
        return RateLimitUsage(
            {
                window.name: WindowUsage(
                    used=sum(b.used for b in await self._buckets(provider, window, now)),
                    limit=_limit(budget, window),
                )
                for window in policy.windows
            }
        )

    async def delete_old_buckets(
        self, provider: str, *, policy: BudgetPolicy, now: datetime
    ) -> int:
        result = await self._session.execute(
            delete(budget_usage).where(
                budget_usage.c.provider == provider,
                budget_usage.c.bucket_start < now - policy.longest_reach,
            )
        )
        return result.rowcount

    async def _load(self, provider: str) -> Row | None:
        return (
            await self._session.execute(select(budgets).where(budgets.c.provider == provider))
        ).one_or_none()

    async def _lock(self, provider: str) -> Row:
        """The provider's budget row, created when missing, locked until the transaction ends."""
        locking = select(budgets).where(budgets.c.provider == provider).with_for_update()
        budget = (await self._session.execute(locking)).one_or_none()
        if budget is not None:
            return budget
        await self._session.execute(
            insert(budgets).values(provider=provider).on_conflict_do_nothing()
        )
        return (await self._session.execute(locking)).one()

    async def _buckets(self, provider: str, window: BudgetWindow, now: datetime) -> Sequence[Row]:
        """The buckets of ``window`` that count at ``now``, oldest first."""
        u = budget_usage.c
        return (
            await self._session.execute(
                select(u.bucket_start, u.used)
                .where(u.provider == provider, u.window == window.name, _counted(window, now))
                .order_by(u.bucket_start)
            )
        ).all()
