"""GarminOAuth and GarminTokenRefresher: PKCE consent, the exchange with the user id and
permissions, refresh rotation, deregistration and each error mapping.
"""

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import pytest

from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderResponseError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.garmin.constants import (
    GARMIN_AUTHORIZE_URL,
    GARMIN_TOKEN_URL,
    GARMIN_USER_ID_URL,
    GARMIN_USER_PERMISSIONS_URL,
    GARMIN_USER_REGISTRATION_URL,
    USER_CALL_RETRY_DELAYS_S,
)
from app.providers.garmin.errors import TOKEN_ERROR_MAX_BYTES, oauth_error_code
from app.providers.garmin.oauth import (
    EXPIRY_MARGIN_S,
    GarminOAuth,
    GarminTokenRefresher,
    code_challenge,
    pkce_pair,
)
from tests.helpers import configure_garmin

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
REDIRECT_URI = "https://app.example/api/providers/garmin/callback"
TOKENS = {
    "access_token": "access-1",
    "refresh_token": "refresh-1",
    "expires_in": 86400,
    "token_type": "bearer",
    "refresh_token_expires_in": 7775998,
}
SECRETS = {"code_verifier": "verifier-1", "redirect_uri": REDIRECT_URI}
CREDENTIALS = ProviderCredentials("access-1", "refresh-1", 0)


@pytest.fixture(autouse=True)
def garmin_settings(monkeypatch):
    configure_garmin(
        monkeypatch,
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri=REDIRECT_URI,
    )


class FakeGarmin:
    """Garmin's OAuth and user endpoints: each answers with its ``responses`` entry."""

    def __init__(self):
        self.sent: list[httpx.Request] = []
        self.responses: dict[tuple[str, str], Callable[[], httpx.Response]] = {
            ("POST", GARMIN_TOKEN_URL): lambda: httpx.Response(200, json=TOKENS),
            ("GET", GARMIN_USER_ID_URL): lambda: httpx.Response(200, json={"userId": "user-7"}),
            ("GET", GARMIN_USER_PERMISSIONS_URL): lambda: httpx.Response(
                200, json={"permissions": ["ACTIVITY_EXPORT", "WORKOUT_IMPORT"]}
            ),
            ("DELETE", GARMIN_USER_REGISTRATION_URL): lambda: httpx.Response(204),
        }

    def answer(self, method: str, url: str, response: httpx.Response | Exception) -> None:
        def respond() -> httpx.Response:
            if isinstance(response, Exception):
                raise response
            return response

        self.responses[(method, url)] = respond

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            url = str(request.url.copy_with(query=None))
            return self.responses[(request.method, url)]()

        return httpx.MockTransport(handler)

    def requests_to(self, method: str, url: str) -> list[httpx.Request]:
        return [r for r in self.sent if r.method == method and str(r.url) == url]


@pytest.fixture
def garmin() -> FakeGarmin:
    return FakeGarmin()


INVALID_GRANT_BODY = json.dumps({"error": "invalid_grant", "error_description": "expired"})
# token-endpoint error bodies that don't say the user's grant is invalid
REFUSED_BODIES = {
    "invalid_client": json.dumps({"error": "invalid_client"}),
    "unauthorized_client": json.dumps({"error": "unauthorized_client"}),
    "invalid_request": json.dumps({"error": "invalid_request"}),
    "no body": b"",
    "garbled": b"<html>Bad Request</html>",
    "oversized": json.dumps({"error": "invalid_grant", "pad": "x" * TOKEN_ERROR_MAX_BYTES}),
}


def rejection(status: int, body: str | bytes) -> httpx.Response:
    content = body.encode() if isinstance(body, str) else body
    return httpx.Response(status, content=content, headers={"content-type": "application/json"})


def refusals_logged(caplog) -> int:
    """The ERROR records saying the token endpoint refused the app's request."""
    return sum(
        1
        for record in caplog.records
        if record.levelname == "ERROR" and "refused the app's request" in record.getMessage()
    )


class ChunkedBody(httpx.AsyncByteStream):
    """``content`` in ``CHUNK``-byte chunks; ``sent`` counts the bytes handed out."""

    CHUNK = 1024

    def __init__(self, content: bytes):
        self._content = content
        self.sent = 0

    async def __aiter__(self):
        for start in range(0, len(self._content), self.CHUNK):
            chunk = self._content[start : start + self.CHUNK]
            self.sent += len(chunk)
            yield chunk


