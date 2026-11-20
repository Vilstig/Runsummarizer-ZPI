"""Fixtures for the repository contract suite.

The suite never touches real data: it uses ``POSTGRES_DSN_TEST`` and runs each
test inside a transaction that is rolled back afterwards. Tests of how concurrent
transactions interact commit for real instead, through ``committed_transaction``,
and only touch the user of ``committed_user_id``, which is deleted afterwards.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import POSTGRES_DSN, POSTGRES_DSN_TEST
from app.db.factory import Repositories, RepositoriesFactory
from app.db.models import User
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
from app.domain.enums import Provider
from app.domain.models import ActivityRecord, ProviderCredentials
from tests.db.builders import make_activity, raw_payload_of
from tests.helpers import reset_rate_limit_buckets

# Strava access-token expiry for seeded users. It only has to round-trip
# unchanged as the Unix timestamp it was given.
SEED_STRAVA_EXPIRES_AT = 4_102_444_800  # 2100-01-01T00:00:00Z
COMMITTED_USER_ID = "committed-user"


@pytest.fixture(autouse=True)
def fresh_rate_limit_buckets(monkeypatch):
    """Start each test with full rate-limit buckets: API requests share one client IP."""
    reset_rate_limit_buckets(monkeypatch)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """One event loop for the whole session; asyncpg runs on asyncio only."""
    return "asyncio"


def _postgres_address(dsn: str) -> tuple:
    """(host, port, database) of a Postgres DSN."""
    url = make_url(dsn)
    return url.host, url.port or 5432, url.database


def _postgres_test_dsn() -> str:
    if not POSTGRES_DSN_TEST:
        pytest.skip("POSTGRES_DSN_TEST is not set")
    if POSTGRES_DSN and _postgres_address(POSTGRES_DSN_TEST) == _postgres_address(POSTGRES_DSN):
        pytest.fail(
            "POSTGRES_DSN_TEST must point at a different database than POSTGRES_DSN: "
            "the contract suite writes to it."
        )
    return POSTGRES_DSN_TEST


def _repositories(session: AsyncSession) -> Repositories:
    return Repositories(
        activities=PostgresActivityRepository(session),
        users=PostgresUserRepository(session),
        providers=PostgresProviderRepository(session),
        budgets=PostgresProviderBudgetRepository(session),
        import_queue=PostgresImportQueueRepository(session),
        hr_zones=PostgresHeartRateZonesRepository(session),
    )


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """The session behind ``repositories``, for reading tables the contract doesn't expose."""
    engine = create_async_engine(_postgres_test_dsn())
    connection = await engine.connect()
    transaction = await connection.begin()
    # The session commits into a savepoint, so the outer rollback still discards
    # everything the test wrote.
    session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def repositories(db_session: AsyncSession) -> Repositories:
    return _repositories(db_session)


@pytest.fixture
async def committed_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_postgres_test_dsn())
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def committed_transaction(committed_engine: AsyncEngine) -> RepositoriesFactory:
    """``app.db.factory.transaction`` over the test database.

    Each block runs in a transaction and connection of its own, committed when the
    block exits cleanly, so concurrent blocks interact as concurrent processes do.
    Only for the users of ``committed_user_id``, which is deleted afterwards.
    """
    sessions = async_sessionmaker(committed_engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction() -> AsyncIterator[Repositories]:
        async with sessions() as session:
            yield _repositories(session)
            await session.commit()

    return transaction


@pytest.fixture
async def committed_user_id(
    committed_engine: AsyncEngine, committed_transaction: RepositoriesFactory
) -> AsyncIterator[str]:
    """A Strava user committed to the test database, deleted afterwards with all that
    cascades from them."""
    async with committed_transaction() as repos:
        await repos.users.ensure_user_exists(COMMITTED_USER_ID)
        await repos.providers.link_provider(
            provider=Provider.STRAVA,
            user_id=COMMITTED_USER_ID,
            provider_user_id="9101",
            credentials=ProviderCredentials("access-9101", "refresh-9101", SEED_STRAVA_EXPIRES_AT),
        )
    try:
        yield COMMITTED_USER_ID
    finally:
        async with committed_engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == COMMITTED_USER_ID))


@pytest.fixture
def rolled_back_transaction(repositories):
    """A ``RepositoriesFactory`` whose blocks all run in the test's transaction."""

    @asynccontextmanager
    async def transaction():
        yield repositories

    return transaction


@pytest.fixture
def activity_repo(repositories: Repositories) -> AsyncActivityRepository:
    return repositories.activities


@pytest.fixture
def user_repo(repositories: Repositories) -> AsyncUserRepository:
    return repositories.users


@pytest.fixture
def hr_zones_repo(repositories: Repositories) -> AsyncHeartRateZonesRepository:
    return repositories.hr_zones


@pytest.fixture
def provider_repo(repositories: Repositories) -> AsyncProviderRepository:
    return repositories.providers


@pytest.fixture
def budget(repositories: Repositories) -> AsyncProviderBudgetRepository:
    return repositories.budgets


@pytest.fixture
def queue(repositories: Repositories) -> AsyncImportQueueRepository:
    return repositories.import_queue


@pytest.fixture
def link_user(user_repo: AsyncUserRepository, provider_repo: AsyncProviderRepository) -> Callable:
    """Create the user, if needed, and link a provider account."""

    async def link(
        user_id: str,
        athlete_id: int,
        *,
        provider: Provider = Provider.STRAVA,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: int | None = SEED_STRAVA_EXPIRES_AT,
    ) -> None:
        await user_repo.ensure_user_exists(user_id)
        await provider_repo.link_provider(
            provider=provider,
            user_id=user_id,
            provider_user_id=str(athlete_id),
            credentials=ProviderCredentials(
                "access" if access_token is None else access_token,
                "refresh" if refresh_token is None else refresh_token,
                expires_at,
            ),
        )

    return link


@pytest.fixture
def make_user(link_user: Callable) -> Callable:
    """Create a user through the contract and return its id."""

    async def build(athlete_id: int) -> str:
        user_id = f"user-{athlete_id}"
        await link_user(
            user_id,
            athlete_id,
            access_token=f"access-{athlete_id}",
            refresh_token=f"refresh-{athlete_id}",
        )
        return user_id

    return build


@pytest.fixture
async def user_id(make_user: Callable) -> str:
    return await make_user(9001)


@pytest.fixture
async def other_user_id(make_user: Callable) -> str:
    return await make_user(9002)


@pytest.fixture
def save_activity(activity_repo: AsyncActivityRepository, user_id: str) -> Callable:
    """Seed one activity, with ``raw_payload_of`` it unless given a raw payload, and
    return the record that was saved."""

    async def save(
        activity_id: str,
        *,
        raw_payload: dict | None = None,
        streams: dict | None = None,
        **kwargs,
    ) -> ActivityRecord:
        kwargs.setdefault("user_id", user_id)
        record = make_activity(activity_id, **kwargs)
        await activity_repo.save(
            record,
            raw_payload=raw_payload if raw_payload is not None else raw_payload_of(activity_id),
            payload_kind="strava_detail",
            streams=streams,
        )
        return record

    return save


async def until_a_query_waits_for_a_lock(engine) -> None:
    for _ in range(100):
        async with engine.connect() as connection:
            waiting = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                    )
                )
            ).scalar_one()
        if waiting:
            return
        await asyncio.sleep(0.05)
    pytest.fail("no query waited for the lock")
