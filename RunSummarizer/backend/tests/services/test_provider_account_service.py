"""ProviderAccountService: connecting, linking and disconnecting a provider account, with a
fake ``ProviderOAuth``."""

import functools
from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import parse_qsl

import pytest

from app.domain.enums import Provider
from app.domain.errors import (
    AnotherProviderConnectedError,
    OAuthStateMismatchError,
    ProviderAccountTakenError,
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    ProviderUnavailableError,
    UserNotFoundError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import (
    AuthorizationStart,
    LinkResult,
    TokenRefresher,
)
from app.providers.registry import PROVIDERS
from app.providers.strava.oauth import StravaOAuth, StravaTokenRefresher
from app.services.accounts.oauth_state import (
    create_oauth_state,
    seal_oauth_secrets,
    verify_oauth_state,
)
from app.services.accounts.provider_account_service import ProviderAccountService
from app.services.credentials import fresh_credentials
from tests.services.fakes import REFRESHED, TokenUpdate

pytestmark = pytest.mark.anyio

USER_ID = "user_abc"
DEFAULT_REDIRECT = "https://api.example/api/providers/strava/callback"
CREDENTIALS = ProviderCredentials("access-1", "refresh-1", 4_102_444_800)
REFRESHER = object()  # stands in for the provider's TokenRefresher


class FakeOAuth:
    """Records each call; ``exchange`` and ``revoke`` raise ``error`` when it is set."""

    def __init__(self):
        self.secrets: dict[str, str] = {}  # what start_authorization hands to the callback
        self.started: list[tuple[str, str]] = []  # (state, redirect URI)
        self.exchanged: list[tuple[dict, dict]] = []  # (params, secrets)
        self.revoked: list[ProviderCredentials] = []
        self.error: Exception | None = None

    def default_redirect_uri(self) -> str:
        return DEFAULT_REDIRECT

    async def start_authorization(self, state: str, redirect_uri: str) -> AuthorizationStart:
        self.started.append((state, redirect_uri))
        return AuthorizationStart(
            url=f"https://provider.example/auth?state={state}", secrets=self.secrets
        )

    async def exchange(self, params: Mapping[str, str], secrets: dict[str, str]) -> LinkResult:
        self.exchanged.append((dict(params), secrets))
        if self.error is not None:
            raise self.error
        return LinkResult(provider_user_id="101", credentials=CREDENTIALS)

    async def revoke(self, credentials: ProviderCredentials) -> None:
        if self.error is not None:
            raise self.error
        self.revoked.append(credentials)


class MemoryUsers:
    def __init__(self):
        self.ensured: list[str] = []

    async def ensure_user_exists(self, user_id: str) -> None:
        self.ensured.append(user_id)


class MemoryProviders:
    def __init__(self):
        self.connected: Provider | None = None  # the user's connected provider
        self.links: list[dict] = []
        self.link_error: Exception | None = None
        self.cleared: list[tuple[Provider, str]] = []

    async def get_connected_provider(self, user_id: str) -> Provider | None:
        return self.connected

    async def link_provider(self, **fields) -> None:
        if self.link_error is not None:
            raise self.link_error
        self.links.append(fields)

    async def clear_provider_credentials(self, *, provider: Provider, user_id: str) -> bool:
        self.cleared.append((provider, user_id))
        return True


class FreshCredentials:
    """Stands in for ``fresh_credentials``: returns ``credentials``, or raises ``error``."""

    def __init__(self):
        self.credentials: ProviderCredentials = CREDENTIALS
        self.error: Exception | None = None
        self.calls: list[tuple[Provider, str, TokenRefresher | None]] = []

    async def __call__(
        self, provider: Provider, user_id: str, refresher: TokenRefresher | None
    ) -> ProviderCredentials:
        self.calls.append((provider, user_id, refresher))
        if self.error is not None:
            raise self.error
        return self.credentials


@pytest.fixture(autouse=True)
def secrets_keys(monkeypatch):
    monkeypatch.setattr("app.services.accounts.oauth_state.OAUTH_STATE_SECRET", "test-secret")
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "test-key")


@pytest.fixture
def oauth() -> FakeOAuth:
    return FakeOAuth()


@pytest.fixture
def users() -> MemoryUsers:
    return MemoryUsers()


@pytest.fixture
def providers() -> MemoryProviders:
    return MemoryProviders()


