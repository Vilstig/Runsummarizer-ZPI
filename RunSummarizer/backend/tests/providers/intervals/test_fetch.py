import base64

import pytest

from app.domain.models import ProviderCredentials
from app.providers.intervals.client import IntervalsClient
from app.providers.intervals.fetch import fetch_intervals_payload
from tests.providers.intervals.fakes import FakeIntervals, intervals_activity, strava_stub

pytestmark = pytest.mark.anyio

CREDENTIALS = ProviderCredentials("access-1", None, None)


async def fetch(intervals: FakeIntervals, activity_id: str = "i1") -> dict | None:
    async with IntervalsClient(CREDENTIALS, transport=intervals.transport) as client:
        return await fetch_intervals_payload(client, activity_id)


async def test_a_fit_original_is_downloaded_as_is():
    intervals = FakeIntervals()
    intervals.add(intervals_activity("i1", file_type="fit"), file=b"FIT-BYTES")

    payload = await fetch(intervals)

    assert payload["file_source"] == "original"
    assert base64.b64decode(payload["file"]) == b"FIT-BYTES"
    assert payload["activity"]["id"] == "i1"


@pytest.mark.parametrize("file_type", ["gpx", "tcx"])
async def test_a_non_fit_original_falls_back_to_the_generated_fit_file(file_type):
    intervals = FakeIntervals()
    intervals.add(
        intervals_activity("i1", file_type=file_type),
        file=b"SHOULD-NOT-BE-USED",
        fit_file=b"GENERATED-FIT",
    )

    payload = await fetch(intervals)

    assert payload["file_source"] == "generated"
    assert base64.b64decode(payload["file"]) == b"GENERATED-FIT"


async def test_strava_stubs_give_no_payload():
    intervals = FakeIntervals()
    intervals.add(strava_stub("i1"))

    assert await fetch(intervals) is None


async def test_non_run_activities_give_no_payload():
    intervals = FakeIntervals()
    intervals.add(intervals_activity("i1", activity_type="Ride", file_type="fit"), file=b"x")

    assert await fetch(intervals) is None


async def test_an_activity_without_an_original_falls_back_to_the_generated_fit_file():
    intervals = FakeIntervals()
    intervals.add(intervals_activity("i1", file_type=None), fit_file=b"GENERATED-FIT")

    payload = await fetch(intervals)

    assert payload["file_source"] == "generated"
    assert base64.b64decode(payload["file"]) == b"GENERATED-FIT"
    assert [r.url.path for r in intervals.requests] == [
        "/api/v1/activity/i1",
        "/api/v1/activity/i1/fit-file",
    ]


async def test_an_activity_without_an_original_or_generated_file_gives_no_payload():
    intervals = FakeIntervals()
    intervals.add(intervals_activity("i1", file_type=None))  # 404 on /fit-file

    assert await fetch(intervals) is None


async def test_a_file_that_has_since_disappeared_gives_no_payload():
    intervals = FakeIntervals()
    intervals.add(intervals_activity("i1", file_type="fit"))  # no file added -> 404 on download

    assert await fetch(intervals) is None
