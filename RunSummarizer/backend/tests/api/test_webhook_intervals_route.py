"""GET and POST /api/webhooks/intervals/{token}: no subscription check, and that an
event is handled before it is acknowledged."""

import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes.webhooks import providers as webhook_routes
from app.domain.enums import Provider
from app.main import app
from app.providers.base import ActivityChanged, WebhookCommand
from app.providers.intervals.webhook import IntervalsWebhookParser

PATH_SECRET = "path-secret"
WEBHOOK_SECRET = "body-secret"
EVENT = {
    "secret": WEBHOOK_SECRET,
    "events": [
        {
            "athlete_id": "2049151",
            "type": "ACTIVITY_UPLOADED",
            "timestamp": "2024-12-06T06:40:47.011+00:00",
            "activity": {"id": "i55751783", "type": "Run"},
        }
    ],
}


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
    intervals = dataclasses.replace(
        webhook_routes.PROVIDERS[Provider.INTERVALS],
        webhook=IntervalsWebhookParser(path_secret=PATH_SECRET, webhook_secret=WEBHOOK_SECRET),
    )
    monkeypatch.setitem(webhook_routes.PROVIDERS, Provider.INTERVALS, intervals)
    return fake


def post_event(path_secret: str = PATH_SECRET, payload: dict | None = None) -> httpx.Response:
    client = TestClient(app, raise_server_exceptions=False)
    return client.post(f"/api/webhooks/intervals/{path_secret}", json=payload or EVENT)


def test_a_get_is_not_a_subscription_check(handler):
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(f"/api/webhooks/intervals/{PATH_SECRET}")

    assert response.status_code == 400


def test_an_event_is_handled_and_acknowledged(handler):
    response = post_event()

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert handler.calls == [
        (Provider.INTERVALS, [ActivityChanged("2049151", "intervals_i55751783")])
    ]


def test_an_event_that_fails_to_be_handled_gets_500_so_intervals_sends_it_again(handler):
    handler.error = RuntimeError("database unavailable")

    response = post_event()

    assert response.status_code == 500


def test_a_wrong_path_secret_is_rejected(handler):
    response = post_event("wrong-secret")

    assert response.status_code == 403
    assert handler.calls == []


def test_a_wrong_body_secret_is_rejected(handler):
    response = post_event(payload={**EVENT, "secret": "wrong-secret"})

    assert response.status_code == 403
    assert handler.calls == []


def test_an_event_that_is_not_an_intervals_envelope_gets_422(handler):
    response = post_event(payload={"secret": WEBHOOK_SECRET})

    assert response.status_code == 422
    assert handler.calls == []


def test_an_unconfigured_path_secret_rejects_every_token(handler, monkeypatch):
    intervals = dataclasses.replace(
        webhook_routes.PROVIDERS[Provider.INTERVALS],
        webhook=IntervalsWebhookParser(path_secret="", webhook_secret=WEBHOOK_SECRET),
    )
    monkeypatch.setitem(webhook_routes.PROVIDERS, Provider.INTERVALS, intervals)

    assert post_event("anything").status_code == 403
    assert handler.calls == []
