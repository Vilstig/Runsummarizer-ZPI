"""Contract tests for ``AsyncActivityRepository``.

Assertions target the protocol -- the records a repository returns and the state it
leaves behind -- never the storage layout.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.db.models import ActivityRawPayload
from app.domain.enums import LapType, Provider, RunType, SegmentRole, StreamType
from app.domain.models import ActivityRecord, Summary, UserSegment
from app.summaries.segmentation import relabel_laps, segment_activity
from tests.db.builders import make_activity, make_lap, text_summary
from tests.db.conftest import until_a_query_waits_for_a_lock

pytestmark = pytest.mark.anyio

# a summary whose text the user edited
EDITED_SUMMARY = Summary(
    text="my own words", text_edited_at=datetime(2026, 10, 20, 9, 30, 15, 250000, tzinfo=UTC)
)

SEGMENTED_LAPS = [make_lap(index) for index in range(1, 6)]
USER_SEGMENTS = (
    UserSegment(1, SegmentRole.PREAMBLE),
    UserSegment(3, SegmentRole.WORK, RunType.TEMPO),
    UserSegment(5, SegmentRole.BREAK),
)

# Ordered oldest to newest, all with an explicit offset.
EARLY = "2026-01-05T07:00:00Z"
MIDDLE = "2026-02-05T07:00:00Z"
LATE = "2026-03-05T07:00:00Z"


def _ids(records: list[ActivityRecord]) -> list[str]:
    return [record.activity.key for record in records]


# ---------- save ----------


async def test_save_then_read_back_round_trips(activity_repo, save_activity):
    record = await save_activity("strava_1", summary="10 km easy")

    stored = await activity_repo.get_by_id("strava_1")

    assert stored == record


async def test_save_round_trips_a_start_time_with_its_offset(activity_repo, save_activity):
    record = await save_activity("strava_1", start_time_local="2026-02-05T07:00:00+02:00")

    stored = await activity_repo.get_by_id("strava_1")

    assert stored.activity.start_time_local == datetime.fromisoformat("2026-02-05T07:00:00+02:00")
    assert stored.activity.utc_offset == 7200
    assert stored.activity.start_time_utc == record.activity.start_time_utc


async def test_save_round_trips_the_segments_and_training_type(activity_repo, save_activity):
    laps = [
        make_lap(1, duration=330.0),
        make_lap(2, distance=400.0, duration=80.0),
        make_lap(3, type_id=LapType.RECOVERY, distance=200.0, duration=90.0),
        make_lap(4, distance=400.0, duration=79.0),
        make_lap(5, type_id=LapType.RECOVERY, distance=200.0, duration=92.0),
        make_lap(6, distance=400.0, duration=78.0),
    ]
    record = await save_activity("strava_1", laps=laps)

    stored = await activity_repo.get_by_id("strava_1")

    assert stored.activity.segments == record.activity.segments
    assert stored.activity.training_type == record.activity.training_type
    assert stored.activity.training_type == RunType.SHORT_INTERVALS


async def test_save_round_trips_each_segments_stats(activity_repo, save_activity):
    laps = [
        make_lap(1, duration=330.0, avg_hr=130.0),
        make_lap(2, distance=400.0, duration=80.0, avg_hr=170.0),
        make_lap(3, type_id=LapType.RECOVERY, distance=200.0, duration=90.0),
        make_lap(4, distance=400.0, duration=79.0, avg_hr=170.0),
        make_lap(5, type_id=LapType.RECOVERY, distance=200.0, duration=92.0),
        make_lap(6, distance=400.0, duration=78.0, avg_hr=170.0),
    ]
    record = await save_activity("strava_1", laps=laps)

    stored = await activity_repo.get_by_id("strava_1")

    stats = [segment.stats for segment in stored.activity.segments]
    assert stats == [segment.stats for segment in record.activity.segments]
    assert [(s.distance, s.avg_hr, s.rep_count, s.rep_distance) for s in stats] == [
        (1000, 130, None, None),
        (1200, None, 3, 400),
    ]


async def test_activity_key_is_unique_per_user_not_globally(activity_repo, user_id, other_user_id):
    await activity_repo.save(make_activity("strava_1", user_id=user_id, summary="mine"))
    await activity_repo.save(make_activity("strava_1", user_id=other_user_id, summary="theirs"))

    mine = await activity_repo.get_by_id("strava_1", user_id=user_id)
    theirs = await activity_repo.get_by_id("strava_1", user_id=other_user_id)

    assert mine.summary.text == "mine"
    assert theirs.summary.text == "theirs"
    assert len(await activity_repo.list_activities(user_id=user_id)) == 1
    assert len(await activity_repo.list_activities(user_id=other_user_id)) == 1


async def test_save_rejects_a_lap_without_a_type(activity_repo, user_id):
    record = make_activity("strava_1", user_id=user_id)
    untyped = replace(record.activity.laps[0], type=None)
    record = replace(record, activity=replace(record.activity, laps=[untyped]))

    with pytest.raises(ValueError, match="no type"):
        await activity_repo.save(record)


async def test_the_hr_zone_bounds_round_trip(activity_repo, user_id):
    record = make_activity("strava_1", user_id=user_id)
    record = replace(record, activity=replace(record.activity, zone_bounds=(125, 145, 158, 176)))
    await activity_repo.save(record)

    stored = await activity_repo.get_by_id("strava_1")

    assert stored.activity.zone_bounds == (125, 145, 158, 176)


async def test_save_rejects_an_activity_without_hr_zone_bounds(activity_repo, user_id):
    record = make_activity("strava_1", user_id=user_id)
    record = replace(record, activity=replace(record.activity, zone_bounds=None))

    with pytest.raises(ValueError, match="not counted"):
        await activity_repo.save(record)


async def test_an_edited_summary_round_trips(activity_repo, user_id):
    record = replace(make_activity("strava_1", user_id=user_id), summary=EDITED_SUMMARY)

    await activity_repo.save(record)

    assert (await activity_repo.get_by_id("strava_1")).summary == EDITED_SUMMARY


async def test_the_users_segments_round_trip(activity_repo, save_activity):
    record = await save_activity("strava_1", laps=SEGMENTED_LAPS, user_segments=USER_SEGMENTS)

    stored = await activity_repo.get_by_id("strava_1")

    assert stored == record
    assert stored.activity.user_segments == USER_SEGMENTS


async def test_an_activity_segmented_automatically_has_no_user_segments(
    activity_repo, save_activity
):
    await save_activity("strava_1", laps=SEGMENTED_LAPS)

    assert (await activity_repo.get_by_id("strava_1")).activity.user_segments is None


async def test_the_recording_device_round_trips(activity_repo, user_id):
    record = make_activity("garmin_1", user_id=user_id, source="garmin")
    record.activity.device_name = "Forerunner 965"

    await activity_repo.save(record)

    stored = await activity_repo.get_by_id("garmin_1")
    assert stored.activity.device_name == "Forerunner 965"
    assert stored == record


async def test_an_activity_without_a_known_device_has_none(activity_repo, save_activity):
    await save_activity("strava_1")

    assert (await activity_repo.get_by_id("strava_1")).activity.device_name is None


async def test_save_inserts_an_activity_that_is_not_stored(activity_repo, user_id):
    record = make_activity("strava_1", user_id=user_id, summary="10 km easy")

    saved = await activity_repo.save(
        record, raw_payload={"id": "strava_1"}, payload_kind="strava_detail"
    )

    assert saved is True

    [stored] = await activity_repo.list_activities(user_id=user_id, include_laps=True)
    assert stored == record
    assert await activity_repo.get_raw_payload("strava_1") == {"id": "strava_1"}


async def test_save_leaves_a_stored_activity_untouched(activity_repo, save_activity, user_id):
    await save_activity(
        "strava_1",
        summary="edited",
        laps=[make_lap(1, type_id=LapType.RECOVERY)],
        raw_payload={"id": "strava_1", "name": "before"},
    )
    stored = await activity_repo.list_activities(user_id=user_id, include_laps=True)
    fetched_again = make_activity(
        "strava_1", user_id=user_id, summary="from Strava", laps=[make_lap(1), make_lap(2)]
    )

    saved = await activity_repo.save(
        fetched_again, raw_payload={"id": "strava_1", "name": "after"}, payload_kind="strava_detail"
    )

    assert saved is False
    assert await activity_repo.list_activities(user_id=user_id, include_laps=True) == stored
    assert await activity_repo.get_raw_payload("strava_1") == {"id": "strava_1", "name": "before"}


async def test_save_stores_the_raw_payload_under_its_kind(activity_repo, db_session, user_id):
    record = make_activity("strava_1", user_id=user_id)

    await activity_repo.save(record, raw_payload={"id": "strava_1"}, payload_kind="test_kind")

    kinds = (await db_session.execute(select(ActivityRawPayload.payload_kind))).scalars().all()
    assert kinds == ["test_kind"]
    assert await activity_repo.get_raw_payload("strava_1") == {"id": "strava_1"}


async def test_a_raw_payload_without_a_kind_is_refused(activity_repo, user_id):
    record = make_activity("strava_1", user_id=user_id)

    with pytest.raises(ValueError, match="payload_kind"):
        await activity_repo.save(record, raw_payload={"id": "strava_1"})


async def test_a_refused_raw_payload_writes_nothing(activity_repo, user_id):
    record = make_activity("strava_1", user_id=user_id)

    with pytest.raises(ValueError):
        await activity_repo.save(record, raw_payload={"id": "strava_1"})

    assert await activity_repo.get_by_id("strava_1") is None


async def test_save_inserts_a_key_another_user_has_stored(activity_repo, user_id, other_user_id):
    await activity_repo.save(make_activity("strava_1", user_id=other_user_id, summary="theirs"))

    mine = make_activity("strava_1", user_id=user_id, summary="mine")
    assert await activity_repo.save(mine) is True

    assert (await activity_repo.get_by_id("strava_1", user_id=user_id)).summary.text == "mine"
    theirs = await activity_repo.get_by_id("strava_1", user_id=other_user_id)
    assert theirs.summary.text == "theirs"


# ---------- get_by_id ----------


async def test_get_by_id_returns_none_when_missing(activity_repo):
    assert await activity_repo.get_by_id("strava_missing") is None


async def test_get_by_id_is_scoped_to_the_user(activity_repo, save_activity, other_user_id):
    await save_activity("strava_1")

    assert await activity_repo.get_by_id("strava_1", user_id=other_user_id) is None


# ---------- get_and_lock_by_id ----------


async def test_get_and_lock_by_id_reads_what_get_by_id_reads(activity_repo, save_activity):
    await save_activity("strava_1", laps=SEGMENTED_LAPS, user_segments=USER_SEGMENTS)

    assert await activity_repo.get_and_lock_by_id("strava_1") == await activity_repo.get_by_id(
        "strava_1"
    )


async def test_get_and_lock_by_id_returns_none_when_missing(activity_repo):
    assert await activity_repo.get_and_lock_by_id("strava_missing") is None


async def test_get_and_lock_by_id_is_scoped_to_the_user(
    activity_repo, save_activity, other_user_id
):
    await save_activity("strava_1")

    assert await activity_repo.get_and_lock_by_id("strava_1", user_id=other_user_id) is None


@pytest.fixture
async def committed_activity(committed_transaction, committed_user_id) -> ActivityRecord:
    """An activity of ``committed_user_id``, committed to the test database."""
    record = make_activity("strava_1", user_id=committed_user_id)
    async with committed_transaction() as repos:
        await repos.activities.save(record)
    return record


async def test_get_and_lock_by_id_waits_for_the_transaction_holding_the_lock(
    committed_engine, committed_transaction, committed_user_id, committed_activity
):
    async def lock_in_another_transaction() -> ActivityRecord | None:
        async with committed_transaction() as repos:
            return await repos.activities.get_and_lock_by_id("strava_1", user_id=committed_user_id)

    async with committed_transaction() as first:
        await first.activities.get_and_lock_by_id("strava_1", user_id=committed_user_id)
        second = asyncio.create_task(lock_in_another_transaction())
        await until_a_query_waits_for_a_lock(committed_engine)
        assert not second.done()
        await first.activities.update_summary(
            "strava_1", text_summary("written first"), user_id=committed_user_id
        )

    assert (await asyncio.wait_for(second, timeout=5)).summary.text == "written first"


async def test_a_plain_read_does_not_wait_for_the_activity_lock(
    committed_transaction, committed_user_id, committed_activity
):
    async def read_in_another_transaction() -> ActivityRecord | None:
        async with committed_transaction() as repos:
            return await repos.activities.get_by_id("strava_1", user_id=committed_user_id)

    async with committed_transaction() as first:
        await first.activities.get_and_lock_by_id("strava_1", user_id=committed_user_id)
        read = await asyncio.wait_for(read_in_another_transaction(), timeout=5)

    assert read == committed_activity


# ---------- get_raw_payload ----------


async def test_get_raw_payload_returns_the_saved_payload(activity_repo, save_activity):
    await save_activity("strava_1", raw_payload={"id": "strava_1", "type": "Run"})

    assert await activity_repo.get_raw_payload("strava_1") == {"id": "strava_1", "type": "Run"}


async def test_get_raw_payload_returns_none_when_missing(activity_repo):
    assert await activity_repo.get_raw_payload("strava_missing") is None


async def test_get_raw_payload_returns_none_for_an_activity_saved_without_one(
    activity_repo, user_id
):
    await activity_repo.save(make_activity("strava_1", user_id=user_id))

    assert await activity_repo.get_raw_payload("strava_1") is None


async def test_get_raw_payload_is_scoped_to_the_user(activity_repo, save_activity, other_user_id):
    await save_activity("strava_1")

    assert await activity_repo.get_raw_payload("strava_1", user_id=other_user_id) is None


# ---------- is_stored ----------


async def test_is_stored_finds_the_users_activity(activity_repo, save_activity, user_id):
    await save_activity("strava_1")

    assert await activity_repo.is_stored(user_id, "strava_1") is True


async def test_is_stored_is_false_for_an_activity_that_is_not_stored(
    activity_repo, save_activity, user_id
):
    await save_activity("strava_1")

    assert await activity_repo.is_stored(user_id, "strava_2") is False


async def test_is_stored_is_scoped_to_the_user(activity_repo, save_activity, other_user_id):
    await save_activity("strava_1")

    assert await activity_repo.is_stored(other_user_id, "strava_1") is False


async def test_is_stored_is_false_for_a_user_id_that_is_not_a_uuid(activity_repo, save_activity):
    await save_activity("strava_1")

    assert await activity_repo.is_stored("not-a-uuid", "strava_1") is False


# ---------- list_activities ----------


async def test_list_activities_is_newest_first(activity_repo, save_activity, user_id):
    await save_activity("strava_middle", start_time_local=MIDDLE)
    await save_activity("strava_early", start_time_local=EARLY)
    await save_activity("strava_late", start_time_local=LATE)

    listed = await activity_repo.list_activities(user_id=user_id)

    assert _ids(listed) == ["strava_late", "strava_middle", "strava_early"]


async def test_list_activities_filters_by_user(
    activity_repo, save_activity, user_id, other_user_id
):
    await save_activity("strava_mine")
    await activity_repo.save(make_activity("strava_theirs", user_id=other_user_id))

    assert _ids(await activity_repo.list_activities(user_id=user_id)) == ["strava_mine"]
    assert _ids(await activity_repo.list_activities(user_id=other_user_id)) == ["strava_theirs"]


async def test_list_activities_without_a_user_filter_returns_every_user(
    activity_repo, save_activity, user_id, other_user_id
):
    await save_activity("strava_mine")
    await activity_repo.save(make_activity("strava_theirs", user_id=other_user_id))

    listed = await activity_repo.list_activities()

    assert sorted(_ids(listed)) == ["strava_mine", "strava_theirs"]


async def test_list_activities_filters_by_source(activity_repo, save_activity, user_id):
    await save_activity("strava_1")
    await save_activity("garmin_1", source="garmin")

    strava = await activity_repo.list_activities(user_id=user_id, source="strava")
    garmin = await activity_repo.list_activities(user_id=user_id, source="garmin")

    assert _ids(strava) == ["strava_1"]
    assert _ids(garmin) == ["garmin_1"]
    assert garmin[0].activity.source == Provider.GARMIN


async def test_list_activities_honours_limit_and_skip(activity_repo, save_activity, user_id):
    await save_activity("strava_early", start_time_local=EARLY)
    await save_activity("strava_middle", start_time_local=MIDDLE)
    await save_activity("strava_late", start_time_local=LATE)

    first_page = await activity_repo.list_activities(user_id=user_id, limit=2)
    second_page = await activity_repo.list_activities(user_id=user_id, limit=2, skip=1)
    past_the_end = await activity_repo.list_activities(user_id=user_id, limit=2, skip=3)

    assert _ids(first_page) == ["strava_late", "strava_middle"]
    assert _ids(second_page) == ["strava_middle", "strava_early"]
    assert past_the_end == []


async def test_list_activities_filters_by_after_inclusive(activity_repo, save_activity, user_id):
    await save_activity("strava_early", start_time_local=EARLY)
    await save_activity("strava_middle", start_time_local="2026-02-05T00:00:00Z")
    await save_activity("strava_late", start_time_local=LATE)

    listed = await activity_repo.list_activities(user_id=user_id, after=date(2026, 2, 5))

    assert _ids(listed) == ["strava_late", "strava_middle"]


async def test_list_activities_filters_by_before_exclusive(activity_repo, save_activity, user_id):
    await save_activity("strava_early", start_time_local=EARLY)
    await save_activity("strava_middle", start_time_local="2026-02-05T00:00:00Z")
    await save_activity("strava_late", start_time_local=LATE)

    listed = await activity_repo.list_activities(user_id=user_id, before=date(2026, 2, 5))

    assert _ids(listed) == ["strava_early"]


async def test_list_activities_filters_by_a_date_window(activity_repo, save_activity, user_id):
    await save_activity("strava_jan", start_time_local="2026-01-31T23:30:00Z")
    await save_activity("strava_feb_first", start_time_local="2026-02-01T00:10:00Z")
    await save_activity("strava_feb_last", start_time_local="2026-02-28T23:30:00Z")
    await save_activity("strava_mar", start_time_local="2026-03-01T00:10:00Z")

    listed = await activity_repo.list_activities(
        user_id=user_id, after=date(2026, 2, 1), before=date(2026, 3, 1)
    )

    assert _ids(listed) == ["strava_feb_last", "strava_feb_first"]


async def test_list_activities_filters_by_the_local_date(activity_repo, save_activity, user_id):
    # 23:30 local on Feb 5 is already Feb 6 in UTC.
    await save_activity("strava_late_evening", start_time_local="2026-02-05T23:30:00-02:00")

    listed = await activity_repo.list_activities(
        user_id=user_id, after=date(2026, 2, 5), before=date(2026, 2, 6)
    )

    assert _ids(listed) == ["strava_late_evening"]


async def test_list_activities_returns_one_day_for_consecutive_bounds(
    activity_repo, save_activity, user_id
):
    await save_activity("strava_before", start_time_local="2026-02-04T23:59:00Z")
    await save_activity("strava_morning", start_time_local="2026-02-05T07:00:00Z")
    await save_activity("strava_evening", start_time_local="2026-02-05T21:00:00Z")
    await save_activity("strava_after", start_time_local="2026-02-06T00:00:00Z")

    listed = await activity_repo.list_activities(
        user_id=user_id, after=date(2026, 2, 5), before=date(2026, 2, 6)
    )

    assert _ids(listed) == ["strava_evening", "strava_morning"]


async def test_list_activities_excludes_laps_by_default(activity_repo, save_activity, user_id):
    await save_activity("strava_1", laps=[make_lap(1), make_lap(2)])

    [listed] = await activity_repo.list_activities(user_id=user_id)

    assert listed.activity.laps == []


async def test_list_activities_includes_laps_on_request(activity_repo, save_activity, user_id):
    record = await save_activity("strava_1", laps=[make_lap(1), make_lap(2), make_lap(3)])

    [listed] = await activity_repo.list_activities(user_id=user_id, include_laps=True)

    assert listed.activity.laps == record.activity.laps


async def test_list_activities_attaches_each_activitys_own_laps(
    activity_repo, save_activity, user_id
):
    await save_activity("strava_early", start_time_local=EARLY, laps=[make_lap(1)])
    await save_activity("strava_late", start_time_local=LATE, laps=[make_lap(1), make_lap(2)])

    listed = await activity_repo.list_activities(user_id=user_id, include_laps=True)

    lap_counts = {record.activity.key: len(record.activity.laps) for record in listed}
    assert lap_counts == {"strava_early": 1, "strava_late": 2}


async def test_list_activities_attaches_each_activitys_own_segments(
    activity_repo, save_activity, user_id
):
    early = await save_activity("strava_early", start_time_local=EARLY)
    late = await save_activity(
        "strava_late", start_time_local=LATE, laps=SEGMENTED_LAPS, user_segments=USER_SEGMENTS
    )

    listed = await activity_repo.list_activities(user_id=user_id)

    assert {record.activity.key: record.activity.segments for record in listed} == {
        "strava_early": early.activity.segments,
        "strava_late": late.activity.segments,
    }


async def test_list_activities_pages_activities_starting_together_without_repeats(
    activity_repo, save_activity, user_id
):
    for number in range(5):
        await save_activity(f"strava_{number}", start_time_local=MIDDLE)

    pages = [
        await activity_repo.list_activities(user_id=user_id, limit=2, skip=skip)
        for skip in (0, 2, 4)
    ]

    keys = [record.activity.key for page in pages for record in page]
    assert sorted(keys) == [f"strava_{number}" for number in range(5)]


# ---------- get_laps ----------


async def test_get_laps_returns_the_stored_laps(activity_repo, save_activity):
    record = await save_activity("strava_1", laps=[make_lap(1), make_lap(2), make_lap(3)])

    laps = await activity_repo.get_laps("strava_1")

    assert laps == record.activity.laps


async def test_get_laps_returns_none_when_the_activity_is_missing(activity_repo):
    assert await activity_repo.get_laps("strava_missing") is None


async def test_get_laps_returns_an_empty_list_when_there_are_no_laps(activity_repo, save_activity):
    await save_activity("strava_1", laps=[])

    assert await activity_repo.get_laps("strava_1") == []


async def test_get_laps_is_scoped_to_the_user(activity_repo, save_activity, other_user_id):
    await save_activity("strava_1")

    assert await activity_repo.get_laps("strava_1", user_id=other_user_id) is None


# ---------- streams ----------

STREAMS = {
    StreamType.TIME: [0, 1, 2],
    StreamType.DISTANCE: [0.0, 3.04, 6.07],
    StreamType.HEARTRATE: [140, 141, 143],
    StreamType.VELOCITY: [3.041, 3.036, 3.0],
    StreamType.ALTITUDE: [101.24, 101.3, 101.36],
}


async def test_save_stores_the_streams_at_their_precision(activity_repo, user_id):
    await activity_repo.save(make_activity("strava_1", user_id=user_id), streams=STREAMS)

    assert await activity_repo.get_streams("strava_1", user_id=user_id) == {
        "time": [0, 1, 2],
        "distance": [0.0, 3.0, 6.1],
        "heartrate": [140, 141, 143],
        "velocity": [3.04, 3.04, 3.0],
        "altitude": [101.2, 101.3, 101.4],
    }


async def test_time_and_heart_rate_come_back_as_whole_numbers(activity_repo, save_activity):
    await save_activity("strava_1", streams=STREAMS)

    streams = await activity_repo.get_streams("strava_1")

    assert all(type(sample) is int for sample in streams["time"] + streams["heartrate"])


async def test_a_stream_the_activity_lacks_is_left_out(activity_repo, save_activity):
    await save_activity(
        "strava_1", streams={StreamType.TIME: [0, 1], StreamType.DISTANCE: [0.0, 3.0]}
    )

    assert await activity_repo.get_streams("strava_1") == {"time": [0, 1], "distance": [0.0, 3.0]}


async def test_an_activity_saved_without_streams_has_none(activity_repo, save_activity):
    await save_activity("strava_1")

    assert await activity_repo.get_streams("strava_1") == {}


async def test_get_streams_returns_only_the_selected_streams(activity_repo, save_activity):
    await save_activity("strava_1", streams=STREAMS)

    streams = await activity_repo.get_streams(
        "strava_1", stream_types=[StreamType.HEARTRATE, StreamType.TIME]
    )

    assert streams == {"heartrate": [140, 141, 143], "time": [0, 1, 2]}


async def test_a_selected_stream_the_activity_lacks_is_left_out(activity_repo, save_activity):
    await save_activity("strava_1", streams={StreamType.TIME: [0, 1]})

    streams = await activity_repo.get_streams(
        "strava_1", stream_types=[StreamType.TIME, StreamType.ALTITUDE]
    )

    assert streams == {"time": [0, 1]}


async def test_selecting_no_streams_gives_an_empty_result(activity_repo, save_activity):
    await save_activity("strava_1", streams=STREAMS)

    assert await activity_repo.get_streams("strava_1", stream_types=[]) == {}


async def test_get_streams_returns_none_when_the_activity_is_missing(activity_repo):
    assert await activity_repo.get_streams("strava_missing") is None


async def test_get_streams_is_scoped_to_the_user(activity_repo, save_activity, other_user_id):
    await save_activity("strava_1", streams=STREAMS)

    assert await activity_repo.get_streams("strava_1", user_id=other_user_id) is None


async def test_save_leaves_the_streams_of_a_stored_activity_untouched(
    activity_repo, save_activity, user_id
):
    await save_activity("strava_1", streams={StreamType.TIME: [0, 1]})

    fetched_again = make_activity("strava_1", user_id=user_id)
    assert await activity_repo.save(fetched_again, streams={StreamType.TIME: [0, 1, 2]}) is False

    assert await activity_repo.get_streams("strava_1") == {"time": [0, 1]}


# ---------- update_activity ----------


async def test_update_activity_moves_the_activity_and_summary_together(
    activity_repo, save_activity
):
    record = await save_activity("strava_1", summary="before")
    renamed = replace(record.activity, name="Renamed")

    returned = await activity_repo.update_activity(
        "strava_1", renamed, summary=text_summary("after")
    )
    stored = await activity_repo.get_by_id("strava_1")

    assert returned == ActivityRecord(
        user_id=record.user_id, activity=renamed, summary=text_summary("after")
    )
    assert stored == returned


async def test_update_activity_keeps_the_recording_device(activity_repo, user_id):
    record = make_activity("garmin_1", user_id=user_id, source="garmin")
    record.activity.device_name = "Forerunner 965"
    await activity_repo.save(record)
    without_device = replace(record.activity, name="Renamed", device_name=None)

    await activity_repo.update_activity("garmin_1", without_device, summary=text_summary("x"))

    assert (await activity_repo.get_by_id("garmin_1")).activity.device_name == "Forerunner 965"


async def test_update_activity_returns_none_when_the_activity_is_missing(
    activity_repo, save_activity
):
    record = await save_activity("strava_1")

    returned = await activity_repo.update_activity(
        "strava_missing", record.activity, summary=text_summary("after")
    )

    assert returned is None


async def test_update_activity_writes_nothing_for_another_user(
    activity_repo, save_activity, other_user_id
):
    """The failure path leaves both the activity and the summary as they were."""
    record = await save_activity("strava_1", summary="before")

    returned = await activity_repo.update_activity(
        "strava_1",
        replace(record.activity, name="Renamed"),
        summary=text_summary("after"),
        user_id=other_user_id,
    )
    stored = await activity_repo.get_by_id("strava_1")

    assert returned is None
    assert stored == record


async def test_update_activity_writes_lap_types_and_no_other_lap_values(
    activity_repo, save_activity
):
    record = await save_activity("strava_1", laps=[make_lap(1), make_lap(2), make_lap(3)])
    retyped = [make_lap(1), make_lap(2, type_id=LapType.REST, distance=9999.0)]

    await activity_repo.update_activity(
        "strava_1", replace(record.activity, laps=retyped), summary=text_summary("after")
    )

    assert await activity_repo.get_laps("strava_1") == [
        make_lap(1),
        make_lap(2, type_id=LapType.REST),
        make_lap(3),
    ]


async def test_update_activity_stores_new_segments_and_training_type(activity_repo, save_activity):
    record = await save_activity("strava_1", laps=[make_lap(1), make_lap(2), make_lap(3)])
    relabelled = relabel_laps(record.activity, {2: LapType.REST})

    await activity_repo.update_activity("strava_1", relabelled, summary=text_summary("after"))
    stored = await activity_repo.get_by_id("strava_1")

    assert stored.activity.segments == relabelled.segments
    assert stored.activity.segments != record.activity.segments
    assert stored.activity.training_type == relabelled.training_type


async def test_update_activity_stores_and_clears_the_users_segments(activity_repo, save_activity):
    record = await save_activity("strava_1", laps=SEGMENTED_LAPS)
    user_segmented = segment_activity(replace(record.activity, user_segments=USER_SEGMENTS))
    automatic = segment_activity(replace(user_segmented, user_segments=None))

    await activity_repo.update_activity("strava_1", user_segmented, summary=text_summary("user"))
    after_user = await activity_repo.get_by_id("strava_1")
    await activity_repo.update_activity("strava_1", automatic, summary=text_summary("auto"))
    after_automatic = await activity_repo.get_by_id("strava_1")

    assert after_user.activity == user_segmented
    assert after_automatic.activity == automatic
    assert after_automatic.activity.user_segments is None


async def test_update_activity_keeps_the_raw_payload(activity_repo, save_activity):
    record = await save_activity("strava_1", raw_payload={"id": "strava_1"})

    await activity_repo.update_activity(
        "strava_1", replace(record.activity, name="Renamed"), summary=text_summary("after")
    )

    assert await activity_repo.get_raw_payload("strava_1") == {"id": "strava_1"}


async def test_update_activity_stores_an_edited_summary(activity_repo, save_activity):
    record = await save_activity("strava_1")

    await activity_repo.update_activity("strava_1", record.activity, summary=EDITED_SUMMARY)

    assert (await activity_repo.get_by_id("strava_1")).summary == EDITED_SUMMARY


# ---------- update_summary ----------


async def test_update_summary_replaces_the_summary(activity_repo, save_activity):
    record = await save_activity("strava_1", summary="before")

    returned = await activity_repo.update_summary("strava_1", EDITED_SUMMARY)
    stored = await activity_repo.get_by_id("strava_1")

    assert returned == replace(record, summary=EDITED_SUMMARY)
    assert stored == returned


async def test_update_summary_clears_the_edit_time(activity_repo, user_id):
    await activity_repo.save(
        replace(make_activity("strava_1", user_id=user_id), summary=EDITED_SUMMARY)
    )

    await activity_repo.update_summary("strava_1", text_summary("regenerated"))

    assert (await activity_repo.get_by_id("strava_1")).summary == text_summary("regenerated")


async def test_update_summary_leaves_the_activity_laps_payload_and_streams(
    activity_repo, save_activity
):
    record = await save_activity(
        "strava_1",
        laps=[make_lap(1), make_lap(2, type_id=LapType.REST), make_lap(3)],
        user_segments=[UserSegment(1, SegmentRole.WORK), UserSegment(2, SegmentRole.BREAK)],
        raw_payload={"id": "strava_1"},
        streams={StreamType.TIME: [0, 1], StreamType.HEARTRATE: [140, 141]},
    )
    streams = await activity_repo.get_streams("strava_1")

    await activity_repo.update_summary("strava_1", EDITED_SUMMARY)
    stored = await activity_repo.get_by_id("strava_1")

    assert stored.activity == record.activity
    assert await activity_repo.get_laps("strava_1") == record.activity.laps
    assert await activity_repo.get_raw_payload("strava_1") == {"id": "strava_1"}
    assert await activity_repo.get_streams("strava_1") == streams


async def test_update_summary_returns_none_when_the_activity_is_missing(activity_repo):
    assert await activity_repo.update_summary("strava_missing", EDITED_SUMMARY) is None


async def test_update_summary_writes_nothing_for_another_user(
    activity_repo, save_activity, other_user_id
):
    record = await save_activity("strava_1", summary="before")

    returned = await activity_repo.update_summary("strava_1", EDITED_SUMMARY, user_id=other_user_id)

    assert returned is None
    assert await activity_repo.get_by_id("strava_1") == record


# ---------- delete ----------


async def test_delete_removes_the_activity(activity_repo, save_activity):
    await save_activity("strava_1")

    assert await activity_repo.delete("strava_1") is True
    assert await activity_repo.get_by_id("strava_1") is None


async def test_delete_returns_false_when_the_activity_is_missing(activity_repo):
    assert await activity_repo.delete("strava_missing") is False


async def test_delete_is_scoped_to_the_user(activity_repo, save_activity, other_user_id):
    await save_activity("strava_1")

    assert await activity_repo.delete("strava_1", user_id=other_user_id) is False
    assert await activity_repo.get_by_id("strava_1") is not None
