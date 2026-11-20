"""download_activity_file and is_activity_file_url: each kind of response, redirects and
the size cap.
"""

import httpx
import pytest

from app.providers.garmin.download import download_activity_file, is_activity_file_url
from app.providers.garmin.errors import (
    GarminFileGoneError,
    GarminFileTooLargeError,
    GarminRateLimitedError,
    GarminUnauthorizedError,
)

pytestmark = pytest.mark.anyio

URL = "https://apis.garmin.com/wellness-api/rest/activityFile?id=901&token=t-1"
FILE = b"\x0e\x20\x00\x00\x00\x00\x00\x00.FIT" + bytes(100)


def transport(response: httpx.Response | Exception, sent: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    return httpx.MockTransport(handler)


async def download(response: httpx.Response | Exception, **kwargs) -> bytes:
    return await download_activity_file(URL, "access-1", transport=transport(response), **kwargs)


def test_garmins_file_endpoint_is_an_activity_file_url():
    assert is_activity_file_url(URL)
    assert is_activity_file_url("https://apis.garmin.com/wellness-api/rest/activityFile")


@pytest.mark.parametrize(
    "url",
    [
        None,
        123,
        "",
        "http://apis.garmin.com/wellness-api/rest/activityFile?id=1",
        "https://apis.garmin.com:443x/wellness-api/rest/activityFile",
        "https://APIS.garmin.com.evil/wellness-api/rest/activityFile",
        "https://apis.garmin.com/wellness-api/rest/activityFile/../activityDetails",
    ],
)
def test_other_urls_arent_activity_file_urls(url):
    assert not is_activity_file_url(url)


async def test_the_file_is_downloaded_with_the_access_token():
    sent = []

    content = await download_activity_file(
        URL, "access-1", transport=transport(httpx.Response(200, content=FILE), sent)
    )

    assert content == FILE
    [request] = sent
    assert (request.method, str(request.url)) == ("GET", URL)
    assert request.headers["Authorization"] == "Bearer access-1"


async def test_the_response_is_passed_to_the_observer():
    seen = []

    async def observe(response, sent_at):
        seen.append(response.status_code)

    await download(httpx.Response(200, content=FILE), on_response=observe)

    assert seen == [200]


@pytest.mark.parametrize("status", [404, 410, 400, 409, 422])
async def test_a_spent_or_missing_link_is_gone(status):
    with pytest.raises(GarminFileGoneError):
        await download(httpx.Response(status))


async def test_an_empty_body_is_gone():
    with pytest.raises(GarminFileGoneError):
        await download(httpx.Response(200, content=b""))


@pytest.mark.parametrize("status", [401, 403, 412])
async def test_a_rejected_token_is_unauthorized(status):
    with pytest.raises(GarminUnauthorizedError):
        await download(httpx.Response(status))


async def test_a_429_carries_retry_after():
    with pytest.raises(GarminRateLimitedError) as raised:
        await download(httpx.Response(429, headers={"Retry-After": "30"}))

    assert raised.value.retry_after == 30


@pytest.mark.parametrize(
    "failure",
    [httpx.Response(500), httpx.Response(503), httpx.ConnectError("down"), httpx.ReadTimeout("t")],
)
async def test_a_server_error_or_network_failure_is_a_plain_http_error(failure):
    with pytest.raises(httpx.HTTPError) as raised:
        await download(failure)

    assert not isinstance(
        raised.value, GarminFileGoneError | GarminUnauthorizedError | GarminRateLimitedError
    )


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500),
        httpx.Response(503),
        httpx.Response(302, headers={"Location": "https://evil.example/file.fit"}),
        httpx.Response(404),
        httpx.Response(403),
        httpx.Response(429),
    ],
)
async def test_an_error_names_the_path_but_not_the_links_query(failure):
    with pytest.raises(httpx.HTTPStatusError) as raised:
        await download(failure)

    assert "/wellness-api/rest/activityFile" in str(raised.value)
    assert "token" not in str(raised.value)
    assert "id=901" not in str(raised.value)


async def test_a_redirect_isnt_followed():
    sent = []
    redirect = httpx.Response(302, headers={"Location": "https://evil.example/file.fit"})

    with pytest.raises(httpx.HTTPStatusError):
        await download_activity_file(URL, "access-1", transport=transport(redirect, sent))

    assert len(sent) == 1


async def test_a_body_over_the_cap_is_too_large():
    with pytest.raises(GarminFileTooLargeError):
        await download(httpx.Response(200, content=bytes(101)), max_bytes=100)


async def test_a_body_at_the_cap_is_kept():
    assert await download(httpx.Response(200, content=bytes(100)), max_bytes=100) == bytes(100)


async def test_a_declared_length_over_the_cap_is_refused_before_reading():
    async def endless():
        yield bytes(10)
        raise AssertionError("the body was read")

    response = httpx.Response(200, headers={"Content-Length": "1000"}, content=endless())

    with pytest.raises(GarminFileTooLargeError):
        await download(response, max_bytes=100)


async def test_a_streamed_body_over_the_cap_is_refused_without_a_length():
    async def chunks():
        for _ in range(20):
            yield bytes(10)

    with pytest.raises(GarminFileTooLargeError):
        await download(httpx.Response(200, content=chunks()), max_bytes=100)
