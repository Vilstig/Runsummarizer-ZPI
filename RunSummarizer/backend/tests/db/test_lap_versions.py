"""Contract tests for the versions of an activity's laps: as imported, and as the user edited
their distance."""

from dataclasses import replace

import pytest
from sqlalchemy import func, select

from app.db import models
from app.domain.enums import LapType
from app.domain.models import Lap
from tests.db.builders import make_lap, text_summary

pytestmark = pytest.mark.anyio

LAPS = [make_lap(1), make_lap(2), make_lap(3)]


def edited(lap: Lap, distance: float) -> Lap:
    """The version of ``lap`` the user edited to ``distance``."""
    return replace(lap, distance=distance, speed=distance / lap.duration, version=1)


@pytest.fixture
async def record(save_activity):
    return await save_activity("strava_1", laps=LAPS)


# ---------- reads ----------


async def test_a_read_gives_the_edited_version_of_a_lap(activity_repo, record):
    returned = await activity_repo.set_lap_distances("strava_1", {2: 1100.0})
    stored = await activity_repo.get_by_id("strava_1")

    assert stored.activity.laps == [LAPS[0], edited(LAPS[1], 1100.0), LAPS[2]]
    assert returned == stored


async def test_get_laps_and_list_activities_give_the_newest_versions(activity_repo, record):
    await activity_repo.set_lap_distances("strava_1", {3: 900.0})

    newest = [LAPS[0], LAPS[1], edited(LAPS[2], 900.0)]
    assert await activity_repo.get_laps("strava_1") == newest
    [listed] = await activity_repo.list_activities(include_laps=True)
    assert listed.activity.laps == newest
    assert (await activity_repo.get_and_lock_by_id("strava_1")).activity.laps == newest


# ---------- set_lap_distances ----------


async def test_a_distance_edit_keeps_the_activity_totals(activity_repo, record):
    returned = await activity_repo.set_lap_distances("strava_1", {1: 1500.0, 2: 1200.0})

    assert returned.activity.distance == record.activity.distance
    assert returned.activity.speed == record.activity.speed


async def test_a_second_distance_edit_updates_the_edited_version(activity_repo, record):
    await activity_repo.set_lap_distances("strava_1", {2: 1100.0})
    await activity_repo.set_lap_distances("strava_1", {2: 1050.0})

    assert (await activity_repo.get_laps("strava_1"))[1] == edited(LAPS[1], 1050.0)


async def test_the_imported_distance_sent_again_is_still_an_edit(activity_repo, record):
    await activity_repo.set_lap_distances("strava_1", {2: LAPS[1].distance})

    assert (await activity_repo.get_laps("strava_1"))[1] == edited(LAPS[1], LAPS[1].distance)


async def test_a_lap_of_no_duration_has_no_edited_speed(activity_repo, save_activity):
    await save_activity("strava_1", laps=[make_lap(1, duration=0.0)])

    await activity_repo.set_lap_distances("strava_1", {1: 800.0})

    [lap] = await activity_repo.get_laps("strava_1")
    assert (lap.distance, lap.speed, lap.version) == (800.0, None, 1)


async def test_a_distance_for_an_unknown_lap_is_refused_and_writes_nothing(activity_repo, record):
    with pytest.raises(ValueError, match="no lap 9"):
        await activity_repo.set_lap_distances("strava_1", {2: 1100.0, 9: 1000.0})

    assert await activity_repo.get_laps("strava_1") == LAPS


# ---------- reset_lap_distances ----------


async def test_a_reset_of_some_laps_deletes_their_edited_versions(activity_repo, record):
    await activity_repo.set_lap_distances("strava_1", {1: 1100.0, 2: 1200.0})

    returned = await activity_repo.reset_lap_distances("strava_1", [1])

    assert returned.activity.laps == [LAPS[0], edited(LAPS[1], 1200.0), LAPS[2]]
    assert await activity_repo.get_laps("strava_1") == returned.activity.laps


async def test_a_reset_of_every_lap_deletes_every_edited_version(activity_repo, record):
    await activity_repo.set_lap_distances("strava_1", {1: 1100.0, 3: 1200.0})

    returned = await activity_repo.reset_lap_distances("strava_1")

    assert returned.activity.laps == LAPS
    assert await activity_repo.get_laps("strava_1") == LAPS


async def test_a_reset_of_an_unknown_lap_is_refused_and_writes_nothing(activity_repo, record):
    await activity_repo.set_lap_distances("strava_1", {1: 1100.0})

    with pytest.raises(ValueError, match="no lap 9"):
        await activity_repo.reset_lap_distances("strava_1", [1, 9])

    assert (await activity_repo.get_laps("strava_1"))[0] == edited(LAPS[0], 1100.0)


# ---------- other writes ----------


async def test_a_type_change_applies_to_both_versions(activity_repo, record):
    await activity_repo.set_lap_distances("strava_1", {2: 1100.0})
    retyped = [replace(lap, type=LapType.REST) if lap.index == 2 else lap for lap in LAPS]

    await activity_repo.update_activity(
        "strava_1", replace(record.activity, laps=retyped), summary=text_summary("after")
    )
    edited_lap = (await activity_repo.get_laps("strava_1"))[1]
    await activity_repo.reset_lap_distances("strava_1")
    imported_lap = (await activity_repo.get_laps("strava_1"))[1]

    assert edited_lap == replace(edited(LAPS[1], 1100.0), type=LapType.REST)
    assert imported_lap == replace(LAPS[1], type=LapType.REST)


async def test_deleting_an_activity_deletes_both_versions(activity_repo, db_session, record):
    activity_id = (
        await db_session.execute(
            select(models.Activity.id).where(models.Activity.activity_key == "strava_1")
        )
    ).scalar_one()
    await activity_repo.set_lap_distances("strava_1", {2: 1100.0})

    await activity_repo.delete("strava_1")

    remaining = await db_session.execute(
        select(func.count()).select_from(models.Lap).where(models.Lap.activity_id == activity_id)
    )
    assert remaining.scalar_one() == 0


# ---------- missing and other users' activities ----------


async def test_another_users_activity_is_neither_changed_nor_returned(
    activity_repo, record, other_user_id
):
    await activity_repo.set_lap_distances("strava_1", {1: 1100.0})

    assert (
        await activity_repo.set_lap_distances("strava_1", {2: 1200.0}, user_id=other_user_id)
        is None
    )
    assert await activity_repo.reset_lap_distances("strava_1", user_id=other_user_id) is None
    assert await activity_repo.get_laps("strava_1") == [edited(LAPS[0], 1100.0), *LAPS[1:]]


async def test_a_missing_activity_is_none(activity_repo, record):
    assert await activity_repo.set_lap_distances("strava_2", {1: 1100.0}) is None
    assert await activity_repo.reset_lap_distances("strava_2") is None