def oauth(garmin: FakeGarmin, slept: list[float] | None = None) -> GarminOAuth:
    """``GarminOAuth`` against ``garmin``; its waits are skipped and recorded in ``slept``."""

    async def sleep(seconds: float) -> None:
        if slept is not None:
            slept.append(seconds)

    return GarminOAuth(transport=garmin.transport(), clock=lambda: NOW, sleep=sleep)


def refresher(garmin: FakeGarmin) -> GarminTokenRefresher:
    return GarminTokenRefresher(transport=garmin.transport(), clock=lambda: NOW)


# ---------- PKCE and the consent URL ----------


def test_the_pkce_challenge_is_the_unpadded_base64url_sha256_of_the_verifier():
    verifier, challenge = pkce_pair()

    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert "=" not in challenge
    assert 43 <= len(verifier) <= 128


def test_every_pkce_pair_is_new():
    assert pkce_pair()[0] != pkce_pair()[0]


async def test_the_consent_url_carries_the_challenge_and_the_secrets_its_verifier(garmin):
    start = await oauth(garmin).start_authorization("state-1", REDIRECT_URI)

    parts = urlsplit(start.url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == GARMIN_AUTHORIZE_URL
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert query == {
        "response_type": "code",
        "client_id": "client-id",
        "code_challenge": code_challenge(start.secrets["code_verifier"]),
        "code_challenge_method": "S256",
        "redirect_uri": REDIRECT_URI,
        "state": "state-1",
    }
    assert start.secrets["redirect_uri"] == REDIRECT_URI
    assert garmin.sent == []


def test_the_default_redirect_uri_is_the_configured_one(garmin):
    assert oauth(garmin).default_redirect_uri() == REDIRECT_URI


# ---------- exchange ----------


async def test_the_exchange_links_the_garmin_user_with_its_tokens(garmin):
    link = await oauth(garmin).exchange({"code": "code-1", "state": "s"}, SECRETS)

    assert link.provider_user_id == "user-7"
    assert link.credentials == ProviderCredentials(
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=int(NOW.timestamp()) + 86400 - EXPIRY_MARGIN_S,
    )
    [token_request] = garmin.requests_to("POST", GARMIN_TOKEN_URL)
    assert dict(parse_qsl(token_request.content.decode())) == {
        "grant_type": "authorization_code",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "code": "code-1",
        "code_verifier": "verifier-1",
        "redirect_uri": REDIRECT_URI,
    }
    for url in (GARMIN_USER_ID_URL, GARMIN_USER_PERMISSIONS_URL):
        [request] = garmin.requests_to("GET", url)
        assert request.headers["Authorization"] == "Bearer access-1"
    assert garmin.requests_to("DELETE", GARMIN_USER_REGISTRATION_URL) == []


async def test_a_numeric_user_id_is_kept_as_text(garmin):
    garmin.answer("GET", GARMIN_USER_ID_URL, httpx.Response(200, json={"userId": 123}))

    link = await oauth(garmin).exchange({"code": "code-1"}, SECRETS)

    assert link.provider_user_id == "123"


async def test_the_exchange_falls_back_to_the_default_redirect_uri(garmin):
    await oauth(garmin).exchange({"code": "code-1"}, {"code_verifier": "verifier-1"})

    [token_request] = garmin.requests_to("POST", GARMIN_TOKEN_URL)
    assert dict(parse_qsl(token_request.content.decode()))["redirect_uri"] == REDIRECT_URI


async def test_a_user_without_activity_export_is_deregistered_and_refused(garmin):
    garmin.answer(
        "GET",
        GARMIN_USER_PERMISSIONS_URL,
        httpx.Response(200, json={"permissions": ["WORKOUT_IMPORT"]}),
    )

    with pytest.raises(ProviderAuthorizationError, match="ACTIVITY_EXPORT"):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)

    [deregistration] = garmin.requests_to("DELETE", GARMIN_USER_REGISTRATION_URL)
    assert deregistration.headers["Authorization"] == "Bearer access-1"


