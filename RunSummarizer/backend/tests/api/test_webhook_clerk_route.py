"""POST /api/webhooks/clerk: Svix signatures, and the user events they carry."""

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from svix.webhooks import Webhook

from app.api.deps import get_account_deletion_service, get_user_service
from app.api.routes.webhooks import clerk
from app.domain.enums import Provider
from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.main import app
from app.providers.garmin.constants import GARMIN_USER_REGISTRATION_URL
from app.providers.garmin.definition import GARMIN
from app.providers.garmin.oauth import GarminOAuth
from app.providers.intervals.definition import INTERVALS
from app.providers.intervals.oauth import INTERVALS_DISCONNECT_URL, IntervalsOAuth
from app.providers.strava.definition import STRAVA
from app.providers.strava.oauth import STRAVA_DEAUTHORIZE_URL, StravaOAuth
from app.services.accounts.deletion import AccountDeletionService
from app.services.user_service import UserService
from tests.services.fakes import FakeHeartRateZonesRepository

WEBHOOK = "/api/webhooks/clerk"
SECRET = "whsec_" + base64.b64encode(b"runsummarizer-webhook-test").decode()
OTHER_SECRET = "whsec_" + base64.b64encode(b"other-webhook-secret").decode()
CREDENTIALS = ProviderCredentials("access-1", "refresh-1", 4_102_444_800)


class FakeUserRepository:
    def __init__(self, events: list[str]):
        self.ensured: list[str] = []
        self.deleted: list[str] = []
        self._events = events

    async def ensure_user_exists(self, user_id: str) -> None:
        self.ensured.append(user_id)

    async def delete_user(self, user_id: str) -> None:
        self.deleted.append(user_id)
        self._events.append(f"delete {user_id}")


class FakeProviderRepository:
    def __init__(self, events: list[str]):
        self.connected: Provider | None = None  # the provider the user is connected to
        self._events = events

    async def get_connected_provider(self, user_id: str) -> Provider | None:
        return self.connected

    async def clear_provider_credentials(self, *, provider: Provider, user_id: str) -> bool:
        self._events.append(f"clear {provider} {user_id}")
        return True


class FreshCredentials:
    """Stands in for ``fresh_credentials``: returns ``CREDENTIALS``, or raises ``error``."""

    def __init__(self):
        self.error: Exception | None = None

    async def __call__(self, provider, user_id, refresher) -> ProviderCredentials:
        if self.error is not None:
            raise self.error
        return CREDENTIALS


class ProviderApi:
    """Answers every provider call with ``status``, and records it in ``events``."""

    def __init__(self, events: list[str]):
        self.status = 204
        self.requests: list[httpx.Request] = []
        self._events = events
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self._events.append(f"{request.method} {request.url}")
        return httpx.Response(self.status, json={})


def _signed(body: str, *, secret: str = SECRET) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "svix-id": "msg_test",
        "svix-timestamp": str(int(now.timestamp())),
        "svix-signature": Webhook(secret).sign("msg_test", now, body),
        "content-type": "application/json",
    }


def _post(client: TestClient, event: dict, *, sign: bool = True, secret: str = SECRET):
    body = json.dumps(event)
    headers = _signed(body, secret=secret) if sign else {"content-type": "application/json"}
    return client.post(WEBHOOK, content=body, headers=headers)


def _delete(client: TestClient):
    return _post(client, {"type": "user.deleted", "data": {"id": "user_abc"}})


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    monkeypatch.setattr(clerk, "CLERK_WEBHOOK_SECRET", SECRET)


@pytest.fixture
def events() -> list[str]:
    """Provider calls, credential clears and user deletions, in order."""
    return []


@pytest.fixture
def provider_api(events) -> ProviderApi:
    return ProviderApi(events)


@pytest.fixture
def providers(events) -> FakeProviderRepository:
    return FakeProviderRepository(events)


@pytest.fixture
def credentials() -> FreshCredentials:
    return FreshCredentials()


