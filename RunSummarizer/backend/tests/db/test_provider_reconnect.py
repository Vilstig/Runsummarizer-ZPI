"""Connecting a provider through ``ProviderConnectionService`` against Postgres: the new
tokens are stored, the user's blocked items are queued again, and a user connected to
another provider is refused.
"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import ImportStatus, Provider
from app.domain.errors import AnotherProviderConnectedError
from app.domain.models import ProviderCredentials
from app.providers.base import AuthorizationStart, LinkResult
from app.providers.registry import PROVIDERS
from app.services.accounts.connection import ProviderConnectionService
from app.services.accounts.oauth_state import create_oauth_state
from app.services.accounts.provider_account_service import ProviderAccountService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
RECONNECTED = NOW + timedelta(hours=1)
ATHLETE_ID = 9001  # the athlete of the ``user_id`` fixture
NEW_CREDENTIALS = ProviderCredentials("new-access", "new-refresh", 4_102_444_800)


class FakeOAuth:
    """Links ``account`` with ``NEW_CREDENTIALS`` for every callback."""

    def __init__(self, account: str):
        self.account = account
        self.exchanges = 0

    def default_redirect_uri(self) -> str:
        return "https://api.example/callback"

    async def start_authorization(self, state: str, redirect_uri: str) -> AuthorizationStart:
        return AuthorizationStart(url=f"https://provider.example/auth?state={state}", secrets={})

    async def exchange(self, params: Mapping[str, str], secrets: dict[str, str]) -> LinkResult:
        self.exchanges += 1
        return LinkResult(provider_user_id=self.account, credentials=NEW_CREDENTIALS)

    async def revoke(self, credentials: ProviderCredentials) -> None:
        return None


@pytest.fixture(autouse=True)
def state_secret(monkeypatch):
    monkeypatch.setattr("app.services.accounts.oauth_state.OAUTH_STATE_SECRET", "test-secret")


def connection(
    user_repo, provider_repo, queue, provider: Provider, oauth: FakeOAuth
) -> ProviderConnectionService:
    definition = replace(
        PROVIDERS[Provider.STRAVA], provider=provider, oauth=oauth, token_refresher=None
    )
    return ProviderConnectionService(
        ProviderAccountService(definition, user_repo, provider_repo),
        queue,
        clock=lambda: RECONNECTED,
    )


async def callback(service: ProviderConnectionService, user_id: str, provider: Provider) -> None:
    state = create_oauth_state(user_id, provider=provider)
    await service.complete({"code": "code-123", "state": state}, state, None)


async def block_item(queue, user_id: str, activity_key: str) -> None:
    await queue.enqueue_sync(
        user_id, Provider.STRAVA, [activity_key], spacing=timedelta(seconds=20), now=NOW
    )
    item = await queue.lock_next(Provider.STRAVA, now=NOW)
    claim = await queue.claim(item, lease=timedelta(minutes=5), now=NOW)
    await queue.block(claim, last_error="401", now=NOW)


async def test_reconnecting_stores_the_tokens_and_queues_blocked_items_again(
    user_repo, provider_repo, queue, user_id
):
    await block_item(queue, user_id, "strava_1")
    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id=user_id)
    strava = connection(
        user_repo, provider_repo, queue, Provider.STRAVA, FakeOAuth(str(ATHLETE_ID))
    )

    await callback(strava, user_id, Provider.STRAVA)

    assert (
        await provider_repo.get_provider_credentials(provider=Provider.STRAVA, user_id=user_id)
        == NEW_CREDENTIALS
    )
    assert await provider_repo.get_connected_provider(user_id) is Provider.STRAVA
    counts = await queue.count_by_status(user_id, Provider.STRAVA)
    assert counts[ImportStatus.BLOCKED] == 0
    assert counts[ImportStatus.QUEUED] == 1
    assert (await queue.lock_next(Provider.STRAVA, now=RECONNECTED)).activity_key == "strava_1"


async def test_connecting_another_provider_while_connected_is_a_409(
    user_repo, provider_repo, queue, user_id
):
    oauth = FakeOAuth("555")
    garmin = connection(user_repo, provider_repo, queue, Provider.GARMIN, oauth)

    with pytest.raises(AnotherProviderConnectedError) as connect:
        await garmin.accounts.build_connect_url(user_id)
    with pytest.raises(AnotherProviderConnectedError) as linked:
        await callback(garmin, user_id, Provider.GARMIN)

    assert str(connect.value) == str(linked.value) == str(AnotherProviderConnectedError())
    assert oauth.exchanges == 0
    assert await provider_repo.get_connected_provider(user_id) is Provider.STRAVA


async def test_another_provider_can_be_connected_after_a_disconnect(
    user_repo, provider_repo, queue, user_id
):
    garmin = connection(user_repo, provider_repo, queue, Provider.GARMIN, FakeOAuth("555"))

    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id=user_id)
    await callback(garmin, user_id, Provider.GARMIN)

    assert await provider_repo.get_connected_provider(user_id) is Provider.GARMIN
