"""ActivityService: editing the types and distances of an activity's laps, resetting their
distances, and what both do to its segments and summary."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.enums import LapType
from app.domain.errors import ActivityNotFoundError, TextPolicyRequiredError, UnknownLapError
from app.domain.models import Activity, ActivityRecord
from app.services.activity_service import ActivityService
from app.summaries.editing import TextPolicy
from app.summaries.segmentation import relabel_laps
from app.summaries.summary import summarize
from tests.services.fakes import FakeDatabase, edited_lap, stored_run

pytestmark = pytest.mark.anyio

EARLIER = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
KEY = "strava_1"
USER_ID = "user-1"
REST_LAP = {2: LapType.REST}


def generated(record: ActivityRecord) -> ActivityRecord:
    """``record`` with the summary its activity is written into."""
    return replace(record, summary=summarize(record.activity))


def text_edited(record: ActivityRecord) -> ActivityRecord:
    """``generated(record)`` with its text edited by the user."""
    record = generated(record)
    return replace(
        record, summary=replace(record.summary, text="my own words", text_edited_at=EARLIER)
    )


def with_distances(
    activity: Activity, distances: dict[int, float], lap_types: dict | None = None
) -> Activity:
    """``activity`` with the user's lap ``distances`` and ``lap_types``, segmented again."""
    laps = [
        edited_lap(lap, distances[lap.index]) if lap.index in distances else lap
        for lap in activity.laps
    ]
    return relabel_laps(replace(activity, laps=laps), lap_types or {})


def database(*records: ActivityRecord) -> FakeDatabase:
    db = FakeDatabase()
    for record in records:
        db.activities[record.activity.key] = record
    return db


async def call(db: FakeDatabase, method: str, *args, **kwargs):
    """``ActivityService.<method>(*args, **kwargs)`` in a transaction."""
    async with db.transaction() as repos:
        return await getattr(ActivityService(repos.activities), method)(*args, **kwargs)


async def edited_distances(db: FakeDatabase) -> FakeDatabase:
    """``db`` once laps 1 and 2 of its activity were edited to 1100 m and 1200 m."""
    await call(db, "edit_laps", KEY, {}, {1: 1100.0, 2: 1200.0}, user_id=USER_ID)
    return db


# ---------- edit_laps ----------


async def test_a_distance_edit_writes_the_summary_from_the_edited_lap():
    record = generated(stored_run(1))
    db = database(record)

    returned = await call(db, "edit_laps", KEY, {}, {2: 1500.0}, user_id=USER_ID)

    activity = with_distances(record.activity, {2: 1500.0})
    assert returned == ActivityRecord(USER_ID, activity, summarize(activity))
    assert returned.activity.laps[1].version == 1
    assert returned.summary != record.summary


async def test_types_and_distances_change_in_one_edit():
    record = generated(stored_run(1))
    db = database(record)

    returned = await call(db, "edit_laps", KEY, REST_LAP, {3: 800.0}, user_id=USER_ID)

    activity = with_distances(record.activity, {3: 800.0}, REST_LAP)
    assert returned == ActivityRecord(USER_ID, activity, summarize(activity))
    async with db.transaction() as repos:
        assert await repos.activities.get_by_id(KEY) == returned


async def test_a_type_edit_alone_writes_no_distance():
    record = generated(stored_run(1))
    db = database(record)

    returned = await call(db, "edit_laps", KEY, REST_LAP, {}, user_id=USER_ID)

    assert [lap.version for lap in returned.activity.laps] == [0, 0, 0]
    assert db.lap_distances == {}


async def test_an_edit_of_edited_text_without_a_policy_writes_nothing():
    record = text_edited(stored_run(1))
    db = database(record)

    with pytest.raises(TextPolicyRequiredError):
        await call(db, "edit_laps", KEY, REST_LAP, {2: 1500.0}, user_id=USER_ID)

    assert db.activities[KEY] == record
    assert db.lap_distances == {}


async def test_keep_leaves_the_edited_text():
    record = text_edited(stored_run(1))
    db = database(record)

    returned = await call(
        db, "edit_laps", KEY, {}, {2: 1500.0}, text_policy=TextPolicy.KEEP, user_id=USER_ID
    )

    assert returned.activity == with_distances(record.activity, {2: 1500.0})
    assert returned.summary == record.summary