@pytest.fixture
def configured() -> dict[Provider, bool]:
    """Whether each provider counts as configured."""
    return {Provider.STRAVA: True, Provider.GARMIN: True, Provider.INTERVALS: True}


@pytest.fixture
def pauses() -> list[tuple[Provider, datetime]]:
    """The (provider, until) of each pause of a provider's calls."""
    return []


@pytest.fixture
def users(events, providers, provider_api, credentials, configured, pauses):
    repo = FakeUserRepository(events)
    definitions = {
        Provider.STRAVA: replace(
            STRAVA,
            oauth=StravaOAuth(transport=provider_api.transport),
            is_configured=lambda: configured[Provider.STRAVA],
        ),
        Provider.GARMIN: replace(
            GARMIN,
            oauth=GarminOAuth(transport=provider_api.transport),
            is_configured=lambda: configured[Provider.GARMIN],
        ),
        Provider.INTERVALS: replace(
            INTERVALS,
            oauth=IntervalsOAuth(transport=provider_api.transport),
            is_configured=lambda: configured[Provider.INTERVALS],
        ),
    }
    app.dependency_overrides[get_user_service] = lambda: UserService(
        repo, FakeHeartRateZonesRepository()
    )

    async def pause_calls(provider: Provider, until: datetime) -> None:
        pauses.append((provider, until))

    app.dependency_overrides[get_account_deletion_service] = lambda: AccountDeletionService(
        repo,
        providers,
        providers=definitions,
        fresh_credentials=credentials,
        pause_calls=pause_calls,
    )
    yield repo
    app.dependency_overrides.pop(get_user_service, None)
    app.dependency_overrides.pop(get_account_deletion_service, None)


@pytest.fixture
def client(users) -> TestClient:
    return TestClient(app)


def test_user_created_ensures_the_user(client, users):
    response = _post(client, {"type": "user.created", "data": {"id": "user_abc"}})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert users.ensured == ["user_abc"]
    assert users.deleted == []


def test_user_deleted_deletes_a_user_connected_to_no_provider(client, users, events):
    response = _delete(client)

    assert response.status_code == 200
    assert users.deleted == ["user_abc"]
    assert users.ensured == []
    assert events == ["delete user_abc"]


def test_user_deleted_deregisters_a_garmin_user_before_deleting_them(
    client, providers, provider_api, events
):
    providers.connected = Provider.GARMIN

    response = _delete(client)

    assert response.status_code == 200
    assert events == [
        f"DELETE {GARMIN_USER_REGISTRATION_URL}",
        "clear garmin user_abc",
        "delete user_abc",
    ]
    assert provider_api.requests[0].headers["authorization"] == "Bearer access-1"


def test_user_deleted_deauthorizes_a_strava_user_before_deleting_them(client, providers, events):
    providers.connected = Provider.STRAVA

    response = _delete(client)

    assert response.status_code == 200
    assert events == [
        f"POST {STRAVA_DEAUTHORIZE_URL}",
        "clear strava user_abc",
        "delete user_abc",
    ]


def test_user_deleted_disconnects_an_intervals_user_before_deleting_them(
    client, providers, provider_api, events
):
    providers.connected = Provider.INTERVALS

    response = _delete(client)

    assert response.status_code == 200
    assert events == [
        f"DELETE {INTERVALS_DISCONNECT_URL}",
        "clear intervals user_abc",
        "delete user_abc",
    ]
    assert provider_api.requests[0].headers["authorization"] == "Bearer access-1"


@pytest.mark.parametrize("provider", [Provider.GARMIN, Provider.STRAVA, Provider.INTERVALS])
def test_a_provider_that_fails_to_revoke_answers_500_and_deletes_nothing(
    client, users, providers, provider_api, events, provider
):
    providers.connected = provider
    provider_api.status = 503

    response = _delete(client)

    assert response.status_code == 500
    assert users.deleted == []
    assert len(events) == 1
    assert len(provider_api.requests) == 1


