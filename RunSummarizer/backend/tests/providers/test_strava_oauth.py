from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderResponseError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import LinkResult
from app.providers.strava.errors import (
    StravaError,
    StravaRateLimitedError,
    StravaUnauthorizedError,
)
from app.providers.strava.oauth import (
    STRAVA_AUTHORIZE_URL,
    STRAVA_DEAUTHORIZE_URL,
    STRAVA_TIMEOUT,
    STRAVA_TOKEN_URL,
    StravaOAuth,
    StravaTokenRefresher,
    deauthorize,
    exchange_code,
    refresh_access_token,
)
from tests.helpers import configure_strava

pytestmark = pytest.mark.anyio

TOKEN_RESPONSE = {
    "access_token": "access",
    "refresh_token": "refresh",
    "expires_at": 4_102_444_800,  # Unix timestamp
    "athlete": {"id": 101, "username": "vilstig"},
}


def recording_transport(sent: list, response: httpx.Response) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return response

    return httpx.MockTransport(handler)


async def exchange(transport: httpx.MockTransport) -> dict:
    return await exchange_code(
        client_id="client-id",
        client_secret="client-secret",
        code="code-123",
        transport=transport,
    )


async def test_exchange_code_posts_the_authorization_code_grant():
    sent = []

    token_data = await exchange(recording_transport(sent, httpx.Response(200, json=TOKEN_RESPONSE)))

    assert token_data == TOKEN_RESPONSE
    [request] = sent
    assert request.method == "POST"
    assert str(request.url) == STRAVA_TOKEN_URL
    assert dict(parse_qsl(request.content.decode())) == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "code": "code-123",
        "grant_type": "authorization_code",
    }


async def test_exchange_code_allows_strava_the_full_timeout():
    sent = []

    await exchange(recording_transport(sent, httpx.Response(200, json=TOKEN_RESPONSE)))

    assert sent[0].extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), STRAVA_TIMEOUT
    )


@pytest.mark.parametrize("status", [400, 401])
async def test_a_rejected_code_raises_unauthorized(status):
    transport = recording_transport([], httpx.Response(status, json={"message": "Bad Request"}))

    with pytest.raises(StravaUnauthorizedError) as raised:
        await exchange(transport)

    assert raised.value.response.status_code == status


async def test_a_429_raises_rate_limited():
    transport = recording_transport([], httpx.Response(429))

    with pytest.raises(StravaRateLimitedError):
        await exchange(transport)


async def test_a_server_error_raises_a_plain_http_status_error():
    transport = recording_transport([], httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await exchange(transport)

    assert not isinstance(raised.value, StravaError)


async def refresh(transport: httpx.MockTransport) -> dict:
    return await refresh_access_token(
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-1",
        transport=transport,
    )


async def test_refresh_access_token_posts_the_refresh_token_grant():
    sent = []
    token = {"access_token": "access-2", "refresh_token": "refresh-2", "expires_at": 4_102_444_800}

    token_data = await refresh(recording_transport(sent, httpx.Response(200, json=token)))

    assert token_data == token
    [request] = sent
    assert request.method == "POST"
    assert str(request.url) == STRAVA_TOKEN_URL
    assert dict(parse_qsl(request.content.decode())) == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "grant_type": "refresh_token",
        "refresh_token": "refresh-1",
    }


@pytest.mark.parametrize("status", [400, 401])
async def test_a_rejected_refresh_token_raises_unauthorized(status):
    transport = recording_transport([], httpx.Response(status, json={"message": "Bad Request"}))

    with pytest.raises(StravaUnauthorizedError):
        await refresh(transport)


async def test_deauthorize_posts_the_access_token():
    sent = []
    transport = recording_transport(sent, httpx.Response(200, json={"access_token": "access-1"}))

    await deauthorize(access_token="access-1", transport=transport)

    [request] = sent
    assert request.method == "POST"
    assert str(request.url) == STRAVA_DEAUTHORIZE_URL
    assert dict(parse_qsl(request.content.decode())) == {"access_token": "access-1"}


