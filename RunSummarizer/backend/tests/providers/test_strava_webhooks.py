from urllib.parse import parse_qsl

import httpx
import pytest

from app.providers.strava.oauth import STRAVA_TIMEOUT
from app.providers.strava.webhooks import (
    PUSH_SUBSCRIPTIONS_URL,
    create_subscription,
    delete_subscription,
    list_subscriptions,
)

CREDENTIALS = {"client_id": "client-id", "client_secret": "client-secret"}
CALLBACK_URL = "https://example.test/api/webhooks/strava/path-secret"
SUBSCRIPTION = {"id": 7, "callback_url": CALLBACK_URL}


def recording_transport(sent: list, response: httpx.Response) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return response

    return httpx.MockTransport(handler)


def create(transport: httpx.MockTransport) -> dict:
    return create_subscription(
        **CREDENTIALS,
        callback_url=CALLBACK_URL,
        verify_token="verify-token",
        transport=transport,
    )


def list_(transport: httpx.MockTransport) -> list[dict]:
    return list_subscriptions(**CREDENTIALS, transport=transport)


def delete(transport: httpx.MockTransport) -> None:
    delete_subscription(subscription_id=7, **CREDENTIALS, transport=transport)


HELPERS = pytest.mark.parametrize("call", [create, list_, delete], ids=["create", "list", "delete"])


def test_create_posts_the_subscription_form():
    sent = []

    created = create(recording_transport(sent, httpx.Response(201, json=SUBSCRIPTION)))

    assert created == SUBSCRIPTION
    [request] = sent
    assert request.method == "POST"
    assert str(request.url) == PUSH_SUBSCRIPTIONS_URL
    assert dict(parse_qsl(request.content.decode())) == {
        **CREDENTIALS,
        "callback_url": CALLBACK_URL,
        "verify_token": "verify-token",
    }


def test_list_sends_the_app_credentials_as_query_params():
    sent = []

    subscriptions = list_(recording_transport(sent, httpx.Response(200, json=[SUBSCRIPTION])))

    assert subscriptions == [SUBSCRIPTION]
    [request] = sent
    assert request.method == "GET"
    assert request.url.copy_with(query=None) == PUSH_SUBSCRIPTIONS_URL
    assert dict(request.url.params) == CREDENTIALS


def test_list_returns_nothing_when_strava_answers_with_an_object():
    sent = []

    subscriptions = list_(recording_transport(sent, httpx.Response(200, json={"id": 7})))

    assert subscriptions == []


def test_delete_targets_the_subscription():
    sent = []

    delete(recording_transport(sent, httpx.Response(204)))

    [request] = sent
    assert request.method == "DELETE"
    assert request.url.copy_with(query=None) == f"{PUSH_SUBSCRIPTIONS_URL}/7"
    assert dict(request.url.params) == CREDENTIALS


@HELPERS
def test_helpers_allow_strava_the_full_timeout(call):
    sent = []

    call(recording_transport(sent, httpx.Response(200, json=[])))

    assert sent[0].extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), STRAVA_TIMEOUT
    )


@HELPERS
def test_helpers_raise_on_an_error_status(call):
    sent = []
    transport = recording_transport(sent, httpx.Response(403, json={"message": "Forbidden"}))

    with pytest.raises(httpx.HTTPStatusError) as raised:
        call(transport)

    assert raised.value.response.status_code == 403