def test_a_rate_limited_refresh_pauses_the_provider_and_answers_500(
    client, users, providers, provider_api, credentials, pauses
):
    until = datetime(2026, 11, 17, 12, tzinfo=UTC)
    providers.connected = Provider.GARMIN
    credentials.error = RateLimitedError("429", until=until)

    response = _delete(client)

    assert response.status_code == 500
    assert pauses == [(Provider.GARMIN, until)]
    assert provider_api.requests == []
    assert users.deleted == []


@pytest.mark.parametrize(
    ("provider", "status"),
    [
        (Provider.GARMIN, 401),
        (Provider.GARMIN, 403),
        (Provider.STRAVA, 401),
        (Provider.INTERVALS, 401),
        (Provider.INTERVALS, 403),
    ],
)
def test_an_authorization_already_revoked_is_deleted_all_the_same(
    client, users, providers, provider_api, events, provider, status
):
    providers.connected = provider
    provider_api.status = status

    response = _delete(client)

    assert response.status_code == 200
    assert len(provider_api.requests) == 1
    assert events[1:] == [f"clear {provider} user_abc", "delete user_abc"]


@pytest.mark.parametrize(
    "error", [ProviderAuthorizationError("rejected"), ProviderNotConnectedError("none")]
)
def test_a_user_with_nothing_to_revoke_is_deleted_without_a_provider_call(
    client, providers, provider_api, credentials, events, error
):
    providers.connected = Provider.GARMIN
    credentials.error = error

    response = _delete(client)

    assert response.status_code == 200
    assert provider_api.requests == []
    assert events == ["clear garmin user_abc", "delete user_abc"]


def test_a_user_of_a_provider_that_is_not_configured_is_deleted_without_a_provider_call(
    client, providers, provider_api, configured, events, caplog
):
    providers.connected = Provider.GARMIN
    configured[Provider.GARMIN] = False

    response = _delete(client)

    assert response.status_code == 200
    assert provider_api.requests == []
    assert events == ["delete user_abc"]
    assert "without revoking their garmin authorization" in caplog.text


def test_other_events_are_acknowledged_without_writes(client, users):
    response = _post(client, {"type": "session.created", "data": {"id": "sess_abc"}})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert users.ensured == []
    assert users.deleted == []


def test_user_created_is_logged(client, users, caplog):
    caplog.set_level("INFO", logger="app.api.routes.webhooks.clerk")

    _post(client, {"type": "user.created", "data": {"id": "user_abc"}})

    assert "user_abc" in caplog.text
    assert "created" in caplog.text


def test_user_deleted_is_logged(client, users, caplog):
    caplog.set_level("INFO", logger="app.api.routes.webhooks.clerk")

    _post(client, {"type": "user.deleted", "data": {"id": "user_abc"}})

    assert "user_abc" in caplog.text
    assert "deleted" in caplog.text


def test_an_ignored_event_is_logged_at_debug(client, users, caplog):
    caplog.set_level("DEBUG", logger="app.api.routes.webhooks.clerk")

    _post(client, {"type": "session.created", "data": {"id": "sess_abc"}})

    assert "session.created" in caplog.text


def test_a_bad_signature_is_403(client, users):
    response = _post(
        client,
        {"type": "user.created", "data": {"id": "user_abc"}},
        secret=OTHER_SECRET,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "invalid signature", "code": "webhook_rejected"}
    assert users.ensured == []


def test_a_missing_signature_is_403(client, users):
    response = _post(client, {"type": "user.created", "data": {"id": "user_abc"}}, sign=False)

    assert response.status_code == 403
    assert response.json() == {"detail": "invalid signature", "code": "webhook_rejected"}
    assert users.ensured == []


def test_clerk_webhook_is_exempt_from_rate_limiting(client, monkeypatch):
    from app.ratelimiter import RateLimiterStore

    store = RateLimiterStore(max_tokens=1, refill_rate=1, interval=60)
    monkeypatch.setattr("app.ratelimiter._public_store", store)

    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 429

    response = _post(client, {"type": "user.created", "data": {"id": "user_abc"}}, sign=False)
    assert response.status_code == 403