async def test_a_failed_deregistration_of_a_refused_user_still_refuses(garmin):
    garmin.answer("GET", GARMIN_USER_PERMISSIONS_URL, httpx.Response(200, json={"permissions": []}))
    garmin.answer("DELETE", GARMIN_USER_REGISTRATION_URL, httpx.Response(500))

    with pytest.raises(ProviderAuthorizationError):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)


@pytest.mark.parametrize(
    ("params", "secrets"),
    [
        ({"error": "access_denied", "state": "s"}, SECRETS),
        ({"state": "s"}, SECRETS),
        ({"code": "code-1"}, {}),
    ],
    ids=["declined", "no code", "no verifier"],
)
async def test_an_unusable_callback_is_an_authorization_error(garmin, params, secrets):
    with pytest.raises(ProviderAuthorizationError):
        await oauth(garmin).exchange(params, secrets)

    assert garmin.sent == []


@pytest.mark.parametrize("status", [400, 401])
async def test_a_code_garmin_rejects_as_an_invalid_grant_is_an_authorization_error(garmin, status):
    garmin.answer("POST", GARMIN_TOKEN_URL, rejection(status, INVALID_GRANT_BODY))

    with pytest.raises(ProviderAuthorizationError):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)


@pytest.mark.parametrize("body", REFUSED_BODIES.values(), ids=REFUSED_BODIES.keys())
async def test_an_exchange_garmin_refuses_otherwise_is_unavailable_and_logged(garmin, caplog, body):
    garmin.answer("POST", GARMIN_TOKEN_URL, rejection(400, body))

    with pytest.raises(ProviderUnavailableError):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)

    assert refusals_logged(caplog) == 1


@pytest.mark.parametrize(
    "failure",
    [httpx.Response(500), httpx.Response(403), httpx.ConnectError("down"), httpx.ReadTimeout("t")],
    ids=["500", "403", "connection", "timeout"],
)
async def test_a_failing_token_endpoint_is_unavailable(garmin, failure):
    garmin.answer("POST", GARMIN_TOKEN_URL, failure)

    with pytest.raises(ProviderUnavailableError):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)


@pytest.mark.parametrize("url", [GARMIN_USER_ID_URL, GARMIN_USER_PERMISSIONS_URL])
@pytest.mark.parametrize(
    "failure", [httpx.Response(403), httpx.Response(503), httpx.ConnectError("down")]
)
async def test_a_failing_user_call_is_unavailable(garmin, url, failure):
    garmin.answer("GET", url, failure)

    with pytest.raises(ProviderUnavailableError):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)


@pytest.mark.parametrize("url", [GARMIN_USER_ID_URL, GARMIN_USER_PERMISSIONS_URL])
async def test_a_user_call_that_answers_403_at_first_is_retried(garmin, url):
    refusals = [httpx.Response(403), httpx.Response(403)]
    success = garmin.responses[("GET", url)]
    garmin.responses[("GET", url)] = lambda: refusals.pop(0) if refusals else success()
    slept: list[float] = []

    link = await oauth(garmin, slept).exchange({"code": "code-1"}, SECRETS)

    assert link.provider_user_id == "user-7"
    assert len(garmin.requests_to("GET", url)) == 3
    assert slept == list(USER_CALL_RETRY_DELAYS_S[:2])


async def test_a_user_call_that_keeps_answering_403_is_unavailable(garmin):
    garmin.answer("GET", GARMIN_USER_PERMISSIONS_URL, httpx.Response(403))
    slept: list[float] = []

    with pytest.raises(ProviderUnavailableError, match="403"):
        await oauth(garmin, slept).exchange({"code": "code-1"}, SECRETS)

    attempts = garmin.requests_to("GET", GARMIN_USER_PERMISSIONS_URL)
    assert len(attempts) == len(USER_CALL_RETRY_DELAYS_S) + 1
    assert slept == list(USER_CALL_RETRY_DELAYS_S)


@pytest.mark.parametrize(
    "failure",
    [httpx.Response(401), httpx.Response(412), httpx.Response(503), httpx.ConnectError("down")],
    ids=["401", "412", "503", "connection"],
)
async def test_a_user_call_failing_otherwise_is_not_retried(garmin, failure):
    garmin.answer("GET", GARMIN_USER_ID_URL, failure)
    slept: list[float] = []

    with pytest.raises(ProviderUnavailableError):
        await oauth(garmin, slept).exchange({"code": "code-1"}, SECRETS)

    assert len(garmin.requests_to("GET", GARMIN_USER_ID_URL)) == 1
    assert slept == []