@pytest.mark.parametrize("status", [400, 401])
async def test_a_rejected_access_token_raises_unauthorized_on_deauthorize(status):
    transport = recording_transport([], httpx.Response(status, json={"message": "Bad Request"}))

    with pytest.raises(StravaUnauthorizedError):
        await deauthorize(access_token="access-1", transport=transport)


async def test_a_server_error_on_deauthorize_raises_a_plain_http_status_error():
    transport = recording_transport([], httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await deauthorize(access_token="access-1", transport=transport)

    assert not isinstance(raised.value, StravaError)


# ---------- StravaOAuth ----------

REDIRECT_URI = "https://api.example/api/providers/strava/callback"
CREDENTIALS = ProviderCredentials("access-1", "refresh-1", 4_102_444_800)
NOW = datetime(2026, 11, 11, 12, 7, tzinfo=UTC)


@pytest.fixture(autouse=True)
def strava_app(monkeypatch):
    configure_strava(
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
    assert StravaOAuth().default_redirect_uri() == REDIRECT_URI


async def test_authorization_starts_at_stravas_authorize_url_with_the_state():
    start = await StravaOAuth().start_authorization("state-1", REDIRECT_URI)

    url = urlsplit(start.url)
    assert f"{url.scheme}://{url.netloc}{url.path}" == STRAVA_AUTHORIZE_URL
    assert dict(parse_qsl(url.query)) == {
        "client_id": "client-id",
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "activity:read_all",
        "state": "state-1",
    }
    assert start.secrets == {}


async def test_the_exchange_links_the_athlete_with_their_tokens():
    sent = []
    strava_oauth = StravaOAuth(transport=answering(httpx.Response(200, json=TOKEN_RESPONSE), sent))

    link = await strava_oauth.exchange({"code": "code-123", "state": "s", "scope": "read"}, {})

    assert link == LinkResult("101", ProviderCredentials("access", "refresh", 4_102_444_800))
    [request] = sent
    assert dict(parse_qsl(request.content.decode()))["code"] == "code-123"


@pytest.mark.parametrize(
    "params", [{"error": "access_denied", "state": "s"}, {"state": "s"}, {"code": ""}]
)
async def test_a_declined_or_codeless_callback_is_an_authorization_error(params):
    sent = []
    strava_oauth = StravaOAuth(transport=answering(httpx.Response(200), sent))

    with pytest.raises(ProviderAuthorizationError):
        await strava_oauth.exchange(params, {})

    assert sent == []


@pytest.mark.parametrize("status", [400, 401])
async def test_a_code_strava_rejects_is_an_authorization_error(status):
    strava_oauth = StravaOAuth(transport=answering(httpx.Response(status)))

    with pytest.raises(ProviderAuthorizationError):
        await strava_oauth.exchange({"code": "code-123"}, {})


@pytest.mark.parametrize(
    "outcome",
    [httpx.Response(500), httpx.Response(429), httpx.ConnectTimeout("timed out")],
    ids=["500", "429", "timeout"],
)
async def test_a_failing_exchange_is_unavailable(outcome):
    strava_oauth = StravaOAuth(transport=answering(outcome))

    with pytest.raises(ProviderUnavailableError):
        await strava_oauth.exchange({"code": "code-123"}, {})


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": "a", "refresh_token": "r", "expires_at": 1},
        {"access_token": "a", "refresh_token": "r", "expires_at": 1, "athlete": {}},
        {"refresh_token": "r", "expires_at": 1, "athlete": {"id": 101}},
    ],
    ids=["no-athlete", "no-athlete-id", "no-access-token"],
)
async def test_an_unusable_token_response_is_a_response_error(payload):
    strava_oauth = StravaOAuth(transport=answering(httpx.Response(200, json=payload)))

    with pytest.raises(ProviderResponseError):
        await strava_oauth.exchange({"code": "code-123"}, {})


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, text="<html>maintenance</html>"), httpx.Response(200, json=[])],
    ids=["not-json", "not-an-object"],
)
async def test_a_token_response_that_is_not_a_json_object_is_a_response_error(response):
    strava_oauth = StravaOAuth(transport=answering(response))

    with pytest.raises(ProviderResponseError):
        await strava_oauth.exchange({"code": "code-123"}, {})


