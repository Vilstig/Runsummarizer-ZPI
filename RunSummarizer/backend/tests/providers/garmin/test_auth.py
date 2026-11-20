"""PersonalApiKeyAuth: trading the Personal API key for bearer tokens."""

import base64
import json
from collections.abc import Callable

import httpx
import pytest

from app.providers.garmin.errors import GarminInvalidResponseError
from app.providers.garmin.personal_api.auth import RENEW_MARGIN_S, PersonalApiKeyAuth, jwt_expiry
from app.providers.garmin.personal_api.constants import GARMIN_PERSONAL_API_BASE, TOKEN_PATH
from app.providers.garmin.personal_api.errors import GarminUnauthorizedError

pytestmark = pytest.mark.anyio

NOW = 1_800_000_000.0  # Unix time
TOKEN_URL = f"{GARMIN_PERSONAL_API_BASE}{TOKEN_PATH}"
DATA_URL = f"{GARMIN_PERSONAL_API_BASE}/activity-service/activity/1"


def jwt(exp: float, n: int = 1) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part({'exp': exp, 'n': n})}.signature"


class FakeGarmin:
    """Garmin stand-in: the token endpoint issues JWTs ``n`` = 1, 2, … valid 24 hours from
    ``clock``; data requests are answered by ``api``, given the request and the bearer token.
    """

    def __init__(self, clock: Callable[[], float], api: Callable | None = None):
        self.clock = clock
        self.api = api or (lambda request, token: httpx.Response(200, json={"ok": True}))
        self.issued: list[str] = []
        self.sent: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        if str(request.url) == TOKEN_URL:
            token = jwt(self.clock() + 24 * 3600, n=len(self.issued) + 1)
            self.issued.append(token)
            return httpx.Response(200, text=token)
        return self.api(request, request.headers["Authorization"].removeprefix("Bearer "))


def http(garmin: FakeGarmin, auth: PersonalApiKeyAuth) -> httpx.AsyncClient:
    return httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(garmin.handler))


async def test_the_key_is_traded_once_and_the_token_reused():
    garmin = FakeGarmin(lambda: NOW)
    async with http(garmin, PersonalApiKeyAuth("key-1", clock=lambda: NOW)) as client:
        await client.get(DATA_URL)
        await client.get(DATA_URL)

    trade, first, second = garmin.sent
    assert trade.method == "POST"
    assert trade.headers["Authorization"] == "ApiKey key-1"
    assert first.headers["Authorization"] == second.headers["Authorization"]
    assert first.headers["Authorization"] == f"Bearer {garmin.issued[0]}"


async def test_a_token_expiring_within_the_margin_is_traded_for_again():
    now = [NOW]
    garmin = FakeGarmin(lambda: now[0])
    async with http(garmin, PersonalApiKeyAuth("key-1", clock=lambda: now[0])) as client:
        await client.get(DATA_URL)
        now[0] += 24 * 3600 - RENEW_MARGIN_S + 1
        await client.get(DATA_URL)

    assert len(garmin.issued) == 2
    assert garmin.sent[-1].headers["Authorization"] == f"Bearer {garmin.issued[1]}"


async def test_a_401_with_a_kept_token_is_sent_again_with_a_new_one():
    garmin = FakeGarmin(lambda: NOW)
    revoked: set[str] = set()

    def api(request, token):
        return httpx.Response(401 if token in revoked else 200)

    garmin.api = api
    async with http(garmin, PersonalApiKeyAuth("key-1", clock=lambda: NOW)) as client:
        await client.get(DATA_URL)
        revoked.add(garmin.issued[0])
        resp = await client.get(DATA_URL)

    assert resp.status_code == 200
    assert len(garmin.issued) == 2


async def test_a_401_with_a_just_traded_token_is_returned():
    garmin = FakeGarmin(lambda: NOW, api=lambda request, token: httpx.Response(401))
    async with http(garmin, PersonalApiKeyAuth("key-1", clock=lambda: NOW)) as client:
        resp = await client.get(DATA_URL)

    assert resp.status_code == 401
    assert len(garmin.issued) == 1


async def test_a_rejected_key_raises_unauthorized():
    transport = httpx.MockTransport(lambda request: httpx.Response(401))
    auth = PersonalApiKeyAuth("bad-key", clock=lambda: NOW)
    async with httpx.AsyncClient(auth=auth, transport=transport) as client:
        with pytest.raises(GarminUnauthorizedError):
            await client.get(DATA_URL)


async def test_a_token_that_isnt_a_jwt_raises():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="not-a-jwt"))
    auth = PersonalApiKeyAuth("key-1", clock=lambda: NOW)
    async with httpx.AsyncClient(auth=auth, transport=transport) as client:
        with pytest.raises(GarminInvalidResponseError):
            await client.get(DATA_URL)


def test_jwt_expiry_reads_the_exp_claim():
    assert jwt_expiry(jwt(NOW)) == NOW


def test_an_empty_key_is_refused():
    with pytest.raises(ValueError, match="key is required"):
        PersonalApiKeyAuth("")
