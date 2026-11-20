"""GET /api/v1/providers/{provider}/connect."""

from dataclasses import replace

import httpx
import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.deps import (
    get_async_provider_repository,
    get_async_user_repository,
    get_provider_account_service,
    require_user,
)
from app.domain.enums import Provider
from app.domain.errors import ProviderUnavailableError
from app.main import app
from app.providers.registry import PROVIDERS
from app.services.accounts.oauth_state import OAUTH_SECRETS_COOKIE, OAUTH_STATE_COOKIE
from app.services.accounts.provider_account_service import ConnectStart
from tests.helpers import configure_strava, unconfigure_garmin

CONNECT = "/api/v1/providers/strava/connect"
USER_ID = "user-1"
REDIRECT_URI = "http://localhost:8000/api/providers/strava/callback"
AUTHORIZE_URL = "https://www.strava.com/oauth/authorize?client_id=client-id&state=state-1"


class FakeProviderAccountService:
    """Stands in for ``ProviderAccountService``: records each call and answers from
    ``connect``."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.connect = ConnectStart(
            authorize_url=AUTHORIZE_URL,
            state="state-1",
            redirect_uri=REDIRECT_URI,
            sealed_secrets=None,
        )
        self.error: Exception | None = None

    async def build_connect_url(self, *args, **kwargs) -> ConnectStart:
        self.calls.append(("build_connect_url", args, kwargs))
        if self.error is not None:
            raise self.error
        return self.connect


def oauth_cookies(response: httpx.Response, name: str = OAUTH_STATE_COOKIE) -> list[str]:
    return [
        cookie
        for cookie in response.headers.get_list("set-cookie")
        if cookie.startswith(f"{name}=")
    ]


@pytest.fixture(autouse=True)
def current_user():
    app.dependency_overrides[require_user] = lambda: USER_ID
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def service(monkeypatch):
    configure_strava(monkeypatch, client_id="client-id", client_secret="client-secret")
    fake = FakeProviderAccountService()

    def override(provider: Provider):
        if provider not in PROVIDERS or not PROVIDERS[provider].is_configured():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider not supported",
            )
        return fake

    app.dependency_overrides[get_provider_account_service] = override
    yield fake
    app.dependency_overrides.pop(get_provider_account_service, None)


def get_connect(path: str = CONNECT) -> httpx.Response:
    return TestClient(app).get(path)


def test_the_authorize_url_comes_back_with_the_state_cookie(service):
    response = get_connect()

    assert response.status_code == 200
    assert response.json() == {"authorize_url": AUTHORIZE_URL}
    assert service.calls == [("build_connect_url", (), {"user_id": USER_ID})]

    cookies = oauth_cookies(response)
    assert len(cookies) == 1
    cookie = cookies[0].lower()
    assert "oauth_state=state-1" in cookie
    assert "httponly" in cookie
    assert "path=/api/providers/strava/callback" in cookie
    assert "secure" not in cookie
    assert oauth_cookies(response, OAUTH_SECRETS_COOKIE) == []


def test_sealed_secrets_come_back_in_their_own_cookie(service):
    service.connect = replace(service.connect, sealed_secrets="enc:v1:sealed")

    response = get_connect()

    [cookie] = oauth_cookies(response, OAUTH_SECRETS_COOKIE)
    cookie = cookie.lower()
    assert "oauth_secrets=enc:v1:sealed" in cookie
    assert "httponly" in cookie
    assert "path=/api/providers/strava/callback" in cookie


def test_an_https_redirect_sets_secure_cookies(service):
    service.connect = replace(
        service.connect, redirect_uri="https://app.example/callback", sealed_secrets="sealed"
    )

    response = get_connect()

    assert response.status_code == 200
    cookies = oauth_cookies(response) + oauth_cookies(response, OAUTH_SECRETS_COOKIE)
    assert len(cookies) == 2
    assert all("secure" in cookie.lower() for cookie in cookies)


def test_a_failing_provider_is_a_502(service):
    service.error = ProviderUnavailableError("500")

    response = get_connect()

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Failed to reach Strava. Please try again later.",
        "code": "provider_unavailable",
    }
    assert oauth_cookies(response) == []


def test_an_unconfigured_provider_is_a_404(monkeypatch):
    configure_strava(monkeypatch, client_id="")
    app.dependency_overrides[get_async_user_repository] = lambda: None
    app.dependency_overrides[get_async_provider_repository] = lambda: None
    try:
        response = get_connect()
    finally:
        app.dependency_overrides.pop(get_async_user_repository, None)
        app.dependency_overrides.pop(get_async_provider_repository, None)

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Provider not supported",
        "code": "provider_not_supported",
    }


def test_an_unsupported_provider_is_a_404(service, monkeypatch):
    unconfigure_garmin(monkeypatch)

    response = get_connect("/api/v1/providers/garmin/connect")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Provider not supported",
        "code": "not_found",
    }
    assert service.calls == []


def test_an_unknown_provider_is_rejected(service):
    response = get_connect("/api/v1/providers/foo/connect")

    assert response.status_code == 422
    assert service.calls == []
