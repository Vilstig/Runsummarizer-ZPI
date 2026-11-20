"""``resegment_activities`` over the Postgres repository, inside the test's rolled-back
transaction."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.enums import LapType, RunType, SegmentRole
from app.domain.models import ActivityRecord, SegmentStats, Summary, ZoneTimes
from app.summaries.segmentation import segment_activity
from app.summaries.summary import summarize
from scripts.resegment_activities import resegment_activities
from tests.db.builders import make_activity, make_lap

pytestmark = pytest.mark.anyio

EDITED_SUMMARY = Summary(
    text="my own words", text_edited_at=datetime(2026, 10, 20, 9, 30, tzinfo=UTC)
)
STEADY_LAPS = [make_lap(index) for index in range(1, 4)]


def stored_before_stats(record: ActivityRecord, run_type: RunType | None = None) -> ActivityRecord:
    """``record`` as stored before segments had stats: its segments without them and, given
    ``run_type``, its work segments and training type of ``run_type``."""
    segments = [
        replace(
            segment,
            stats=SegmentStats(),
            run_type=(
                run_type
                if run_type is not None and segment.role == SegmentRole.WORK
                else segment.run_type
            ),
        )
        for segment in record.activity.segments
    ]
    training_type = run_type if run_type is not None else record.activity.training_type
    return replace(
        record,
        activity=replace(record.activity, segments=segments, training_type=training_type),
    )


async def test_stored_segments_get_their_stats_and_the_current_run_type(
    activity_repo, rolled_back_transaction, user_id, capsys
):
    record = make_activity("strava_race", user_id=user_id, laps=STEADY_LAPS, summary="old text")
    hard = replace(record.activity, zone_times=ZoneTimes(zone4=100.0, zone5=600.0))
    await activity_repo.save(stored_before_stats(replace(record, activity=hard), RunType.TEMPO))

    count = await resegment_activities(user_id=user_id, transaction=rolled_back_transaction)

    stored = await activity_repo.get_by_id("strava_race")
    expected = segment_activity(hard)
    assert count == 1
    assert stored.activity.training_type == RunType.RACE
    assert stored.activity.segments == expected.segments
    assert stored.activity.segments[0].stats.pace is not None
    assert stored.summary == summarize(expected)
    assert "strava_race: Tempo -> Race" in capsys.readouterr().out


async def test_the_stored_lap_types_and_edited_text_are_kept(
    activity_repo, rolled_back_transaction, user_id
):
    laps = [
        make_lap(1),
        make_lap(2, type_id=LapType.REST, distance=10.0, duration=60.0),
        make_lap(3),
        make_lap(4),
    ]
    record = replace(make_activity("strava_1", user_id=user_id, laps=laps), summary=EDITED_SUMMARY)
    await activity_repo.save(stored_before_stats(record))
    laps_before = await activity_repo.get_laps("strava_1")

    await resegment_activities(user_id=user_id, transaction=rolled_back_transaction)

    stored = await activity_repo.get_by_id("strava_1")
    assert await activity_repo.get_laps("strava_1") == laps_before
    assert stored.summary == EDITED_SUMMARY
    assert stored.activity.segments == record.activity.segments


async def test_only_the_users_activities_with_laps_are_resegmented(
    activity_repo, rolled_back_transaction, user_id, other_user_id
):
    no_laps = make_activity("strava_no_laps", user_id=user_id, laps=[], summary="")
    no_laps = replace(no_laps, activity=replace(no_laps.activity, training_type=None))
    theirs = stored_before_stats(
        make_activity("strava_theirs", user_id=other_user_id, laps=STEADY_LAPS), RunType.TEMPO
    )
    await activity_repo.save(no_laps)
    await activity_repo.save(theirs)
    await activity_repo.save(make_activity("strava_mine", user_id=user_id))

    count = await resegment_activities(user_id=user_id, transaction=rolled_back_transaction)

    assert count == 1
    assert await activity_repo.get_by_id("strava_no_laps") == no_laps
    assert await activity_repo.get_by_id("strava_theirs", user_id=other_user_id) == theirs


async def test_a_dry_run_writes_nothing(activity_repo, rolled_back_transaction, user_id):
    record = stored_before_stats(
        make_activity("strava_1", user_id=user_id, laps=STEADY_LAPS), RunType.TEMPO
    )
    await activity_repo.save(record)

    count = await resegment_activities(
        user_id=user_id, dry_run=True, transaction=rolled_back_transaction
    )

    assert count == 1
    assert await activity_repo.get_by_id("strava_1") == record
