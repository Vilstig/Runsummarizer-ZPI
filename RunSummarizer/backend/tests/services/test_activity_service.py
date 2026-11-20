"""ActivityService: the lap flag and date window of list_activities reach the
repository, a search reaches it whole, get_activity_streams reads the user's streams
from it, and weekly_summary works out the Monday-based week range it asks the
repository for."""

from datetime import UTC, date, datetime

import pytest

from app.domain.enums import ActivitySortKey, StreamType
from app.domain.errors import ActivityNotFoundError
from app.domain.models import ActivityFilter, ActivityOrder, ActivityPage, NumberRange
from app.services.activity_service import ActivityService

pytestmark = pytest.mark.anyio


class RecordingRepository:
    def __init__(self):
        self.calls: list[dict] = []  # arguments of each call, by name
        self.streams: dict | None = {"time": [0, 1]}  # what get_streams returns

    async def list_activities(self, **kwargs) -> list[dict]:
        self.calls.append(kwargs)
        return []

    async def search_activities(self, activity_filter: ActivityFilter, **kwargs) -> ActivityPage:
        self.calls.append({"activity_filter": activity_filter, **kwargs})
        return ActivityPage(records=[], total=0)

    async def get_streams(self, activity_id: str, **kwargs) -> dict | None:
        self.calls.append({"activity_id": activity_id, **kwargs})
        return self.streams

    async def weekly_totals(self, user_id: str, **kwargs) -> list:
        self.calls.append({"user_id": user_id, **kwargs})
        return []


async def test_laps_are_left_out_unless_requested():
    repo = RecordingRepository()

    await ActivityService(repo).list_activities(user_id="user-1")

    assert repo.calls[0]["include_laps"] is False


async def test_the_date_window_is_open_unless_given():
    repo = RecordingRepository()

    await ActivityService(repo).list_activities(user_id="user-1")

    assert repo.calls[0]["after"] is None
    assert repo.calls[0]["before"] is None


async def test_the_date_window_is_passed_to_the_repository():
    repo = RecordingRepository()

    await ActivityService(repo).list_activities(
        after=date(2026, 10, 1), before=date(2026, 11, 1), user_id="user-1"
    )

    assert repo.calls[0]["after"] == date(2026, 10, 1)
    assert repo.calls[0]["before"] == date(2026, 11, 1)


async def test_the_lap_flag_is_passed_to_the_repository():
    repo = RecordingRepository()

    await ActivityService(repo).list_activities(include_laps=True, user_id="user-1")

    assert repo.calls[0]["include_laps"] is True


async def test_a_search_reaches_the_repository_with_its_order_and_page():
    repo = RecordingRepository()
    activity_filter = ActivityFilter(user_id="user-1", distance=NumberRange(min=10000))
    order = ActivityOrder(ActivitySortKey.PACE, descending=False)

    page = await ActivityService(repo).search_activities(
        activity_filter, order=order, limit=20, offset=40
    )

    assert page == ActivityPage(records=[], total=0)
    assert repo.calls == [
        {
            "activity_filter": activity_filter,
            "order": order,
            "limit": 20,
            "offset": 40,
        }
    ]


async def test_the_requested_streams_are_read_for_the_user():
    repo = RecordingRepository()
    requested = (StreamType.HEARTRATE, StreamType.TIME)

    streams = await ActivityService(repo).get_activity_streams(
        "strava_7", user_id="user-1", stream_types=requested
    )

    assert streams == {"heartrate": None, "time": [0, 1]}
    assert repo.calls == [
        {"activity_id": "strava_7", "user_id": "user-1", "stream_types": requested}
    ]


async def test_every_stream_is_requested_by_default():
    repo = RecordingRepository()

    streams = await ActivityService(repo).get_activity_streams("strava_7", user_id="user-1")

    assert streams == {
        "time": [0, 1],
        "distance": None,
        "heartrate": None,
        "velocity": None,
        "altitude": None,
    }


async def test_streams_of_an_activity_that_is_not_found_are_none():
    repo = RecordingRepository()
    repo.streams = None

    with pytest.raises(ActivityNotFoundError):
        await ActivityService(repo).get_activity_streams("strava_7", user_id="user-1")


async def test_weekly_summary_starts_the_range_at_the_monday_before_as_of():
    repo = RecordingRepository()

    # 2026-11-19 is a Thursday; its Monday is 2026-11-16; 4 weeks back is 2026-10-26
    await ActivityService(repo).weekly_summary(weeks=4, as_of=date(2026, 11, 19), user_id="user-1")

    assert repo.calls[0] == {
        "user_id": "user-1",
        "first_week_start": date(2026, 10, 26),
        "weeks": 4,
    }


async def test_weekly_summary_treats_a_monday_as_of_as_its_own_week_start():
    repo = RecordingRepository()

    await ActivityService(repo).weekly_summary(weeks=1, as_of=date(2026, 11, 16), user_id="user-1")

    assert repo.calls[0]["first_week_start"] == date(2026, 11, 16)


async def test_weekly_summary_defaults_as_of_to_the_clocks_today():
    repo = RecordingRepository()

    def clock() -> datetime:
        return datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

    await ActivityService(repo, clock).weekly_summary(weeks=1, user_id="user-1")

    assert repo.calls[0]["first_week_start"] == date(2026, 11, 16)
