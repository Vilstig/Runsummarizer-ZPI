"""GarminClient: the activity list, an activity's JSON and its original file."""

from datetime import date

import httpx
import pytest

from app.providers.garmin.errors import GarminInvalidResponseError, GarminUnsupportedFileError
from app.providers.garmin.personal_api.client import GarminClient
from app.providers.garmin.personal_api.constants import ACTIVITY_SEARCH_PATH
from app.providers.garmin.personal_api.errors import GarminNotFoundError
from tests.providers.fit.fit_builder import build_zip

pytestmark = pytest.mark.anyio

ACTIVITIES = [{"activityId": n} for n in range(1, 6)]


def client(handler, sent: list | None = None) -> GarminClient:
    def record(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(request)
        return handler(request)

    return GarminClient(httpx.Auth(), transport=httpx.MockTransport(record))


def search(request: httpx.Request) -> httpx.Response:
    start = int(request.url.params["start"])
    limit = int(request.url.params["limit"])
    return httpx.Response(200, json=ACTIVITIES[start : start + limit])


async def test_list_activities_pages_until_a_short_page():
    sent = []
    async with client(search, sent) as garmin:
        activities = await garmin.list_activities(date(2026, 5, 1), date(2026, 5, 14), page_size=2)

    assert activities == ACTIVITIES
    assert [request.url.params["start"] for request in sent] == ["0", "2", "4"]
    assert sent[0].url.path == ACTIVITY_SEARCH_PATH
    assert dict(sent[0].url.params) == {
        "limit": "2",
        "startDate": "2026-05-01",
        "endDate": "2026-05-14",
        "activityType": "running",
        "start": "0",
    }


async def test_list_activities_stops_at_the_limit():
    sent = []
    async with client(search, sent) as garmin:
        activities = await garmin.list_activities(limit=3)

    assert activities == ACTIVITIES[:3]
    assert len(sent) == 1


async def test_list_activities_of_every_type_sends_no_type():
    sent = []
    async with client(search, sent) as garmin:
        await garmin.list_activities(activity_type=None)

    assert "activityType" not in sent[0].url.params


async def test_an_empty_list_response_is_no_activities():
    async with client(lambda request: httpx.Response(200)) as garmin:
        assert await garmin.list_activities() == []


async def test_get_activity_returns_the_json_as_sent():
    detail = {"activityId": 7, "activityName": "Morning Run"}
    sent = []
    async with client(lambda request: httpx.Response(200, json=detail), sent) as garmin:
        assert await garmin.get_activity(7) == detail
    assert sent[0].url.path == "/activity-service/activity/7"


async def test_download_activity_file_returns_the_bytes():
    sent = []
    async with client(lambda request: httpx.Response(200, content=b"zip"), sent) as garmin:
        assert await garmin.download_activity_file(7) == b"zip"
    assert sent[0].url.path == "/download-service/files/activity/7"
    assert "application/zip" in sent[0].headers["Accept"]


async def test_an_empty_download_raises():
    async with client(lambda request: httpx.Response(200)) as garmin:
        with pytest.raises(GarminInvalidResponseError):
            await garmin.download_activity_file(7)


async def test_download_fit_takes_the_fit_file_out_of_the_download():
    content = build_zip({"7_ACTIVITY.fit": b"fit"})
    async with client(lambda request: httpx.Response(200, content=content)) as garmin:
        assert await garmin.download_fit(7) == b"fit"


async def test_download_fit_of_a_gpx_upload_is_unsupported():
    content = build_zip({"7.gpx": b"<gpx/>"})
    async with client(lambda request: httpx.Response(200, content=content)) as garmin:
        with pytest.raises(GarminUnsupportedFileError):
            await garmin.download_fit(7)


async def test_a_missing_activity_raises_not_found():
    async with client(lambda request: httpx.Response(404)) as garmin:
        with pytest.raises(GarminNotFoundError):
            await garmin.get_activity(7)
