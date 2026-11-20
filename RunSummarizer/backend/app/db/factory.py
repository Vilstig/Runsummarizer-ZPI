from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.client import open_session
from app.db.protocols import (
    AsyncActivityRepository,
    AsyncHeartRateZonesRepository,
    AsyncImportQueueRepository,
    AsyncProviderBudgetRepository,
    AsyncProviderRepository,
    AsyncUserRepository,
)
from app.db.repositories.postgres.activities import PostgresActivityRepository
from app.db.repositories.postgres.budgets import PostgresProviderBudgetRepository
from app.db.repositories.postgres.hr_zones import PostgresHeartRateZonesRepository
from app.db.repositories.postgres.import_queue import PostgresImportQueueRepository
from app.db.repositories.postgres.providers import PostgresProviderRepository
from app.db.repositories.postgres.users import PostgresUserRepository


def create_async_activity_repository(session: AsyncSession) -> AsyncActivityRepository:
    """The activity repository over ``session``."""
    return PostgresActivityRepository(session)


def create_async_user_repository(session: AsyncSession) -> AsyncUserRepository:
    """The user repository over ``session``."""
    return PostgresUserRepository(session)


def create_async_hr_zones_repository(session: AsyncSession) -> AsyncHeartRateZonesRepository:
    """The heart rate zone history repository over ``session``."""
    return PostgresHeartRateZonesRepository(session)


def create_async_provider_repository(session: AsyncSession) -> AsyncProviderRepository:
    """The provider repository over ``session``."""
    return PostgresProviderRepository(session)


def create_async_budget_repository(session: AsyncSession) -> AsyncProviderBudgetRepository:
    """The provider budget repository over ``session``."""
    return PostgresProviderBudgetRepository(session)


def create_async_import_queue_repository(session: AsyncSession) -> AsyncImportQueueRepository:
    """The import queue repository over ``session``."""
    return PostgresImportQueueRepository(session)


class Repositories(NamedTuple):
    activities: AsyncActivityRepository
    users: AsyncUserRepository
    providers: AsyncProviderRepository
    budgets: AsyncProviderBudgetRepository
    import_queue: AsyncImportQueueRepository
    hr_zones: AsyncHeartRateZonesRepository


# ``transaction``, or a stand-in with the same shape.
type RepositoriesFactory = Callable[[], AbstractAsyncContextManager[Repositories]]


@asynccontextmanager
async def transaction() -> AsyncGenerator[Repositories]:
    """A transaction over the repositories, for code outside a request.

    They share one ``open_session()`` session, committed when the block exits
    cleanly and rolled back when it raises.
    """
    async with open_session() as session:
        yield Repositories(
            activities=create_async_activity_repository(session),
            users=create_async_user_repository(session),
            providers=create_async_provider_repository(session),
            budgets=create_async_budget_repository(session),
            import_queue=create_async_import_queue_repository(session),
            hr_zones=create_async_hr_zones_repository(session),
        )