@pytest.fixture
def fresh() -> FreshCredentials:
    return FreshCredentials()


@pytest.fixture
def service(oauth, users, providers, fresh) -> ProviderAccountService:
    definition = replace(PROVIDERS[Provider.STRAVA], oauth=oauth, token_refresher=REFRESHER)
    return ProviderAccountService(definition, users, providers, fresh_credentials=fresh)


def callback_params(state: str, **params: str) -> dict[str, str]:
    return {"code": "code-123", "state": state, **params}


# ---------- build_connect_url ----------


async def test_connect_binds_the_state_to_the_user_and_provider(service, users, oauth):
    start = await service.build_connect_url(user_id=USER_ID)

    assert users.ensured == [USER_ID]
    assert verify_oauth_state(start.state, cookie_state=start.state, provider=Provider.STRAVA) == (
        USER_ID
    )
    assert oauth.started == [(start.state, DEFAULT_REDIRECT)]
    assert start.authorize_url == f"https://provider.example/auth?state={start.state}"
    assert start.redirect_uri == DEFAULT_REDIRECT


async def test_connect_uses_a_given_redirect_uri(service, oauth):
    start = await service.build_connect_url(user_id=USER_ID, redirect_uri="https://app.example/cb")

    assert start.redirect_uri == "https://app.example/cb"
    assert oauth.started == [(start.state, "https://app.example/cb")]


async def test_connect_without_secrets_seals_none(service):
    start = await service.build_connect_url(user_id=USER_ID)

    assert start.sealed_secrets is None


async def test_connect_seals_the_secrets_for_the_callback(service, oauth):
    oauth.secrets = {"code_verifier": "verifier-1"}

    start = await service.build_connect_url(user_id=USER_ID)

    assert start.sealed_secrets is not None
    assert "verifier-1" not in start.sealed_secrets
    await service.handle_callback(callback_params(start.state), start.state, start.sealed_secrets)
    assert oauth.exchanged[0][1] == {"code_verifier": "verifier-1"}


async def test_connect_is_refused_while_another_provider_is_connected(service, providers, oauth):
    providers.connected = Provider.GARMIN

    with pytest.raises(AnotherProviderConnectedError):
        await service.build_connect_url(user_id=USER_ID)

    assert oauth.started == []


async def test_connect_is_allowed_while_the_same_provider_is_connected(service, providers):
    providers.connected = Provider.STRAVA

    start = await service.build_connect_url(user_id=USER_ID)

    assert start.state


# ---------- handle_callback ----------


async def test_callback_links_the_account_and_returns_the_user(service, providers, oauth):
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    linked = await service.handle_callback(callback_params(state, scope="read"), state, None)

    assert linked == USER_ID
    assert oauth.exchanged == [(callback_params(state, scope="read"), {})]
    assert providers.links == [
        {
            "provider": Provider.STRAVA,
            "user_id": USER_ID,
            "provider_user_id": "101",
            "credentials": CREDENTIALS,
        }
    ]


@pytest.mark.parametrize(
    "params", [{"code": "code-123", "state": "nope"}, {"code": "code-123"}, {}]
)
async def test_callback_rejects_a_state_that_does_not_match_before_the_exchange(
    service, oauth, params
):
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    with pytest.raises(OAuthStateMismatchError):
        await service.handle_callback(params, state, None)

    assert oauth.exchanged == []


@pytest.mark.parametrize("cookie", ["plain-text", "enc:v1:not-a-token"])
async def test_callback_rejects_secrets_that_are_not_sealed(service, oauth, cookie):
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    with pytest.raises(OAuthStateMismatchError):
        await service.handle_callback(callback_params(state), state, cookie)

    assert oauth.exchanged == []


async def test_callback_rejects_secrets_sealed_for_another_state(service, oauth):
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)
    other = create_oauth_state("user-2", provider=Provider.STRAVA)

    with pytest.raises(OAuthStateMismatchError):
        await service.handle_callback(
            callback_params(state), state, seal_oauth_secrets({"v": "1"}, state=other)
        )

    assert oauth.exchanged == []


async def test_callback_is_refused_while_another_provider_is_connected(service, providers, oauth):
    providers.connected = Provider.GARMIN
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    with pytest.raises(AnotherProviderConnectedError):
        await service.handle_callback(callback_params(state), state, None)

    assert oauth.exchanged == []
    assert providers.links == []


