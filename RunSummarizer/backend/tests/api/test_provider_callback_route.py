"""GET /api/providers/strava/callback."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.deps import get_provider_connection_service
from app.api.schemas.auth import OAuthCallbackError
from app.domain.enums import Provider
from app.domain.errors import (
    AnotherProviderConnectedError,
    OAuthStateMismatchError,
    ProviderAccountTakenError,
    ProviderAuthorizationError,
    ProviderNotSupportedError,
    ProviderResponseError,
    ProviderUnavailableError,
    RateLimitedError,
    UserNotFoundError,
)
from app.main import app
from app.providers.registry import PROVIDERS
from app.services.accounts.oauth_state import OAUTH_SECRETS_COOKIE, OAUTH_STATE_COOKIE
from tests.helpers import configure_strava, unconfigure_garmin

CALLBACK = "/api/providers/strava/callback"
FRONTEND = "http://localhost:8080"
FRONTEND_CALLBACK = f"{FRONTEND}/oauth/callback"


class FakeProviderConnectionService:
    """Stands in for ``ProviderConnectionService``: records each call and raises ``error``
    when set."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.error: Exception | None = None

    async def complete(self, *args, **kwargs) -> None:
        self.calls.append(("complete", args, kwargs))
        if self.error is not None:
            raise self.error


def oauth_cookies(response: httpx.Response, name: str = OAUTH_STATE_COOKIE) -> list[str]:
    return [
        cookie
        for cookie in response.headers.get_list("set-cookie")
        if cookie.startswith(f"{name}=")
    ]


@pytest.fixture(autouse=True)
def frontend(monkeypatch):
    monkeypatch.setattr("app.api.routes.providers.FRONTEND_URL", FRONTEND)


@pytest.fixture
def service(monkeypatch):
    configure_strava(monkeypatch, client_id="client-id", client_secret="client-secret")
    fake = FakeProviderConnectionService()

    def override(provider: Provider):
        if provider not in PROVIDERS or not PROVIDERS[provider].is_configured():
            raise ProviderNotSupportedError("Provider not supported")
        return fake

    app.dependency_overrides[get_provider_connection_service] = override
    yield fake
    app.dependency_overrides.pop(get_provider_connection_service, None)


PARAMS = {"code": "code-123", "state": "state-1"}


def get_callback(
    path: str = CALLBACK,
    *,
    params: dict[str, str] = PARAMS,
    cookie: str | None = "state-1",
    secrets: str | None = None,
) -> httpx.Response:
    client = TestClient(app)
    if cookie is not None:
        client.cookies.set(OAUTH_STATE_COOKIE, cookie)
    if secrets is not None:
        client.cookies.set(OAUTH_SECRETS_COOKIE, secrets)
    return client.get(path, params=params, follow_redirects=False)


def frontend_query(response: httpx.Response) -> dict[str, list[str]]:
    """The query of the frontend callback URL ``response`` redirects to."""
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == FRONTEND_CALLBACK
    return parse_qs(location.query)


def assert_cookies_cleared(response: httpx.Response) -> None:
    for name in (OAUTH_STATE_COOKIE, OAUTH_SECRETS_COOKIE):
        cleared = oauth_cookies(response, name)
        assert cleared
        assert all("max-age=0" in cookie.lower() for cookie in cleared)


def test_a_completed_callback_redirects_with_the_provider_and_clears_both_cookies(service):
    response = get_callback(secrets="sealed")

    assert frontend_query(response) == {"provider": ["strava"]}
    assert service.calls == [("complete", (PARAMS, "state-1", "sealed"), {})]
    assert_cookies_cleared(response)


def test_every_query_parameter_is_passed_to_the_service(service):
    params = {"oauth_token": "token-1", "oauth_verifier": "verifier-1", "state": "state-1"}

    get_callback(params=params)

    assert service.calls == [("complete", (params, "state-1", None), {})]


def test_missing_cookies_are_passed_to_the_service(service):
    get_callback(cookie=None)

    assert service.calls == [("complete", (PARAMS, None, None), {})]


@pytest.mark.parametrize(
    ("params", "error", "code"),
    [
        (
            {"error": "access_denied", "state": "state-1"},
            ProviderAuthorizationError("access_denied"),
            OAuthCallbackError.DECLINED,
        ),
        (PARAMS, ProviderAuthorizationError("bad code"), OAuthCallbackError.AUTHORIZATION_FAILED),
        (
            PARAMS,
            OAuthStateMismatchError("OAuth state does not match browser session"),
            OAuthCallbackError.STATE_MISMATCH,
        ),
        (PARAMS, AnotherProviderConnectedError(), OAuthCallbackError.ANOTHER_PROVIDER_CONNECTED),
        (
            PARAMS,
            ProviderAccountTakenError("linked to another user"),
            OAuthCallbackError.ACCOUNT_TAKEN,
        ),
        (PARAMS, ProviderUnavailableError("500"), OAuthCallbackError.PROVIDER_UNAVAILABLE),
        (PARAMS, ProviderResponseError("no athlete"), OAuthCallbackError.PROVIDER_UNAVAILABLE),
        (
            PARAMS,
            RateLimitedError("429", until=datetime(2026, 11, 11, tzinfo=UTC)),
            OAuthCallbackError.PROVIDER_UNAVAILABLE,
        ),
        (PARAMS, UserNotFoundError("no user"), OAuthCallbackError.FAILED),
        (PARAMS, RuntimeError("boom"), OAuthCallbackError.FAILED),
    ],
    ids=[
        "declined",
        "rejected-grant",
        "state-mismatch",
        "another-provider",
        "account-taken",
        "unavailable",
        "unusable-response",
        "rate-limited",
        "unknown-user",
        "unexpected",
    ],
)
def test_a_failed_callback_redirects_with_an_error_code_and_clears_both_cookies(
    service, params, error, code
):
    service.error = error

    response = get_callback(params=params, secrets="sealed")

    assert frontend_query(response) == {"provider": ["strava"], "error": [code.value]}
    assert_cookies_cleared(response)


def test_a_failed_callback_reaches_the_request_dependencies_as_an_error():
    """The request's session commits only when its dependency exits cleanly, so a
    failed callback must not return normally."""
    exits: list[type[BaseException] | None] = []

    async def session() -> AsyncIterator[None]:
        try:
            yield
        except Exception as exc:
            exits.append(type(exc))
            raise
        else:
            exits.append(None)

    fake = FakeProviderConnectionService()
    fake.error = AnotherProviderConnectedError()

    def override(_session: None = Depends(session, scope="function")):
        return fake

    app.dependency_overrides[get_provider_connection_service] = override
    try:
        response = get_callback()
    finally:
        app.dependency_overrides.pop(get_provider_connection_service, None)

    assert frontend_query(response)["error"] == ["another_provider_connected"]
    assert exits and exits[0] is not None


def test_an_unsupported_provider_is_a_404(service, monkeypatch):
    unconfigure_garmin(monkeypatch)

    response = get_callback(path="/api/providers/garmin/callback")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Provider not supported",
        "code": "provider_not_supported",
    }
    assert service.calls == []
