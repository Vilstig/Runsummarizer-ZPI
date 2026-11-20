from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from app.domain.models import ProviderCredentials
from app.providers.intervals.client import USER_AGENT, IntervalsClient
from app.providers.intervals.errors import (
    IntervalsError,
    IntervalsNotFoundError,
    IntervalsRateLimitedError,
    IntervalsUnauthorizedError,
)

pytestmark = pytest.mark.anyio

CREDENTIALS = ProviderCredentials("access-1", None, None)

API_CALLS = {
    "list": lambda c: c.list_activities(oldest="2000-01-01"),
    "activity": lambda c: c.get_activity("i7"),
    "file": lambda c: c.get_activity_file("i7"),
    "fit-file": lambda c: c.get_activity_fit_file("i7"),
}


def intervals(api: Callable[[httpx.Request], httpx.Response], sent: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(request)
        return api(request)

    return httpx.MockTransport(handler)


def client(transport: httpx.MockTransport, **kwargs) -> IntervalsClient:
    return IntervalsClient(CREDENTIALS, transport=transport, **kwargs)


async def test_the_access_token_and_a_custom_user_agent_are_sent():
    sent = []

    transport = intervals(lambda request: httpx.Response(200, json={"id": "i7"}), sent)
    async with client(transport) as c:
        await c.get_activity("i7")

    [request] = sent
    assert request.url.path == "/api/v1/activity/i7"
    assert request.headers["Authorization"] == "Bearer access-1"
    assert request.headers["User-Agent"] == USER_AGENT


async def test_list_activities_sends_oldest_newest_limit_and_fields():
    requested = []

    def api(request: httpx.Request) -> httpx.Response:
        requested.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    async with client(intervals(api)) as c:
        await c.list_activities(
            oldest="2026-09-01T00:00:00",
            newest="2026-10-01T00:00:00",
            limit=200,
            fields="id,type,start_date,source",
        )

    [params] = requested
    assert params == {
        "oldest": "2026-09-01T00:00:00",
        "newest": "2026-10-01T00:00:00",
        "limit": "200",
        "fields": "id,type,start_date,source",
    }


async def test_list_activities_without_newest_or_limit_leaves_them_out():
    requested = []

    def api(request: httpx.Request) -> httpx.Response:
        requested.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    async with client(intervals(api)) as c:
        await c.list_activities(oldest="2000-01-01", fields="id")

    assert "newest" not in requested[0]
    assert "limit" not in requested[0]


async def test_get_activity_returns_the_json_body():
    async with client(intervals(lambda r: httpx.Response(200, json={"id": "i7"}))) as c:
        assert await c.get_activity("i7") == {"id": "i7"}


async def test_get_activity_file_returns_the_raw_bytes():
    async with client(intervals(lambda r: httpx.Response(200, content=b"\x1f\x8bgzipped"))) as c:
        assert await c.get_activity_file("i7") == b"\x1f\x8bgzipped"


async def test_get_activity_fit_file_hits_the_fit_file_endpoint():
    requested = []

    def api(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, content=b"FIT")

    async with client(intervals(api)) as c:
        await c.get_activity_fit_file("i7")

    assert requested == ["/api/v1/activity/i7/fit-file"]


# ---------- typed errors ----------


@pytest.mark.parametrize("call", API_CALLS.values(), ids=list(API_CALLS))
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, IntervalsUnauthorizedError),
        (403, IntervalsUnauthorizedError),
        (404, IntervalsNotFoundError),
        (429, IntervalsRateLimitedError),
    ],
)
async def test_api_errors_raise_typed_exceptions(call, status, error):
    async with client(intervals(lambda r: httpx.Response(status))) as c:
        with pytest.raises(error) as raised:
            await call(c)

    assert isinstance(raised.value, httpx.HTTPStatusError)
    assert raised.value.response.status_code == status


@pytest.mark.parametrize("call", API_CALLS.values(), ids=list(API_CALLS))
async def test_a_server_error_raises_a_plain_http_status_error(call):
    async with client(intervals(lambda r: httpx.Response(503))) as c:
        with pytest.raises(httpx.HTTPStatusError) as raised:
            await call(c)

    assert not isinstance(raised.value, IntervalsError)


# ---------- responses ----------


async def test_every_api_response_is_passed_on_with_the_time_its_request_was_sent():
    seen = []
    times = iter(
        [datetime(2026, 10, 6, 10, 14, 59, tzinfo=UTC), datetime(2026, 10, 6, 10, 15, tzinfo=UTC)]
    )

    async def on_response(response: httpx.Response, sent_at: datetime) -> None:
        seen.append((response.request.url.path, response.status_code, sent_at))

    transport = intervals(lambda r: httpx.Response(200, json={"id": "i7"}))
    async with client(transport, on_response=on_response, clock=lambda: next(times)) as c:
        await c.get_activity("i7")
        await c.get_activity_file("i7")

    assert seen == [
        ("/api/v1/activity/i7", 200, datetime(2026, 10, 6, 10, 14, 59, tzinfo=UTC)),
        ("/api/v1/activity/i7/file", 200, datetime(2026, 10, 6, 10, 15, tzinfo=UTC)),
    ]


async def test_a_429_is_passed_on_before_it_raises():
    seen = []

    async def on_response(response: httpx.Response, sent_at: datetime) -> None:
        seen.append(response.status_code)

    transport = intervals(lambda r: httpx.Response(429, headers={"Retry-After": "30"}))
    async with client(transport, on_response=on_response) as c:
        with pytest.raises(IntervalsRateLimitedError) as raised:
            await c.get_activity("i7")

    assert seen == [429]
    assert raised.value.response.headers["Retry-After"] == "30"
