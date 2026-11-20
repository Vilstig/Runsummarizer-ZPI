from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from app.domain.models import ProviderCredentials, RateLimitUsage, WindowUsage
from app.providers.strava.client import StravaClient
from app.providers.strava.errors import (
    StravaError,
    StravaNotFoundError,
    StravaRateLimitedError,
    StravaUnauthorizedError,
)

pytestmark = pytest.mark.anyio

# An access token that has expired, as far as the client could tell
CREDENTIALS = ProviderCredentials("access-1", "refresh-1", expires_at=0)

READ_RATE_LIMIT = {
    "X-ReadRateLimit-Limit": "100,1000",
    "X-ReadRateLimit-Usage": "37,512",
}

API_CALLS = {
    "list": lambda strava_client: strava_client.get_running_activities(),
    "detail": lambda strava_client: strava_client.get_activity_detail(1),
    "streams": lambda strava_client: strava_client.get_activity_streams(1, ["heartrate"]),
}


def strava(api: Callable[[httpx.Request], httpx.Response], sent: list | None = None):
    """Strava stand-in: ``api`` answers every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(request)
        return api(request)

    return httpx.MockTransport(handler)


def client(transport: httpx.MockTransport, **kwargs) -> StravaClient:
    return StravaClient(CREDENTIALS, transport=transport, **kwargs)


async def test_the_given_access_token_is_used_as_it_is_without_refreshing():
    sent = []

    transport = strava(lambda request: httpx.Response(200, json={"id": 1}), sent)
    async with client(transport) as strava_client:
        await strava_client.get_activity_detail(1)

    [detail] = sent
    assert detail.url.path == "/api/v3/activities/1"
    assert detail.headers["Authorization"] == "Bearer access-1"


async def test_listing_pages_until_a_short_page():
    pages = {
        "1": [{"id": 1, "type": "Run"}, {"id": 2, "type": "Run"}],
        "2": [{"id": 3, "type": "Run"}],
    }
    requested = []

    def api(request: httpx.Request) -> httpx.Response:
        requested.append(dict(request.url.params))
        return httpx.Response(200, json=pages[request.url.params["page"]])

    async with client(strava(api)) as strava_client:
        runs = await strava_client.get_running_activities(
            after_epoch=1_000, before_epoch=2_000, per_page=2
        )

    assert [run["id"] for run in runs] == [1, 2, 3]
    assert requested == [
        {"per_page": "2", "after": "1000", "before": "2000", "page": "1"},
        {"per_page": "2", "after": "1000", "before": "2000", "page": "2"},
    ]


async def test_listing_keeps_only_runs():
    activities = [
        {"id": 1, "type": "Run"},
        {"id": 2, "type": "Ride"},
        {"id": 3, "type": "Run"},
        {"id": 4, "type": "Walk"},
    ]

    transport = strava(lambda request: httpx.Response(200, json=activities))
    async with client(transport) as strava_client:
        runs = await strava_client.get_running_activities()

    assert [run["id"] for run in runs] == [1, 3]


async def test_streams_request_the_keys_in_one_call():
    requested = []

    def api(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(
            200,
            json={
                "time": {"data": [0, 1, 2]},
                "heartrate": {"data": [140, 150, 160]},
            },
        )

    async with client(strava(api)) as strava_client:
        await strava_client.get_activity_streams(7, ["time", "heartrate"])

    [request] = requested
    assert request.url.path == "/api/v3/activities/7/streams"
    assert dict(request.url.params) == {"keys": "time,heartrate", "key_by_type": "true"}


async def test_streams_parse_into_samples_by_key():
    def api(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "time": {"data": [0, 1, 2], "series_type": "distance"},
                "heartrate": {"data": [140, 150, 160], "series_type": "distance"},
                # sent even when not requested
                "distance": {"data": [0.0, 3.0, 6.0], "series_type": "distance"},
            },
        )

    async with client(strava(api)) as strava_client:
        streams = await strava_client.get_activity_streams(7, ["time", "heartrate", "altitude"])

    assert streams == {"time": [0, 1, 2], "heartrate": [140, 150, 160]}


async def test_a_401_raises():
    unauthorized = httpx.Response(401, json={"message": "Authorization Error"})

    async with client(strava(lambda request: unauthorized)) as strava_client:
        with pytest.raises(httpx.HTTPStatusError) as raised:
            await strava_client.get_activity_detail(1)

    assert raised.value.response.status_code == 401


# ---------- typed errors ----------


@pytest.mark.parametrize("call", API_CALLS.values(), ids=list(API_CALLS))
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, StravaUnauthorizedError),
        (403, StravaUnauthorizedError),
        (404, StravaNotFoundError),
        (429, StravaRateLimitedError),
    ],
)
async def test_api_errors_raise_typed_exceptions(call, status, error):
    async with client(strava(lambda request: httpx.Response(status))) as strava_client:
        with pytest.raises(error) as raised:
            await call(strava_client)

    assert isinstance(raised.value, httpx.HTTPStatusError)
    assert raised.value.response.status_code == status


@pytest.mark.parametrize("call", API_CALLS.values(), ids=list(API_CALLS))
async def test_a_server_error_raises_a_plain_http_status_error(call):
    async with client(strava(lambda request: httpx.Response(503))) as strava_client:
        with pytest.raises(httpx.HTTPStatusError) as raised:
            await call(strava_client)

    assert not isinstance(raised.value, StravaError)


# ---------- responses ----------


async def test_every_api_response_is_passed_on_with_the_time_its_request_was_sent():
    seen = []
    times = iter(
        [datetime(2026, 10, 6, 10, 14, 59, tzinfo=UTC), datetime(2026, 10, 6, 10, 15, tzinfo=UTC)]
    )

    async def on_response(response: httpx.Response, sent_at: datetime) -> None:
        seen.append((response.request.url.path, response.status_code, sent_at))

    transport = strava(lambda request: httpx.Response(200, json={"id": 1}, headers=READ_RATE_LIMIT))
    async with client(transport, on_response=on_response, clock=lambda: next(times)) as c:
        await c.get_activity_detail(1)
        await c.get_activity_streams(1, ["heartrate"])

    assert seen == [
        ("/api/v3/activities/1", 200, datetime(2026, 10, 6, 10, 14, 59, tzinfo=UTC)),
        ("/api/v3/activities/1/streams", 200, datetime(2026, 10, 6, 10, 15, tzinfo=UTC)),
    ]


async def test_a_429_is_passed_on_before_it_raises_carrying_the_usage():
    headers = {"X-ReadRateLimit-Limit": "100,1000", "X-ReadRateLimit-Usage": "101,640"}
    seen = []

    async def on_response(response: httpx.Response, sent_at: datetime) -> None:
        seen.append(response.status_code)

    transport = strava(lambda request: httpx.Response(429, headers=headers))
    async with client(transport, on_response=on_response) as strava_client:
        with pytest.raises(StravaRateLimitedError) as raised:
            await strava_client.get_activity_detail(1)

    assert seen == [429]
    assert raised.value.usage == RateLimitUsage(
        {"15m": WindowUsage(used=101, limit=100), "day": WindowUsage(used=640, limit=1000)}
    )


async def test_a_429_without_rate_limit_headers_carries_no_usage():
    transport = strava(lambda request: httpx.Response(429))
    async with client(transport) as strava_client:
        with pytest.raises(StravaRateLimitedError) as raised:
            await strava_client.get_activity_detail(1)

    assert raised.value.usage is None
