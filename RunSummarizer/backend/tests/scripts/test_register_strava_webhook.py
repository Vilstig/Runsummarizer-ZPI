from collections.abc import Callable
from functools import partial

import httpx
import pytest

from app.providers.strava import webhooks
from scripts import register_strava_webhook as script
from tests.helpers import configure_strava

CALLBACK_URL = "https://example.test/api/webhooks/strava/path-secret"
SUBSCRIPTIONS_PATH = "/api/v3/push_subscriptions"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    configure_strava(
        monkeypatch,
        client_id="client-id",
        client_secret="client-secret",
        webhook_verify_token="verify-token",
        webhook_path_secret="path-secret",
        webhook_callback_url=CALLBACK_URL,
    )


def strava_answering(
    monkeypatch,
    respond: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    """Route the script's helpers through a fake Strava; return the requests it receives."""
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return respond(request)

    transport = httpx.MockTransport(handler)
    for name in ("create_subscription", "delete_subscription", "list_subscriptions"):
        monkeypatch.setattr(script, name, partial(getattr(webhooks, name), transport=transport))
    return sent


def subscriptions_api(request: httpx.Request) -> httpx.Response:
    if request.method == "GET":
        return httpx.Response(200, json=[{"id": 3, "callback_url": CALLBACK_URL}])
    if request.method == "DELETE":
        return httpx.Response(204)
    return httpx.Response(201, json={"id": 4})


def test_replaces_the_existing_subscription(monkeypatch):
    sent = strava_answering(monkeypatch, subscriptions_api)

    assert script.main() == 0

    assert [(request.method, request.url.path) for request in sent] == [
        ("GET", SUBSCRIPTIONS_PATH),
        ("DELETE", f"{SUBSCRIPTIONS_PATH}/3"),
        ("POST", SUBSCRIPTIONS_PATH),
    ]


@pytest.mark.parametrize("failing_method", ["GET", "DELETE", "POST"])
def test_a_rejected_request_exits_with_strava_s_answer(monkeypatch, capsys, failing_method):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == failing_method:
            return httpx.Response(400, json={"message": "Bad Request"})
        return subscriptions_api(request)

    sent = strava_answering(monkeypatch, respond)

    assert script.main() == 1

    assert sent[-1].method == failing_method
    assert '{"message":"Bad Request"}' in capsys.readouterr().err
