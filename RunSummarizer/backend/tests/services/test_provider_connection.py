"""Completing a provider connection: link the account, then unblock the user's items."""

from datetime import UTC, datetime

import pytest

from app.domain.enums import Provider
from app.domain.errors import ProviderAccountTakenError, ProviderUnavailableError
from app.services.accounts.connection import ProviderConnectionService

pytestmark = pytest.mark.anyio

USER_ID = "user_abc"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
PARAMS = {"code": "code-123", "state": "state"}  # the callback's query parameters


class FakeAccounts:
    provider = Provider.STRAVA

    def __init__(self):
        self.callbacks: list[dict] = []
        self.disconnected: list[str] = []
        self.error: Exception | None = None

    async def handle_callback(
        self, params: dict, cookie_state: str | None, cookie_secrets: str | None
    ) -> str:
        self.callbacks.append(
            {"params": params, "cookie_state": cookie_state, "cookie_secrets": cookie_secrets}
        )
        if self.error is not None:
            raise self.error
        return USER_ID

    async def disconnect(self, user_id: str) -> None:
        self.disconnected.append(user_id)
        if self.error is not None:
            raise self.error


class FakeImportQueue:
    def __init__(self):
        self.unblocked: list[tuple[str, str, datetime]] = []
        self.deleted: list[tuple[str, str]] = []

    async def unblock(self, user_id: str, provider: str, *, now: datetime) -> int:
        self.unblocked.append((user_id, provider, now))
        return 0

    async def delete_user_items(self, user_id: str, provider: str) -> int:
        self.deleted.append((user_id, provider))
        return 0


@pytest.fixture
def accounts() -> FakeAccounts:
    return FakeAccounts()


@pytest.fixture
def import_queue() -> FakeImportQueue:
    return FakeImportQueue()


@pytest.fixture
def connection(accounts, import_queue) -> ProviderConnectionService:
    return ProviderConnectionService(accounts, import_queue, clock=lambda: NOW)


async def test_complete_links_the_account_then_unblocks_the_users_items(
    connection, accounts, import_queue
):
    await connection.complete(PARAMS, "state", "sealed")

    assert accounts.callbacks == [
        {"params": PARAMS, "cookie_state": "state", "cookie_secrets": "sealed"}
    ]
    assert import_queue.unblocked == [(USER_ID, Provider.STRAVA, NOW)]


async def test_a_failed_link_unblocks_nothing(connection, accounts, import_queue):
    accounts.error = ProviderAccountTakenError("already linked")

    with pytest.raises(ProviderAccountTakenError):
        await connection.complete(PARAMS, "state", None)

    assert import_queue.unblocked == []


async def test_disconnect_revokes_the_authorization_then_deletes_the_users_items(
    connection, accounts, import_queue
):
    await connection.disconnect(USER_ID)

    assert accounts.disconnected == [USER_ID]
    assert import_queue.deleted == [(USER_ID, Provider.STRAVA)]


async def test_a_failed_disconnect_deletes_nothing(connection, accounts, import_queue):
    accounts.error = ProviderUnavailableError("timed out")

    with pytest.raises(ProviderUnavailableError):
        await connection.disconnect(USER_ID)

    assert import_queue.deleted == []