async def test_keep_leaves_the_edited_text_while_the_segment_stats_follow_the_laps():
    record = text_edited(stored_run(1))
    db = database(record)

    returned = await call(
        db, "edit_laps", KEY, {}, {2: 1500.0}, text_policy=TextPolicy.KEEP, user_id=USER_ID
    )

    assert [segment.stats.distance for segment in record.activity.segments] == [3000]
    assert [segment.stats.distance for segment in returned.activity.segments] == [3500]
    assert returned.summary == record.summary


async def test_regenerate_writes_the_edited_text_again():
    record = text_edited(stored_run(1))
    db = database(record)

    returned = await call(
        db, "edit_laps", KEY, REST_LAP, {}, text_policy=TextPolicy.REGENERATE, user_id=USER_ID
    )

    assert returned.summary == summarize(relabel_laps(record.activity, REST_LAP))
    assert returned.summary.text_edited_at is None


@pytest.mark.parametrize(
    ("lap_types", "distances"),
    [
        pytest.param({9: LapType.REST}, {2: 1500.0}, id="type"),
        pytest.param({}, {9: 1500.0}, id="distance"),
    ],
)
async def test_an_edit_of_an_unknown_lap_writes_nothing(lap_types, distances):
    record = generated(stored_run(1))
    db = database(record)

    with pytest.raises(UnknownLapError, match="Unknown lapIndex: 9"):
        await call(db, "edit_laps", KEY, lap_types, distances, user_id=USER_ID)

    assert db.activities[KEY] == record
    assert db.lap_distances == {}


async def test_an_unknown_lap_is_refused_before_the_text_policy():
    db = database(text_edited(stored_run(1)))

    with pytest.raises(UnknownLapError):
        await call(db, "edit_laps", KEY, {}, {9: 1500.0}, user_id=USER_ID)


async def test_laps_of_a_missing_or_another_users_activity_raise_not_found():
    record = generated(stored_run(1))
    db = database(record)

    with pytest.raises(ActivityNotFoundError):
        await call(db, "edit_laps", "strava_2", {}, {2: 1.0}, user_id=USER_ID)
    with pytest.raises(ActivityNotFoundError):
        await call(db, "edit_laps", KEY, {}, {2: 1.0}, user_id="user-2")
    with pytest.raises(ActivityNotFoundError):
        await call(db, "reset_laps", KEY, user_id="user-2")
    assert db.lap_distances == {}


# ---------- reset_laps ----------


async def test_a_reset_of_some_laps_keeps_the_others_edited():
    record = generated(stored_run(1))
    db = await edited_distances(database(record))

    returned = await call(db, "reset_laps", KEY, [1], user_id=USER_ID)

    activity = with_distances(record.activity, {2: 1200.0})
    assert returned == ActivityRecord(USER_ID, activity, summarize(activity))


async def test_a_reset_of_every_lap_brings_back_the_imported_laps_and_summary():
    record = generated(stored_run(1))
    db = await edited_distances(database(record))

    returned = await call(db, "reset_laps", KEY, user_id=USER_ID)

    assert returned == record


async def test_a_reset_of_edited_text_without_a_policy_writes_nothing():
    record = text_edited(stored_run(1))
    db = database(record)
    await call(db, "edit_laps", KEY, {}, {2: 1500.0}, text_policy=TextPolicy.KEEP, user_id=USER_ID)

    with pytest.raises(TextPolicyRequiredError):
        await call(db, "reset_laps", KEY, user_id=USER_ID)

    assert db.lap_distances == {KEY: {2: 1500.0}}


async def test_a_reset_with_keep_leaves_the_edited_text():
    record = text_edited(stored_run(1))
    db = database(record)
    await call(db, "edit_laps", KEY, {}, {2: 1500.0}, text_policy=TextPolicy.KEEP, user_id=USER_ID)

    returned = await call(db, "reset_laps", KEY, text_policy=TextPolicy.KEEP, user_id=USER_ID)

    assert returned == record


async def test_a_reset_of_an_unknown_lap_writes_nothing():
    db = await edited_distances(database(generated(stored_run(1))))

    with pytest.raises(UnknownLapError, match="Unknown lapIndex: 9"):
        await call(db, "reset_laps", KEY, [1, 9], user_id=USER_ID)

    assert db.lap_distances == {KEY: {1: 1100.0, 2: 1200.0}}
