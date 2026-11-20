"""The JSON the user's segments are stored as in ``activities.user_segments``, pinned."""

import pytest
from sqlalchemy import select

from app.db.models import Activity
from app.domain.enums import RunType, SegmentRole
from app.domain.models import UserSegment
from tests.db.builders import make_lap

pytestmark = pytest.mark.anyio

USER_SEGMENTS = [
    UserSegment(1, SegmentRole.PREAMBLE),
    UserSegment(3, SegmentRole.WORK, RunType.SHORT_INTERVALS),
    UserSegment(5, SegmentRole.BREAK),
    UserSegment(6, SegmentRole.EPILOGUE, RunType.EASY),
]


@pytest.fixture
def stored_user_segments(db_session):
    """The ``user_segments`` column of an activity, and whether it is SQL NULL."""

    async def read(activity_key: str) -> tuple[object, bool]:
        row = (
            await db_session.execute(
                select(Activity.user_segments, Activity.user_segments.is_(None)).where(
                    Activity.activity_key == activity_key
                )
            )
        ).one()
        return row[0], row[1]

    return read


async def test_the_users_segments_are_stored_as_json(save_activity, stored_user_segments):
    await save_activity(
        "strava_1", laps=[make_lap(index) for index in range(1, 7)], user_segments=USER_SEGMENTS
    )

    assert await stored_user_segments("strava_1") == (
        [
            {"startLapIndex": 1, "role": "preamble", "runTypeId": None},
            {"startLapIndex": 3, "role": "work", "runTypeId": 1},
            {"startLapIndex": 5, "role": "break", "runTypeId": None},
            {"startLapIndex": 6, "role": "epilogue", "runTypeId": 0},
        ],
        False,
    )


async def test_automatic_segmentation_is_stored_as_null(save_activity, stored_user_segments):
    await save_activity("strava_1")

    assert await stored_user_segments("strava_1") == (None, True)