async def test_revoking_deauthorizes_the_access_token():
    sent = []
    strava_oauth = StravaOAuth(transport=answering(httpx.Response(200, json={}), sent))

    await strava_oauth.revoke(CREDENTIALS)

    [request] = sent
    assert str(request.url) == STRAVA_DEAUTHORIZE_URL
    assert dict(parse_qsl(request.content.decode())) == {"access_token": "access-1"}


@pytest.mark.parametrize("status", [400, 401])
async def test_an_access_token_strava_rejects_counts_as_revoked(status):
    await StravaOAuth(transport=answering(httpx.Response(status))).revoke(CREDENTIALS)


@pytest.mark.parametrize(
    "outcome", [httpx.Response(503), httpx.ConnectTimeout("timed out")], ids=["503", "timeout"]
)
async def test_a_failing_revocation_is_unavailable(outcome):
    with pytest.raises(ProviderUnavailableError):
        await StravaOAuth(transport=answering(outcome)).revoke(CREDENTIALS)


# ---------- StravaTokenRefresher ----------


def refresher(response: httpx.Response | Exception, sent: list | None = None):
    return StravaTokenRefresher(transport=answering(response, sent), clock=lambda: NOW)


async def test_a_refresh_trades_the_refresh_token_for_new_tokens():
    sent = []
    token = {"access_token": "access-2", "refresh_token": "refresh-2", "expires_at": 4_102_444_900}

    refreshed = await refresher(httpx.Response(200, json=token), sent).refresh(CREDENTIALS)

    assert refreshed == ProviderCredentials("access-2", "refresh-2", 4_102_444_900)
    [request] = sent
    assert dict(parse_qsl(request.content.decode())) == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "grant_type": "refresh_token",
        "refresh_token": "refresh-1",
    }


async def test_a_refresh_strava_does_not_rotate_keeps_the_refresh_token():
    token = {"access_token": "access-2", "expires_at": 4_102_444_900}

    refreshed = await refresher(httpx.Response(200, json=token)).refresh(CREDENTIALS)

    assert refreshed == ProviderCredentials("access-2", "refresh-1", 4_102_444_900)


async def test_credentials_without_a_refresh_token_cannot_be_refreshed():
    sent = []

    with pytest.raises(ProviderAuthorizationError):
        await refresher(httpx.Response(200), sent).refresh(ProviderCredentials("access-1", None, 0))

    assert sent == []


@pytest.mark.parametrize("status", [400, 401])
async def test_a_refresh_strava_rejects_is_an_authorization_error(status):
    with pytest.raises(ProviderAuthorizationError):
        await refresher(httpx.Response(status)).refresh(CREDENTIALS)


async def test_a_429_on_a_refresh_is_rate_limited_until_the_next_window():
    with pytest.raises(RateLimitedError) as raised:
        await refresher(httpx.Response(429)).refresh(CREDENTIALS)

    assert raised.value.until == datetime(2026, 11, 11, 12, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.Response(500),
        httpx.ConnectTimeout("timed out"),
        httpx.Response(200, json={}),
        httpx.Response(200, text="<html>maintenance</html>"),
        httpx.Response(200, json=[]),
    ],
    ids=["500", "timeout", "no-access-token", "not-json", "not-an-object"],
)
async def test_a_failing_refresh_is_unavailable(outcome):
    with pytest.raises(ProviderUnavailableError):
        await refresher(outcome).refresh(CREDENTIALS)
