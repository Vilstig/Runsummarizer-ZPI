"""GET and POST /api/webhooks/strava/{token}: subscription validation, and that an event
is handled before it is acknowledged."""

import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes.webhooks import providers as webhook_routes
from app.domain.enums import Provider
from app.main import app
from app.providers.base import ActivityChanged, WebhookCommand
from app.providers.strava.webhook import StravaWebhookParser

PATH_SECRET = "path-secret"
VERIFY_TOKEN = "verify-token"
EVENT = {"object_type": "activity", "object_id": 7, "aspect_type": "create", "owner_id": 101}
CHALLENGE = "challenge-from-strava"


class FakeIngest:
    """Stands in for ``ingest_webhook``: records each provider and its commands, and
    raises ``error`` when it is set.
    """

    def __init__(self):
        self.calls: list[tuple[Provider, list[WebhookCommand]]] = []
        self.error: Exception | None = None

    async def __call__(self, provider: Provider, commands: list[WebhookCommand]) -> None:
        self.calls.append((provider, list(commands)))
        if self.error is not None:
            raise self.error


@pytest.fixture
def handler(monkeypatch) -> FakeIngest:
    fake = FakeIngest()
    monkeypatch.setattr(webhook_routes, "ingest_webhook", fake)
    strava = dataclasses.replace(
        webhook_routes.PROVIDERS[Provider.STRAVA],
        webhook=StravaWebhookParser(path_secret=PATH_SECRET, verify_token=VERIFY_TOKEN),
    )
    monkeypatch.setitem(webhook_routes.PROVIDERS, Provider.STRAVA, strava)
    return fake


def post_event(path_secret: str = PATH_SECRET) -> httpx.Response:
    client = TestClient(app, raise_server_exceptions=False)
    return client.post(f"/api/webhooks/strava/{path_secret}", json=EVENT)


def get_validation(
    *,
    path_secret: str = PATH_SECRET,
    hub_mode: str | None = "subscribe",
    hub_challenge: str | None = CHALLENGE,
    hub_verify_token: str | None = VERIFY_TOKEN,
) -> httpx.Response:
    params = {}
    if hub_mode is not None:
        params["hub.mode"] = hub_mode
    if hub_challenge is not None:
        params["hub.challenge"] = hub_challenge
    if hub_verify_token is not None:
        params["hub.verify_token"] = hub_verify_token
    client = TestClient(app, raise_server_exceptions=False)
    return client.get(f"/api/webhooks/strava/{path_secret}", params=params)


def test_subscription_validation_echoes_the_challenge(handler):
    response = get_validation()

    assert response.status_code == 200
    assert response.json() == {"hub.challenge": CHALLENGE}


def test_subscription_validation_rejects_a_wrong_path_secret(handler):
    response = get_validation(path_secret="wrong-secret")

    assert response.status_code == 403


def test_subscription_validation_rejects_a_wrong_verify_token(handler):
    response = get_validation(hub_verify_token="wrong-token")

    assert response.status_code == 403


def test_subscription_validation_rejects_a_request_that_is_not_a_subscribe(handler):
    response = get_validation(hub_mode="unsubscribe")

    assert response.status_code == 400


def test_subscription_validation_rejects_a_request_without_a_challenge(handler):
    response = get_validation(hub_challenge=None)

    assert response.status_code == 400


def test_an_event_is_handled_and_acknowledged(handler):
    response = post_event()

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert handler.calls == [(Provider.STRAVA, [ActivityChanged("101", "strava_7")])]


def test_an_event_that_fails_to_be_handled_gets_500_so_strava_sends_it_again(handler):
    handler.error = RuntimeError("database unavailable")

    response = post_event()

    assert response.status_code == 500


def test_a_wrong_path_secret_is_rejected(handler):
    response = post_event("wrong-secret")

    assert response.status_code == 403
    assert handler.calls == []


def test_an_event_that_is_not_a_strava_event_gets_422(handler):
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/api/webhooks/strava/{PATH_SECRET}", json={"object_type": "activity"})

    assert response.status_code == 422
    assert handler.calls == []


def test_an_unconfigured_path_secret_rejects_every_token(handler, monkeypatch):
    strava = dataclasses.replace(
        webhook_routes.PROVIDERS[Provider.STRAVA],
        webhook=StravaWebhookParser(path_secret="", verify_token=VERIFY_TOKEN),
    )
    monkeypatch.setitem(webhook_routes.PROVIDERS, Provider.STRAVA, strava)

    assert post_event("anything").status_code == 403
    assert handler.calls == []


@pytest.mark.parametrize("provider", ["polar", "garmin"])
def test_a_provider_without_webhooks_gets_404(handler, provider, monkeypatch):
    garmin = webhook_routes.PROVIDERS[Provider.GARMIN]
    monkeypatch.setitem(
        webhook_routes.PROVIDERS, Provider.GARMIN, dataclasses.replace(garmin, webhook=None)
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/api/webhooks/{provider}/{PATH_SECRET}", json=EVENT)

    assert response.status_code == 404