@pytest.mark.parametrize(
    "tokens",
    [
        {"refresh_token": "r", "expires_in": 1},
        {"access_token": "a", "expires_in": 1},
        {"access_token": "a", "refresh_token": "r"},
        {"access_token": "a", "refresh_token": "r", "expires_in": "soon"},
        ["access_token"],
    ],
    ids=["no access token", "no refresh token", "no expires_in", "bad expires_in", "not a dict"],
)
async def test_a_token_response_without_the_tokens_is_a_response_error(garmin, tokens):
    garmin.answer("POST", GARMIN_TOKEN_URL, httpx.Response(200, json=tokens))

    with pytest.raises(ProviderResponseError):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)


async def test_a_token_response_that_isnt_json_is_a_response_error(garmin):
    garmin.answer("POST", GARMIN_TOKEN_URL, httpx.Response(200, text="<html>"))

    with pytest.raises(ProviderResponseError):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)


@pytest.mark.parametrize(
    ("url", "body"),
    [
        (GARMIN_USER_ID_URL, {}),
        (GARMIN_USER_ID_URL, {"userId": ""}),
        (GARMIN_USER_ID_URL, ["user-7"]),
        (GARMIN_USER_PERMISSIONS_URL, ["ACTIVITY_EXPORT"]),
        (GARMIN_USER_PERMISSIONS_URL, {}),
        (GARMIN_USER_PERMISSIONS_URL, {"permissions": "ACTIVITY_EXPORT"}),
    ],
)
async def test_a_user_response_without_its_fields_is_a_response_error(garmin, url, body):
    garmin.answer("GET", url, httpx.Response(200, json=body))

    with pytest.raises(ProviderResponseError):
        await oauth(garmin).exchange({"code": "code-1"}, SECRETS)


# ---------- revoke ----------


async def test_revoking_deregisters_the_user(garmin):
    await oauth(garmin).revoke(CREDENTIALS)

    [request] = garmin.requests_to("DELETE", GARMIN_USER_REGISTRATION_URL)
    assert request.headers["Authorization"] == "Bearer access-1"


@pytest.mark.parametrize("status", [401, 403, 412])
async def test_a_registration_garmin_no_longer_knows_counts_as_revoked(garmin, status):
    garmin.answer("DELETE", GARMIN_USER_REGISTRATION_URL, httpx.Response(status))

    await oauth(garmin).revoke(CREDENTIALS)


@pytest.mark.parametrize(
    "failure",
    [httpx.Response(500), httpx.Response(429), httpx.ConnectError("down")],
    ids=["500", "429", "connection"],
)
async def test_a_failing_deregistration_is_unavailable(garmin, failure):
    garmin.answer("DELETE", GARMIN_USER_REGISTRATION_URL, failure)

    with pytest.raises(ProviderUnavailableError):
        await oauth(garmin).revoke(CREDENTIALS)


# ---------- refresh ----------


async def test_a_refresh_replaces_both_tokens(garmin):
    rotated = {**TOKENS, "access_token": "access-2", "refresh_token": "refresh-2"}
    garmin.answer("POST", GARMIN_TOKEN_URL, httpx.Response(200, json=rotated))

    credentials = await refresher(garmin).refresh(CREDENTIALS)

    assert credentials == ProviderCredentials(
        "access-2", "refresh-2", int(NOW.timestamp()) + 86400 - EXPIRY_MARGIN_S
    )
    [request] = garmin.requests_to("POST", GARMIN_TOKEN_URL)
    assert dict(parse_qsl(request.content.decode())) == {
        "grant_type": "refresh_token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": "refresh-1",
    }


async def test_credentials_without_a_refresh_token_cant_be_refreshed(garmin):
    with pytest.raises(ProviderAuthorizationError):
        await refresher(garmin).refresh(ProviderCredentials("access-1", None, 0))

    assert garmin.sent == []


