"""ActivityService: splitting an activity into the user's segments or back into automatic
ones, what that does to its summary, and what a summary reset and a lap edit do to the
user's segments."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.enums import LapType, RunType, SegmentRole
from app.domain.errors import (
    ActivityNotFoundError,
    InvalidSegmentationError,
    TextPolicyRequiredError,
)
from app.domain.models import ActivityRecord, UserSegment
from app.services.activity_service import ActivityService
from app.summaries.editing import TextPolicy
from app.summaries.segmentation import segment_activity
from app.summaries.summary import summarize
from tests.db.builders import make_activity, make_lap
from tests.services.fakes import FakeDatabase

pytestmark = pytest.mark.anyio

EARLIER = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
KEY = "strava_1"
USER_ID = "user-1"

PREAMBLE, WORK, EPILOGUE, BREAK = (
    SegmentRole.PREAMBLE,
    SegmentRole.WORK,
    SegmentRole.EPILOGUE,
    SegmentRole.BREAK,
)

# A warm-up, four 400 m reps with jog recoveries, a rest and a cool-down. Segmented
# automatically: warm-up 1-2, intervals 3-9, break 10, cool-down 11.
LAPS = [
    make_lap(1, duration=330.0, avg_hr=135.0),
    make_lap(2, duration=325.0, avg_hr=137.0),
    make_lap(3, distance=400.0, duration=80.0, avg_hr=172.0),
    make_lap(4, type_id=LapType.RECOVERY, distance=200.0, duration=90.0, avg_hr=140.0),
    make_lap(5, distance=400.0, duration=79.0, avg_hr=174.0),
    make_lap(6, type_id=LapType.RECOVERY, distance=200.0, duration=92.0, avg_hr=142.0),
    make_lap(7, distance=400.0, duration=78.0, avg_hr=176.0),
    make_lap(8, type_id=LapType.RECOVERY, distance=200.0, duration=91.0, avg_hr=141.0),
    make_lap(9, distance=400.0, duration=81.0, avg_hr=175.0),
    make_lap(10, type_id=LapType.REST, distance=10.0, duration=60.0, avg_hr=130.0),
    make_lap(11, duration=335.0, avg_hr=136.0),
]

# The first rep in the warm-up, the rest and cool-down as one cool-down.
LONGER_WARM_UP = (UserSegment(1, PREAMBLE), UserSegment(5, WORK), UserSegment(10, EPILOGUE))
# The automatic segments, the intervals split in two after the second rep.
SPLIT_INTERVALS = (
    UserSegment(1, PREAMBLE),
    UserSegment(3, WORK),
    UserSegment(7, WORK),
    UserSegment(10, BREAK),
    UserSegment(11, EPILOGUE),
)


def stored(user_segments: tuple[UserSegment, ...] | None = None) -> ActivityRecord:
    """The record of ``LAPS`` segmented into ``user_segments``, with its generated summary."""
    record = make_activity(KEY, user_id=USER_ID, laps=LAPS, user_segments=user_segments)
    return replace(record, summary=summarize(record.activity))


def resegmented(record: ActivityRecord, user_segments) -> ActivityRecord:
    """``record`` segmented into ``user_segments``, with the summary generated over them."""
    activity = segment_activity(replace(record.activity, user_segments=user_segments))
    return replace(record, activity=activity, summary=summarize(activity))


def bounds(record: ActivityRecord) -> list[tuple[int, int]]:
    return [
        (segment.start_lap_index, segment.end_lap_index) for segment in record.activity.segments
    ]


def database(*records: ActivityRecord) -> FakeDatabase:
    db = FakeDatabase()
    for record in records:
        db.activities[record.activity.key] = record
    return db


async def call(db: FakeDatabase, method: str, *args, **kwargs):
    """``ActivityService.<method>(*args, **kwargs)`` in a transaction, at ``NOW``."""
    async with db.transaction() as repos:
        service = ActivityService(repos.activities, clock=lambda: NOW)
        return await getattr(service, method)(*args, **kwargs)


# ---------- set_segments ----------


async def test_the_users_segments_are_stored_with_the_summary_written_over_them():
    record = stored()
    db = database(record)

    returned = await call(db, "set_segments", KEY, LONGER_WARM_UP, user_id=USER_ID)

    assert returned == resegmented(record, LONGER_WARM_UP)
    assert db.activities[KEY] == returned
    assert returned.activity.user_segments == LONGER_WARM_UP
    assert bounds(returned) == [(1, 4), (5, 9), (10, 11)]


async def test_none_goes_back_to_automatic_segments():
    record = stored(LONGER_WARM_UP)
    db = database(record)

    returned = await call(db, "set_segments", KEY, None, user_id=USER_ID)

    assert returned == resegmented(record, None)
    assert returned.activity.user_segments is None
    assert bounds(returned) == [(1, 2), (3, 9), (10, 10), (11, 11)]


@pytest.mark.parametrize(
    "user_segments",
    [
        pytest.param([], id="no segments"),
        pytest.param([UserSegment(3, WORK)], id="first lap left out"),
        pytest.param([UserSegment(1, WORK), UserSegment(12, WORK)], id="no such lap"),
        pytest.param([UserSegment(1, WORK), UserSegment(5, BREAK, RunType.EASY)], id="typed break"),
    ],
)
async def test_refused_segments_write_nothing(user_segments):
    record = stored()
    db = database(record)

    with pytest.raises(InvalidSegmentationError):
        await call(db, "set_segments", KEY, user_segments, user_id=USER_ID)

    assert db.activities[KEY] == record


async def test_segments_of_an_activity_that_is_not_found_raise_not_found():
    db = database(stored())

    with pytest.raises(ActivityNotFoundError):
        await call(db, "set_segments", "strava_2", LONGER_WARM_UP, user_id=USER_ID)


async def test_segments_of_another_users_activity_raise_not_found():
    record = stored()
    db = database(record)

    with pytest.raises(ActivityNotFoundError):
        await call(db, "set_segments", KEY, LONGER_WARM_UP, user_id="user-2")
    assert db.activities[KEY] == record


async def test_segments_of_a_summary_with_edited_text_need_a_policy():
    record = stored()
    edited = replace(
        record,
        summary=replace(record.summary, text="mine", text_edited_at=EARLIER),
    )
    db = database(edited)

    with pytest.raises(TextPolicyRequiredError):
        await call(db, "set_segments", KEY, LONGER_WARM_UP, user_id=USER_ID)
    assert db.activities[KEY] == edited


@pytest.mark.parametrize(
    ("policy", "kept"), [(TextPolicy.KEEP, True), (TextPolicy.REGENERATE, False)]
)
async def test_a_text_policy_decides_the_edited_text_over_the_fresh_summary(policy, kept):
    record = stored()
    edited = replace(
        record,
        summary=replace(record.summary, text="mine", text_edited_at=EARLIER),
    )
    db = database(edited)

    returned = await call(
        db, "set_segments", KEY, LONGER_WARM_UP, text_policy=policy, user_id=USER_ID
    )

    fresh = resegmented(record, LONGER_WARM_UP).summary
    expected = replace(fresh, text="mine", text_edited_at=EARLIER) if kept else fresh
    assert returned.summary == expected
    assert db.activities[KEY].summary == returned.summary


# ---------- the user's segments through other edits ----------


async def test_a_summary_reset_keeps_the_users_segments():
    record = stored(LONGER_WARM_UP)
    edited = replace(record.summary, text="mine", text_edited_at=EARLIER)
    db = database(replace(record, summary=edited))

    returned = await call(db, "reset_summary", KEY, user_id=USER_ID)

    assert returned == record
    assert db.activities[KEY].activity.user_segments == LONGER_WARM_UP


async def test_a_lap_edit_keeps_the_users_segments():
    db = database(stored(LONGER_WARM_UP))

    returned = await call(
        db, "edit_laps", KEY, {4: LapType.RUN, 6: LapType.RUN}, {}, user_id=USER_ID
    )

    assert returned.activity.user_segments == LONGER_WARM_UP
    assert bounds(returned) == [(1, 4), (5, 9), (10, 11)]
    assert returned.summary == summarize(returned.activity)
