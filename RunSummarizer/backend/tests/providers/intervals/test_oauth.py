from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import LinkResult
from app.providers.intervals.errors import IntervalsError, IntervalsUnauthorizedError
from app.providers.intervals.oauth import (
    INTERVALS_AUTHORIZE_URL,
    INTERVALS_DISCONNECT_URL,
    INTERVALS_TIMEOUT,
    INTERVALS_TOKEN_URL,
    IntervalsOAuth,
    build_authorize_url,
    disconnect,
    exchange_code,
    generate_pkce,
)
from tests.helpers import configure_intervals

pytestmark = pytest.mark.anyio

TOKEN_RESPONSE = {
    "token_type": "Bearer",
    "access_token": "d842c1fc",
    "scope": "ACTIVITY:READ",
    "athlete": {"id": "2049151", "name": "Vil Stig"},
}


def recording_transport(sent: list, response: httpx.Response) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return response

    return httpx.MockTransport(handler)


# ---------- generate_pkce ----------


def test_the_verifier_is_within_the_pkce_length_bounds():
    verifier, _ = generate_pkce()
    assert 43 <= len(verifier) <= 128


def test_the_challenge_is_the_sha256_of_the_verifier():
    import base64
    import hashlib

    verifier, challenge = generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode()


def test_each_pair_is_fresh():
    assert generate_pkce() != generate_pkce()


# ---------- exchange_code / disconnect ----------


async def exchange(transport: httpx.MockTransport) -> dict:
    return await exchange_code(
        client_id="client-id",
        client_secret="client-secret",
        code="code-123",
        code_verifier="verifier-1",
        transport=transport,
    )


async def test_exchange_code_posts_the_code_and_verifier():
    sent = []

    token_data = await exchange(recording_transport(sent, httpx.Response(200, json=TOKEN_RESPONSE)))

    assert token_data == TOKEN_RESPONSE
    [request] = sent
    assert request.method == "POST"
    assert str(request.url) == INTERVALS_TOKEN_URL
    assert dict(parse_qsl(request.content.decode())) == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "code": "code-123",
        "code_verifier": "verifier-1",
    }


async def test_exchange_code_allows_the_full_timeout():
    sent = []

    await exchange(recording_transport(sent, httpx.Response(200, json=TOKEN_RESPONSE)))

    assert sent[0].extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), INTERVALS_TIMEOUT
    )


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_a_rejected_code_raises_unauthorized(status):
    transport = recording_transport([], httpx.Response(status, json={"message": "Bad Request"}))

    with pytest.raises(IntervalsUnauthorizedError) as raised:
        await exchange(transport)

    assert raised.value.response.status_code == status


