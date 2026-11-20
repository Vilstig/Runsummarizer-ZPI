"""POST /api/v1/sync/{provider} and GET /api/v1/sync/{provider}/status, at Strava's URLs
and others: authentication, the provider, and the response to each service outcome.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_user
from app.api.routes import sync
from app.domain.enums import Provider, SyncState
from app.domain.errors import (
    InvalidSyncLimitError,
    InvalidSyncWindowError,
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    ProviderPausedError,
    ProviderUnavailableError,
    SyncNotSupportedError,
)
from app.main import app
from app.providers.registry import PROVIDERS
from app.services.sync import SyncStarted
from tests.helpers import configure_strava, unconfigure_garmin

SYNC = "/api/v1/sync/strava"
STATUS = "/api/v1/sync/strava/status"
USER_ID = "user-1"


class FakeSyncService:
    """Stands in for ``start_sync``: records each call, and returns or raises ``outcome``."""

    def __init__(self):
        self.calls: list[tuple[Provider, str, date | None, date | None, int | None]] = []
        self.outcome: SyncStarted | Exception = SyncStarted(queued=0, requested=False)

    async def __call__(
        self,
        provider: Provider,
        user_id: str,
        after: date | None,
        before: date | None,
        limit: int | None,
    ) -> SyncStarted:
        self.calls.append((provider, user_id, after, before, limit))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeStatusService:
    """Stands in for ``sync_status``: records each call, and returns ``state``."""

    def __init__(self):
        self.calls: list[tuple[Provider, str]] = []
        self.state = SyncState.IDLE

    async def __call__(self, provider: Provider, user_id: str) -> SyncState:
        self.calls.append((provider, user_id))
        return self.state


@pytest.fixture(autouse=True)
def current_user():
    app.dependency_overrides[require_user] = lambda: USER_ID
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture(autouse=True)
def strava_configured(monkeypatch):
    configure_strava(monkeypatch, client_id="client-id", client_secret="client-secret")


@pytest.fixture
def signed_out(current_user):
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def other_provider(monkeypatch) -> None:
    """Garmin registered as a second provider, with Strava's definition parts."""
    monkeypatch.setitem(PROVIDERS, Provider.GARMIN, PROVIDERS[Provider.STRAVA])


@pytest.fixture
def service(monkeypatch) -> FakeSyncService:
    fake = FakeSyncService()
    monkeypatch.setattr(sync, "start_sync", fake)
    return fake


@pytest.fixture
def status_service(monkeypatch) -> FakeStatusService:
    fake = FakeStatusService()
    monkeypatch.setattr(sync, "sync_status", fake)
    return fake


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def post_sync(url: str = SYNC, **params) -> httpx.Response:
    return TestClient(app).post(url, params=params, headers=auth_headers())


def get_status(url: str = STATUS) -> httpx.Response:
    return TestClient(app).get(url, headers=auth_headers())


# ---------- POST /sync/{provider} ----------


def test_a_request_without_a_token_gets_401(service, signed_out):
    response = TestClient(app).post(SYNC)

    assert response.status_code == 401
    assert service.calls == []


def test_a_queued_sync_is_accepted_with_the_status_to_poll(service):
    service.outcome = SyncStarted(queued=3, requested=False)

    response = post_sync()

    assert response.status_code == 202
    assert response.json() == {"queued": 3, "requested": False}
    assert response.headers["Location"] == "/api/v1/sync/strava/status"


def test_a_requested_sync_is_accepted_with_nothing_queued(service):
    service.outcome = SyncStarted(queued=0, requested=True)

    response = post_sync()

    assert response.status_code == 202
    assert response.json() == {"queued": 0, "requested": True}


def test_the_sync_runs_for_the_user_over_the_requested_days(service):
    post_sync(after="2026-09-01", before="2026-10-01")

    assert service.calls == [(Provider.STRAVA, USER_ID, date(2026, 9, 1), date(2026, 10, 1), None)]


def test_a_sync_without_days_leaves_the_window_to_the_service(service):
    post_sync()

    assert service.calls == [(Provider.STRAVA, USER_ID, None, None, None)]


def test_another_providers_sync_runs_for_it_with_its_status_to_poll(service, other_provider):
    response = post_sync("/api/v1/sync/garmin")

    assert response.status_code == 202
    assert response.headers["Location"] == "/api/v1/sync/garmin/status"
    assert service.calls == [(Provider.GARMIN, USER_ID, None, None, None)]


def test_an_unsupported_provider_gets_404(service, monkeypatch):
    unconfigure_garmin(monkeypatch)

    response = post_sync("/api/v1/sync/garmin")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Provider not supported",
        "code": "provider_not_supported",
    }
    assert service.calls == []


def test_a_signed_out_request_for_an_unregistered_provider_gets_401(service, signed_out):
    assert TestClient(app).post("/api/v1/sync/garmin").status_code == 401


