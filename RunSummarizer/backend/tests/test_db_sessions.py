from contextlib import asynccontextmanager

import pytest

from app.api.deps import get_session
from app.db import client, factory
from app.db.repositories.postgres.activities import PostgresActivityRepository
from app.db.repositories.postgres.budgets import PostgresProviderBudgetRepository
from app.db.repositories.postgres.hr_zones import PostgresHeartRateZonesRepository
from app.db.repositories.postgres.import_queue import PostgresImportQueueRepository
from app.db.repositories.postgres.providers import PostgresProviderRepository
from app.db.repositories.postgres.users import PostgresUserRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeSession:
    """Records what the session owner does with the session it opens."""

    def __init__(self):
        self.committed = False
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.closed = True

    async def commit(self):
        self.committed = True


@pytest.fixture
def session(monkeypatch) -> FakeSession:
    session = FakeSession()
    monkeypatch.setattr(client, "get_sessionmaker", lambda: lambda: session)
    return session


# ---------- open_session ----------


async def test_open_session_commits_when_the_block_exits_cleanly(session):
    async with client.open_session() as opened:
        assert opened is session
        assert not session.committed

    assert session.committed
    assert session.closed


async def test_open_session_skips_the_commit_when_the_block_raises(session):
    with pytest.raises(RuntimeError, match="boom"):
        async with client.open_session():
            raise RuntimeError("boom")

    assert not session.committed
    assert session.closed


# ---------- get_session (the request dependency) ----------


async def test_get_session_commits_the_request_session(session):
    async with asynccontextmanager(get_session)() as opened:
        assert opened is session

    assert session.committed


# ---------- transaction ----------


async def test_transaction_shares_a_committed_session(session):
    async with factory.transaction() as (
        activities,
        users,
        providers,
        budgets,
        import_queue,
        hr_zones,
    ):
        assert isinstance(activities, PostgresActivityRepository)
        assert isinstance(users, PostgresUserRepository)
        assert isinstance(providers, PostgresProviderRepository)
        assert isinstance(budgets, PostgresProviderBudgetRepository)
        assert isinstance(import_queue, PostgresImportQueueRepository)
        assert isinstance(hr_zones, PostgresHeartRateZonesRepository)

    assert session.committed