async def test_a_server_error_raises_a_plain_http_status_error():
    transport = recording_transport([], httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await exchange(transport)

    assert not isinstance(raised.value, IntervalsError)


async def test_disconnect_sends_the_bearer_token():
    sent = []
    transport = recording_transport(sent, httpx.Response(200, json={}))

    await disconnect(access_token="access-1", transport=transport)

    [request] = sent
    assert request.method == "DELETE"
    assert str(request.url) == INTERVALS_DISCONNECT_URL
    assert request.headers["Authorization"] == "Bearer access-1"


@pytest.mark.parametrize("status", [401, 403])
async def test_a_rejected_token_raises_unauthorized_on_disconnect(status):
    transport = recording_transport([], httpx.Response(status))

    with pytest.raises(IntervalsUnauthorizedError):
        await disconnect(access_token="access-1", transport=transport)


# ---------- IntervalsOAuth ----------

REDIRECT_URI = "https://api.example/api/providers/intervals/callback"
CREDENTIALS = ProviderCredentials("access-1", None, None)


@pytest.fixture(autouse=True)
def intervals_app(monkeypatch):
    configure_intervals(
        monkeypatch, client_id="client-id", client_secret="client-secret", redirect_uri=REDIRECT_URI
    )


def answering(response: httpx.Response | Exception, sent: list | None = None):
    """A transport answering every request with ``response``, or raising it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    return httpx.MockTransport(handler)


async def test_the_default_redirect_uri_is_the_configured_one():
    assert IntervalsOAuth().default_redirect_uri() == REDIRECT_URI


async def test_authorization_starts_at_the_authorize_url_with_pkce_and_the_state():
    start = await IntervalsOAuth().start_authorization("state-1", REDIRECT_URI)

    url = urlsplit(start.url)
    assert f"{url.scheme}://{url.netloc}{url.path}" == INTERVALS_AUTHORIZE_URL
    params = dict(parse_qsl(url.query))
    assert params["client_id"] == "client-id"
    assert params["redirect_uri"] == REDIRECT_URI
    assert params["scope"] == "ACTIVITY:READ"
    assert params["state"] == "state-1"
    assert params["code_challenge_method"] == "S256"
    assert "code_challenge" in params
    assert start.secrets.keys() == {"code_verifier"}


async def test_build_authorize_url_carries_every_parameter():
    url = build_authorize_url(
        client_id="client-id",
        redirect_uri=REDIRECT_URI,
        state="state-1",
        code_challenge="challenge-1",
    )

    assert dict(parse_qsl(urlsplit(url).query)) == {
        "client_id": "client-id",
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "ACTIVITY:READ",
        "state": "state-1",
        "code_challenge": "challenge-1",
        "code_challenge_method": "S256",
    }


async def test_the_exchange_links_the_athlete_with_their_token():
    sent = []
    oauth = IntervalsOAuth(transport=answering(httpx.Response(200, json=TOKEN_RESPONSE), sent))

    link = await oauth.exchange({"code": "code-123", "state": "s"}, {"code_verifier": "verifier-1"})

    assert link == LinkResult("2049151", ProviderCredentials("d842c1fc", None, None))
    [request] = sent
    body = dict(parse_qsl(request.content.decode()))
    assert body["code"] == "code-123"
    assert body["code_verifier"] == "verifier-1"


@pytest.mark.parametrize(
    "params",
    [{"error": "access_denied", "state": "s"}, {"state": "s"}, {"code": ""}],
    ids=["declined", "no-code", "empty-code"],
)
async def test_a_declined_or_codeless_callback_is_an_authorization_error(params):
    sent = []
    oauth = IntervalsOAuth(transport=answering(httpx.Response(200), sent))

    with pytest.raises(ProviderAuthorizationError):
        await oauth.exchange(params, {"code_verifier": "verifier-1"})

    assert sent == []


async def test_a_callback_without_a_stored_verifier_is_an_authorization_error():
    oauth = IntervalsOAuth(transport=answering(httpx.Response(200)))

    with pytest.raises(ProviderAuthorizationError):
        await oauth.exchange({"code": "code-123"}, {})


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_a_code_intervals_rejects_is_an_authorization_error(status):
    oauth = IntervalsOAuth(transport=answering(httpx.Response(status)))

    with pytest.raises(ProviderAuthorizationError):
        await oauth.exchange({"code": "code-123"}, {"code_verifier": "v"})


@pytest.mark.parametrize(
    "outcome",
    [httpx.Response(500), httpx.Response(429), httpx.ConnectTimeout("timed out")],
    ids=["500", "429", "timeout"],
)
async def test_a_failing_exchange_is_unavailable(outcome):
    oauth = IntervalsOAuth(transport=answering(outcome))

    with pytest.raises(ProviderUnavailableError):
        await oauth.exchange({"code": "code-123"}, {"code_verifier": "v"})


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": "a", "scope": "ACTIVITY:READ"},
        {"access_token": "a", "scope": "ACTIVITY:READ", "athlete": {}},
        {"scope": "ACTIVITY:READ", "athlete": {"id": "1"}},
    ],
    ids=["no-athlete", "no-athlete-id", "no-access-token"],
)
async def test_an_unusable_token_response_is_a_response_error(payload):
    oauth = IntervalsOAuth(transport=answering(httpx.Response(200, json=payload)))

    with pytest.raises(ProviderResponseError):
        await oauth.exchange({"code": "code-123"}, {"code_verifier": "v"})


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, text="<html>maintenance</html>"), httpx.Response(200, json=[])],
    ids=["not-json", "not-an-object"],
)
async def test_a_token_response_that_is_not_a_json_object_is_a_response_error(response):
    oauth = IntervalsOAuth(transport=answering(response))

    with pytest.raises(ProviderResponseError):
        await oauth.exchange({"code": "code-123"}, {"code_verifier": "v"})


@pytest.mark.parametrize("scope", ["", "WELLNESS:READ", "CALENDAR:READ,SETTINGS:WRITE"])
async def test_a_scope_without_activity_access_is_an_authorization_error(scope):
    oauth = IntervalsOAuth(
        transport=answering(httpx.Response(200, json={**TOKEN_RESPONSE, "scope": scope}))
    )

    with pytest.raises(ProviderAuthorizationError):
        await oauth.exchange({"code": "code-123"}, {"code_verifier": "v"})


@pytest.mark.parametrize(
    "scope", ["ACTIVITY:READ", "ACTIVITY:WRITE", "WELLNESS:READ,ACTIVITY:WRITE"]
)
async def test_either_activity_scope_is_accepted(scope):
    oauth = IntervalsOAuth(
        transport=answering(httpx.Response(200, json={**TOKEN_RESPONSE, "scope": scope}))
    )

    link = await oauth.exchange({"code": "code-123"}, {"code_verifier": "v"})

    assert link.provider_user_id == "2049151"


async def test_revoking_disconnects_the_app():
    sent = []
    oauth = IntervalsOAuth(transport=answering(httpx.Response(200, json={}), sent))

    await oauth.revoke(CREDENTIALS)

    [request] = sent
    assert str(request.url) == INTERVALS_DISCONNECT_URL
    assert request.headers["Authorization"] == "Bearer access-1"


@pytest.mark.parametrize("status", [401, 403])
async def test_an_access_token_intervals_rejects_counts_as_revoked(status):
    await IntervalsOAuth(transport=answering(httpx.Response(status))).revoke(CREDENTIALS)


@pytest.mark.parametrize(
    "outcome", [httpx.Response(503), httpx.ConnectTimeout("timed out")], ids=["503", "timeout"]
)
async def test_a_failing_revocation_is_unavailable(outcome):
    with pytest.raises(ProviderUnavailableError):
        await IntervalsOAuth(transport=answering(outcome)).revoke(CREDENTIALS)