@pytest.mark.parametrize("status", [400, 401])
async def test_a_refresh_token_garmin_rejects_as_an_invalid_grant_is_an_authorization_error(
    garmin, caplog, status
):
    garmin.answer("POST", GARMIN_TOKEN_URL, rejection(status, INVALID_GRANT_BODY))

    with pytest.raises(ProviderAuthorizationError):
        await refresher(garmin).refresh(CREDENTIALS)

    assert refusals_logged(caplog) == 0


@pytest.mark.parametrize("status", [400, 401])
@pytest.mark.parametrize("body", REFUSED_BODIES.values(), ids=REFUSED_BODIES.keys())
async def test_a_refresh_garmin_refuses_otherwise_is_unavailable_and_logged(
    garmin, caplog, status, body
):
    garmin.answer("POST", GARMIN_TOKEN_URL, rejection(status, body))

    with pytest.raises(ProviderUnavailableError):
        await refresher(garmin).refresh(CREDENTIALS)

    assert refusals_logged(caplog) == 1


@pytest.mark.parametrize(
    ("body", "logged"),
    [
        (
            json.dumps({"error": "invalid_client", "error_description": "secret-ish"}),
            "invalid_client",
        ),
        (json.dumps({"error": "unauthorized_client"}), "unauthorized_client"),
        (b"", "no error code"),
    ],
    ids=["invalid_client", "unauthorized_client", "empty"],
)
async def test_the_refusal_log_names_the_error_code_and_not_the_body(garmin, caplog, body, logged):
    garmin.answer("POST", GARMIN_TOKEN_URL, rejection(401, body))

    with pytest.raises(ProviderUnavailableError):
        await refresher(garmin).refresh(CREDENTIALS)

    assert f"with 401 ({logged})" in caplog.text
    assert "secret-ish" not in caplog.text


async def test_an_error_body_is_read_no_further_than_the_cap(garmin, caplog):
    body = ChunkedBody(json.dumps({"error": "invalid_grant"}).encode() + b" " * 100_000)
    garmin.answer("POST", GARMIN_TOKEN_URL, httpx.Response(400, stream=body))

    with pytest.raises(ProviderUnavailableError):
        await refresher(garmin).refresh(CREDENTIALS)

    assert body.sent <= TOKEN_ERROR_MAX_BYTES + ChunkedBody.CHUNK
    assert refusals_logged(caplog) == 1


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b'{"error": "invalid_grant"}', "invalid_grant"),
        (b'{"error": "invalid_client", "error_description": "Bad client"}', "invalid_client"),
        (b'{"error": "x" }' + b" " * (TOKEN_ERROR_MAX_BYTES - 15), "x"),
        (b'{"error": "x" }' + b" " * (TOKEN_ERROR_MAX_BYTES - 14), None),
        (b"", None),
        (b"not json", None),
        (b"\xff\xfe", None),
        (b'["invalid_grant"]', None),
        (b'{"error": 400}', None),
        (b'{"error": "invalid grant\\n"}', None),
        (b'{"error": ""}', None),
        (b'{"message": "invalid_grant"}', None),
    ],
    ids=[
        "invalid_grant",
        "invalid_client",
        "at the cap",
        "over the cap",
        "empty",
        "not json",
        "not utf-8",
        "not an object",
        "not a string",
        "not a word",
        "blank",
        "no error key",
    ],
)
def test_oauth_error_code_reads_only_a_short_code_from_a_small_json_object(body, code):
    assert oauth_error_code(body) == code


async def test_a_rate_limited_refresh_waits_for_retry_after(garmin):
    garmin.answer("POST", GARMIN_TOKEN_URL, httpx.Response(429, headers={"Retry-After": "120"}))

    with pytest.raises(RateLimitedError) as raised:
        await refresher(garmin).refresh(CREDENTIALS)

    assert raised.value.until == NOW + timedelta(seconds=120)


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, content=json.dumps({"access_token": "a"}).encode()),
        httpx.ReadTimeout("t"),
    ],
    ids=["500", "not json", "no refresh token", "timeout"],
)
async def test_a_failing_refresh_is_unavailable(garmin, failure):
    garmin.answer("POST", GARMIN_TOKEN_URL, failure)

    with pytest.raises(ProviderUnavailableError):
        await refresher(garmin).refresh(CREDENTIALS)
