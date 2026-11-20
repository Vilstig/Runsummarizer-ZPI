"""Central domain-error handlers: status, code, Retry-After, and the catch-all 500."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers
from app.domain.enums import Provider
from app.domain.errors import (
    ActivityNotFoundError,
    DomainError,
    FetchError,
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    ProviderPausedError,
    ProviderUnavailableError,
    RateLimitedError,
    UnknownLapError,
)


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/activity")
    async def activity():
        raise ActivityNotFoundError("Activity not found")

    @app.get("/lap")
    async def lap():
        raise UnknownLapError("Unknown lapIndex: 9")

    @app.get("/providers/{provider}/sync")
    async def sync(provider: str):
        raise ProviderNotConnectedError(f"User x has no {provider} credentials")

    @app.get("/providers/{provider}/auth")
    async def auth(provider: str):
        raise ProviderAuthorizationError("revoked")

    @app.get("/providers/{provider}/down")
    async def down(provider: str):
        raise ProviderUnavailableError("timeout")

    @app.get("/providers/{provider}/fetch")
    async def fetch(provider: str):
        raise FetchError("generic")

    @app.get("/providers/{provider}/paused")
    async def paused(provider: str):
        raise ProviderPausedError(Provider(provider), datetime.now(UTC) + timedelta(seconds=90))

    @app.get("/providers/{provider}/rate")
    async def rate(provider: str):
        raise RateLimitedError("429", until=datetime.now(UTC) + timedelta(seconds=30))

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internals")

    @app.get("/domain")
    async def domain():
        raise DomainError("unmapped domain error")

    return TestClient(app, raise_server_exceptions=False)


def test_activity_not_found_is_404_with_code(client):
    response = client.get("/activity")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}


def test_unknown_lap_is_400_with_code(client):
    response = client.get("/lap")

    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown lapIndex: 9", "code": "unknown_lap"}


def test_provider_not_connected_uses_the_path_provider_name(client):
    response = client.get("/providers/strava/sync")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Strava not connected",
        "code": "provider_not_connected",
    }


def test_provider_authorization_uses_the_path_provider_name(client):
    response = client.get("/providers/strava/auth")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Strava authorization expired. Please reconnect Strava.",
        "code": "provider_reauthorization_required",
    }


def test_fetch_error_is_502_without_leaking_internals(client):
    response = client.get("/providers/strava/down")

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Failed to reach Strava. Please try again later.",
        "code": "provider_unavailable",
    }


def test_generic_fetch_error_is_also_502(client):
    response = client.get("/providers/garmin/fetch")

    assert response.status_code == 502
    assert response.json()["code"] == "provider_unavailable"
    assert "Garmin" in response.json()["detail"]


def test_rate_limited_falls_through_to_fetch_error_mapping(client):
    """``RateLimitedError`` is a ``FetchError``; services turn it into
    ``ProviderPausedError`` before the API. Left untranslated it is a 502."""
    response = client.get("/providers/strava/rate")

    assert response.status_code == 502
    assert response.json()["code"] == "provider_unavailable"


def test_provider_paused_is_503_with_retry_after(client):
    response = client.get("/providers/strava/paused")

    assert response.status_code == 503
    assert response.json()["code"] == "provider_rate_limited"
    assert int(response.headers["retry-after"]) >= 1


def test_unhandled_errors_are_a_500_without_internals(client):
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "An unexpected error occurred.",
        "code": "internal_error",
    }
    assert "secret" not in response.text


def test_an_unmapped_domain_error_is_a_500(client):
    response = client.get("/domain")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
