"""GET /api/v1/providers."""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_user
from app.api.routes import providers as providers_route
from app.domain.enums import Provider, SyncState
from app.main import app
from app.services.sync import ProviderStatus

PROVIDERS = "/api/v1/providers"
USER_ID = "user-1"


class FakeStatuses:
    """Stands in for ``provider_statuses``: records each user id, returns ``statuses``."""

    def __init__(self):
        self.calls: list[str] = []
        self.statuses: list[ProviderStatus] = []

    async def __call__(self, user_id: str) -> list[ProviderStatus]:
        self.calls.append(user_id)
        return self.statuses


@pytest.fixture(autouse=True)
def current_user():
    app.dependency_overrides[require_user] = lambda: USER_ID
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def statuses(monkeypatch) -> FakeStatuses:
    fake = FakeStatuses()
    monkeypatch.setattr(providers_route, "provider_statuses", fake)
    return fake


def test_every_provider_is_listed_with_the_users_status(statuses):
    statuses.statuses = [
        ProviderStatus(
            Provider.STRAVA,
            configured=True,
            can_sync=True,
            connected=True,
            sync_state=SyncState.SYNCING,
        ),
        ProviderStatus(
            Provider.GARMIN,
            configured=False,
            can_sync=False,
            connected=False,
            sync_state=SyncState.IDLE,
        ),
    ]

    response = TestClient(app).get(PROVIDERS)

    assert response.status_code == 200
    assert response.json() == [
        {
            "provider": "strava",
            "configured": True,
            "can_sync": True,
            "connected": True,
            "sync_state": "syncing",
        },
        {
            "provider": "garmin",
            "configured": False,
            "can_sync": False,
            "connected": False,
            "sync_state": "idle",
        },
    ]
    assert statuses.calls == [USER_ID]


def test_the_list_needs_a_signed_in_user(statuses):
    app.dependency_overrides.pop(require_user, None)

    response = TestClient(app).get(PROVIDERS)

    assert response.status_code == 401
    assert statuses.calls == []
