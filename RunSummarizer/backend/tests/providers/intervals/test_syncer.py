from datetime import UTC, datetime

import httpx
import pytest

from app.domain.errors import ProviderAuthorizationError, ProviderUnavailableError, RateLimitedError
from app.domain.models import ProviderCredentials
from app.providers.base import Listed, ListedActivity, SyncWindow
from app.providers.intervals import syncer as syncer_module
from app.providers.intervals.activity_keys import intervals_activity_key
from app.providers.intervals.syncer import IntervalsSyncer
from tests.providers.intervals.fakes import FakeIntervals, intervals_activity, strava_stub

pytestmark = pytest.mark.anyio

CREDENTIALS = ProviderCredentials("access-1", None, None)
LISTING = "/api/v1/athlete/0/activities"


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
def intervals() -> FakeIntervals:
    return FakeIntervals()


async def ignore_response(response: httpx.Response, sent_at: datetime) -> None:
    pass


async def start(
    intervals: FakeIntervals,
    *,
    window: SyncWindow | None = None,
    limit: int | None = None,
    clock=lambda: utc(2026, 9, 1),
) -> Listed:
    return await IntervalsSyncer(transport=intervals.transport, clock=clock).start(
        CREDENTIALS, window, limit, ignore_response
    )


def listing_requests(intervals: FakeIntervals) -> list[httpx.Request]:
    return [r for r in intervals.requests if r.url.path == LISTING]


# ---------- authentication ----------


async def test_intervals_is_called_with_the_access_token(intervals):
    intervals.add(intervals_activity("i1"))

    await start(intervals)

    [request] = listing_requests(intervals)
    assert request.headers["Authorization"] == "Bearer access-1"


# ---------- filtering ----------


async def test_a_run_is_listed_with_its_key_and_utc_start_time(intervals):
    intervals.add(
        intervals_activity(
            "i1", start_date="2026-09-05T06:00:00Z", start_date_local="2026-09-05T08:00:00"
        )
    )

    listed = await start(intervals, window=SyncWindow(utc(2026, 9, 1), utc(2026, 10, 1)))

    assert listed == Listed([ListedActivity(intervals_activity_key("i1"), utc(2026, 9, 5, 6))])


async def test_non_run_activity_types_are_left_out(intervals):
    intervals.add(
        intervals_activity(
            "i1",
            activity_type="Ride",
            start_date="2026-09-05T06:00:00Z",
            start_date_local="2026-09-05T08:00:00",
        )
    )

    listed = await start(intervals, window=SyncWindow(utc(2026, 9, 1), utc(2026, 10, 1)))

    assert listed == Listed([])


async def test_strava_stubs_without_a_type_are_left_out(intervals):
    intervals.add(strava_stub("i9", start_date_local="2026-09-05T08:00:00"))

    listed = await start(intervals, window=SyncWindow(utc(2026, 9, 1), utc(2026, 10, 1)))

    assert listed == Listed([])


# ---------- windowed sync ----------


async def test_the_window_query_is_widened_by_14_hours_each_side_as_naive_local_values(intervals):
    intervals.add(intervals_activity("i1"))

    await start(intervals, window=SyncWindow(utc(2026, 9, 1), utc(2026, 10, 1)))

    [request] = listing_requests(intervals)
    assert request.url.params["oldest"] == "2026-08-31T10:00:00"
    assert request.url.params["newest"] == "2026-10-01T14:00:00"


async def test_the_result_is_filtered_to_the_precise_utc_window(intervals):
    intervals.add(
        intervals_activity(
            "before", start_date="2026-08-31T23:00:00Z", start_date_local="2026-09-01T01:00:00"
        )
    )
    intervals.add(
        intervals_activity(
            "inside", start_date="2026-09-05T06:00:00Z", start_date_local="2026-09-05T08:00:00"
        )
    )
    intervals.add(
        intervals_activity(
            "at-the-end", start_date="2026-10-01T00:00:00Z", start_date_local="2026-10-01T02:00:00"
        )
    )

    listed = await start(intervals, window=SyncWindow(utc(2026, 9, 1), utc(2026, 10, 1)))

    assert [a.activity_key for a in listed.activities] == [intervals_activity_key("inside")]


# ---------- unwindowed sync ----------


async def test_without_a_window_the_newest_runs_up_to_the_limit_are_listed(intervals):
    intervals.add(
        intervals_activity(
            "i1", start_date="2026-05-01T06:00:00Z", start_date_local="2026-05-01T08:00:00"
        )
    )
    intervals.add(
        intervals_activity(
            "i2", start_date="2026-05-02T06:00:00Z", start_date_local="2026-05-02T08:00:00"
        )
    )
    intervals.add(
        intervals_activity(
            "i3", start_date="2026-05-03T06:00:00Z", start_date_local="2026-05-03T08:00:00"
        )
    )

    listed = await start(intervals, limit=2)

    assert [a.activity_key for a in listed.activities] == [
        intervals_activity_key("i3"),
        intervals_activity_key("i2"),
    ]


async def test_pagination_walks_newest_backward_across_short_pages(intervals, monkeypatch):
    monkeypatch.setattr(syncer_module, "PAGE_SIZE", 1)
    intervals.add(
        intervals_activity(
            "i1", start_date="2026-05-01T06:00:00Z", start_date_local="2026-05-01T08:00:00"
        )
    )
    intervals.add(
        intervals_activity(
            "i2", start_date="2026-05-02T06:00:00Z", start_date_local="2026-05-02T08:00:00"
        )
    )
    intervals.add(
        intervals_activity(
            "i3", start_date="2026-05-03T06:00:00Z", start_date_local="2026-05-03T08:00:00"
        )
    )

    listed = await start(intervals, limit=2)

    assert [a.activity_key for a in listed.activities] == [
        intervals_activity_key("i3"),
        intervals_activity_key("i2"),
    ]
    requests = listing_requests(intervals)
    assert len(requests) == 2
    assert "newest" not in requests[0].url.params
    assert requests[1].url.params["newest"] == "2026-05-03T07:59:59"


async def test_a_short_page_stops_the_pagination_even_under_the_limit(intervals):
    intervals.add(intervals_activity("i1"))
    intervals.add(intervals_activity("i2", start_date_local="2026-05-02T08:00:00"))

    listed = await start(intervals, limit=10)

    assert len(listed.activities) == 2
    assert len(listing_requests(intervals)) == 1


# ---------- errors ----------


async def test_a_429_raises_rate_limited_until_retry_after(intervals):
    intervals.fail(LISTING, 429)
    intervals.retry_after = 30

    with pytest.raises(RateLimitedError) as raised:
        await start(intervals, window=SyncWindow(utc(2026, 9, 1), utc(2026, 10, 1)))

    assert raised.value.until == utc(2026, 9, 1, 0, 0, 30)


@pytest.mark.parametrize("status", [401, 403])
async def test_401_or_403_raises_an_authorization_error(intervals, status):
    intervals.fail(LISTING, status)

    with pytest.raises(ProviderAuthorizationError):
        await start(intervals, window=SyncWindow(utc(2026, 9, 1), utc(2026, 10, 1)))


@pytest.mark.parametrize(
    "outcome", [500, httpx.ConnectTimeout("timed out")], ids=["server-error", "timeout"]
)
async def test_other_failures_are_unavailable(intervals, outcome):
    intervals.fail(LISTING, outcome)

    with pytest.raises(ProviderUnavailableError):
        await start(intervals, window=SyncWindow(utc(2026, 9, 1), utc(2026, 10, 1)))