async def test_a_provider_error_from_the_exchange_propagates_and_links_nothing(
    service, providers, oauth
):
    oauth.error = ProviderAuthorizationError("declined")
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    with pytest.raises(ProviderAuthorizationError):
        await service.handle_callback(callback_params(state), state, None)

    assert providers.links == []


@pytest.mark.parametrize(
    "error",
    [
        UserNotFoundError("User does not exist"),
        ProviderAccountTakenError("already linked"),
        AnotherProviderConnectedError("race"),
    ],
)
async def test_callback_maps_link_errors(service, providers, error):
    providers.link_error = error
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    with pytest.raises(type(error)) as raised:
        await service.handle_callback(callback_params(state), state, None)

    assert str(raised.value) == str(error)


# ---------- disconnect ----------


async def test_disconnect_revokes_the_fresh_credentials_then_clears_them(
    service, providers, oauth, fresh
):
    await service.disconnect(USER_ID)

    assert fresh.calls == [(Provider.STRAVA, USER_ID, REFRESHER)]
    assert oauth.revoked == [CREDENTIALS]
    assert providers.cleared == [(Provider.STRAVA, USER_ID)]


@pytest.mark.parametrize(
    "error", [ProviderNotConnectedError("none"), ProviderAuthorizationError("rejected")]
)
async def test_disconnect_without_credentials_to_revoke_only_clears(
    service, providers, oauth, fresh, error
):
    fresh.error = error

    await service.disconnect(USER_ID)

    assert oauth.revoked == []
    assert providers.cleared == [(Provider.STRAVA, USER_ID)]


async def test_disconnect_keeps_everything_when_the_refresh_fails(service, providers, fresh):
    fresh.error = ProviderUnavailableError("down")

    with pytest.raises(ProviderUnavailableError):
        await service.disconnect(USER_ID)

    assert providers.cleared == []


async def test_disconnect_keeps_everything_when_the_revocation_fails(service, providers, oauth):
    oauth.error = ProviderUnavailableError("down")

    with pytest.raises(ProviderUnavailableError):
        await service.disconnect(USER_ID)

    assert providers.cleared == []


# ---------- disconnect with Strava's OAuth ----------


# ---------- logging ----------


async def test_an_account_link_logs_the_provider_user_id(service, caplog):
    caplog.set_level("INFO", logger="app.services.accounts.provider_account_service")
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    await service.handle_callback(callback_params(state), state, None)

    assert "strava" in caplog.text
    assert USER_ID in caplog.text
    assert "101" in caplog.text


async def test_a_disconnect_with_credentials_logs_that_the_authorization_was_revoked(
    service, caplog
):
    caplog.set_level("INFO", logger="app.services.accounts.provider_account_service")

    await service.disconnect(USER_ID)

    assert "authorization revoked" in caplog.text


async def test_a_disconnect_without_credentials_logs_that_there_was_nothing_to_revoke(
    service, fresh, caplog
):
    caplog.set_level("INFO", logger="app.services.accounts.provider_account_service")
    fresh.error = ProviderNotConnectedError("none")

    await service.disconnect(USER_ID)

    assert "nothing to revoke" in caplog.text


async def test_a_strava_disconnect_revokes_with_the_refreshed_token_and_saves_it_first(db, strava):
    db.add_strava_user(USER_ID, 101, "refresh-1")  # with an expired access token
    definition = replace(
        PROVIDERS[Provider.STRAVA],
        oauth=StravaOAuth(transport=strava.transport),
        token_refresher=StravaTokenRefresher(transport=strava.transport),
    )

    async with db.transaction() as repos:
        service = ProviderAccountService(
            definition,
            repos.users,
            repos.providers,
            fresh_credentials=functools.partial(fresh_credentials, transaction=db.transaction),
        )
        await service.disconnect(USER_ID)

    refresh, deauthorize = strava.requests
    assert refresh.url.path == "/oauth/token"
    assert deauthorize.url.path == "/oauth/deauthorize"
    assert dict(parse_qsl(deauthorize.content.decode())) == {"access_token": "access-2"}
    assert db.token_updates == [TokenUpdate(Provider.STRAVA, USER_ID, REFRESHED)]
    assert USER_ID not in db.credentials
