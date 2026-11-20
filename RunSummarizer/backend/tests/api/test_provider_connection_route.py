"""DELETE /api/v1/providers/{provider}/connection."""

import httpx
import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.deps import get_provider_connection_service, require_user
from app.domain.enums import Provider
from app.domain.errors import ProviderUnavailableError
from app.main import app
from app.providers.registry import PROVIDERS
from tests.helpers import configure_strava, unconfigure_garmin

CONNECTION = "/api/v1/providers/strava/connection"
USER_ID = "user-1"


class FakeProviderConnectionService:
    """Stands in for ``ProviderConnectionService``: records each call and raises ``error``
    when set."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.error: Exception | None = None

    async def disconnect(self, *args, **kwargs) -> None:
        self.calls.append(("disconnect", args, kwargs))
        if self.error is not None:
            raise self.error


@pytest.fixture(autouse=True)
def current_user():
    app.dependency_overrides[require_user] = lambda: USER_ID
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def service(monkeypatch):
    configure_strava(monkeypatch, client_id="client-id", client_secret="client-secret")
    fake = FakeProviderConnectionService()

    def override(provider: Provider):
        if provider not in PROVIDERS or not PROVIDERS[provider].is_configured():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider not supported",
            )
        return fake

    app.dependency_overrides[get_provider_connection_service] = override
    yield fake
    app.dependency_overrides.pop(get_provider_connection_service, None)


def delete_connection(path: str = CONNECTION) -> httpx.Response:
    return TestClient(app).delete(path)


def test_a_disconnect_is_a_204(service):
    response = delete_connection()

    assert response.status_code == 204
    assert service.calls == [("disconnect", (USER_ID,), {})]


def test_a_provider_failure_is_a_502(service):
    service.error = ProviderUnavailableError("503")

    response = delete_connection()

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Failed to reach Strava. Please try again later.",
        "code": "provider_unavailable",
    }
    assert service.calls == [("disconnect", (USER_ID,), {})]


def test_an_unsupported_provider_is_a_404(service, monkeypatch):
    unconfigure_garmin(monkeypatch)

    response = delete_connection("/api/v1/providers/garmin/connection")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Provider not supported",
        "code": "not_found",
    }
    assert service.calls == []