def test_an_unknown_provider_gets_422(service):
    assert post_sync("/api/v1/sync/nope").status_code == 422
    assert service.calls == []


def test_an_invalid_window_gets_400_with_the_reason(service):
    service.outcome = InvalidSyncWindowError("'after' must be earlier than 'before'")

    response = post_sync(after="2026-10-02", before="2026-10-01")

    assert response.status_code == 400
    assert response.json() == {
        "detail": "'after' must be earlier than 'before'",
        "code": "invalid_sync_window",
    }


def test_the_limit_is_passed_to_the_service(service):
    post_sync(limit=25)

    assert service.calls == [(Provider.STRAVA, USER_ID, None, None, 25)]


def test_a_limit_with_a_window_gets_400_with_the_reason(service):
    service.outcome = InvalidSyncLimitError("'limit' can't be combined with 'after' or 'before'")

    response = post_sync(after="2026-09-01", limit=25)

    assert response.status_code == 400
    assert response.json() == {
        "detail": "'limit' can't be combined with 'after' or 'before'",
        "code": "invalid_sync_limit",
    }


@pytest.mark.parametrize("limit", [0, 501])
def test_a_limit_out_of_range_gets_422(service, limit):
    assert post_sync(limit=limit).status_code == 422
    assert service.calls == []


def test_a_user_without_strava_gets_409(service):
    service.outcome = ProviderNotConnectedError("no tokens")

    response = post_sync()

    assert response.status_code == 409
    assert response.json() == {"detail": "Strava not connected", "code": "provider_not_connected"}


def test_an_unconfigured_provider_gets_404(service, monkeypatch):
    configure_strava(monkeypatch, client_secret="")

    response = post_sync()

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Provider not supported",
        "code": "provider_not_supported",
    }
    assert service.calls == []


def test_a_provider_that_is_not_the_users_connected_one_gets_409(service, other_provider):
    service.outcome = ProviderNotConnectedError("no tokens")

    response = post_sync("/api/v1/sync/garmin")

    assert response.status_code == 409
    assert response.json() == {"detail": "Garmin not connected", "code": "provider_not_connected"}


def test_a_paused_strava_gets_503_with_retry_after(service):
    service.outcome = ProviderPausedError(
        Provider.STRAVA, datetime.now(UTC) + timedelta(seconds=120)
    )

    response = post_sync()

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Strava's rate limit is used up. Please try again later.",
        "code": "provider_rate_limited",
    }
    assert 119 <= int(response.headers["Retry-After"]) <= 120


def test_a_revoked_strava_authorization_is_a_409_asking_to_reconnect(service):
    service.outcome = ProviderAuthorizationError("401")

    response = post_sync()

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Strava authorization expired. Please reconnect Strava.",
        "code": "provider_reauthorization_required",
    }


def test_a_failing_strava_is_a_502(service):
    service.outcome = ProviderUnavailableError("500")

    response = post_sync()

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Failed to reach Strava. Please try again later.",
        "code": "provider_unavailable",
    }


def test_a_provider_without_a_syncer_gets_409(service, other_provider):
    service.outcome = SyncNotSupportedError("garmin has no syncer")

    response = post_sync("/api/v1/sync/garmin")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Garmin can't be synced. New activities arrive on their own.",
        "code": "sync_not_supported",
    }


# ---------- GET /sync/{provider}/status ----------


def test_a_status_request_without_a_token_gets_401(status_service, signed_out):
    response = TestClient(app).get(STATUS)

    assert response.status_code == 401
    assert status_service.calls == []


@pytest.mark.parametrize("state", list(SyncState))
def test_the_status_responds_with_the_sync_state(status_service, state):
    status_service.state = state

    response = get_status()

    assert response.status_code == 200
    assert response.json() == {"state": state.value}


def test_the_status_is_read_for_the_user(status_service):
    get_status()

    assert status_service.calls == [(Provider.STRAVA, USER_ID)]


def test_another_providers_status_is_read_for_it(status_service, other_provider):
    assert get_status("/api/v1/sync/garmin/status").status_code == 200

    assert status_service.calls == [(Provider.GARMIN, USER_ID)]


def test_the_status_of_an_unregistered_provider_gets_404(status_service, monkeypatch):
    registered = {provider: d for provider, d in PROVIDERS.items() if provider != Provider.GARMIN}
    monkeypatch.setattr(sync, "PROVIDERS", registered)

    assert get_status("/api/v1/sync/garmin/status").status_code == 404
    assert status_service.calls == []


def test_the_status_of_an_unconfigured_provider_is_read(status_service, monkeypatch):
    unconfigure_garmin(monkeypatch)

    assert get_status("/api/v1/sync/garmin/status").status_code == 200
    assert status_service.calls == [(Provider.GARMIN, USER_ID)]
