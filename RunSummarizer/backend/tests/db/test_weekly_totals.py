"""Contract tests for ``AsyncActivityRepository.weekly_totals``.

Assertions target the protocol -- the per-week totals returned -- never the storage
layout or the SQL used to compute them.
"""

from collections.abc import Callable
from datetime import date

import pytest

from app.domain.models import WeekTotals
from tests.db.builders import make_activity, make_lap

pytestmark = pytest.mark.anyio

# A full Monday-Sunday week.
WEEK_1_START = date(2026, 11, 2)  # Monday
WEEK_1_MONDAY = "2026-11-02T06:00:00Z"
WEEK_1_SUNDAY = "2026-11-08T22:00:00Z"
WEEK_2_START = date(2026, 11, 9)  # Monday, the week after WEEK_1_START
WEEK_2_MONDAY = "2026-11-09T06:00:00Z"
# The Sunday just before WEEK_1_START: the last instant of the week before it.
BEFORE_WEEK_1 = "2026-11-01T23:00:00Z"


def _laps(distance: float, duration: float) -> list:
    return [make_lap(1, distance=distance, duration=duration)]


@pytest.fixture
def totals(activity_repo, user_id) -> Callable:
    """The user's weekly totals of ``weeks`` weeks from ``first_week_start``."""

    async def run(*, first_week_start: date, weeks: int) -> list[WeekTotals]:
        return await activity_repo.weekly_totals(
            user_id, first_week_start=first_week_start, weeks=weeks
        )

    return run


async def test_a_weeks_activities_are_summed(save_activity, totals):
    await save_activity("strava_1", start_time_local=WEEK_1_MONDAY, laps=_laps(2000.0, 600.0))
    await save_activity("strava_2", start_time_local=WEEK_1_SUNDAY, laps=_laps(3000.0, 900.0))

    weeks = await totals(first_week_start=WEEK_1_START, weeks=1)

    assert weeks == [WeekTotals(WEEK_1_START, distance=5000.0, duration=1500.0, elevation_gain=0.0)]


async def test_a_week_without_activities_is_zero_not_left_out(save_activity, totals):
    await save_activity("strava_1", start_time_local=WEEK_1_MONDAY, laps=_laps(1000.0, 300.0))

    weeks = await totals(first_week_start=WEEK_1_START, weeks=3)

    assert weeks == [
        WeekTotals(WEEK_1_START, distance=1000.0, duration=300.0, elevation_gain=0.0),
        WeekTotals(WEEK_2_START, distance=0.0, duration=0.0, elevation_gain=0.0),
        WeekTotals(date(2026, 11, 16), distance=0.0, duration=0.0, elevation_gain=0.0),
    ]


async def test_the_weeks_come_back_oldest_first(save_activity, totals):
    weeks = await totals(first_week_start=WEEK_1_START, weeks=2)

    assert [week.week_start for week in weeks] == [WEEK_1_START, WEEK_2_START]


async def test_monday_and_sunday_both_belong_to_their_week(save_activity, totals):
    await save_activity("strava_monday", start_time_local=WEEK_1_MONDAY, laps=_laps(1000.0, 300.0))
    await save_activity("strava_sunday", start_time_local=WEEK_1_SUNDAY, laps=_laps(2000.0, 600.0))

    weeks = await totals(first_week_start=WEEK_1_START, weeks=1)

    assert weeks == [WeekTotals(WEEK_1_START, distance=3000.0, duration=900.0, elevation_gain=0.0)]


async def test_an_activity_the_sunday_before_the_range_is_excluded(save_activity, totals):
    await save_activity("strava_before", start_time_local=BEFORE_WEEK_1, laps=_laps(1000.0, 300.0))

    weeks = await totals(first_week_start=WEEK_1_START, weeks=1)

    assert weeks == [WeekTotals(WEEK_1_START, distance=0.0, duration=0.0, elevation_gain=0.0)]


async def test_an_activity_the_monday_after_the_range_is_excluded(save_activity, totals):
    await save_activity("strava_after", start_time_local=WEEK_2_MONDAY, laps=_laps(1000.0, 300.0))

    weeks = await totals(first_week_start=WEEK_1_START, weeks=1)

    assert weeks == [WeekTotals(WEEK_1_START, distance=0.0, duration=0.0, elevation_gain=0.0)]


async def test_another_users_activities_are_excluded(
    activity_repo, save_activity, other_user_id, totals
):
    await save_activity("strava_mine", start_time_local=WEEK_1_MONDAY, laps=_laps(1000.0, 300.0))
    await activity_repo.save(
        make_activity(
            "strava_theirs",
            user_id=other_user_id,
            start_time_local=WEEK_1_MONDAY,
            laps=_laps(9000.0, 2700.0),
        )
    )

    weeks = await totals(first_week_start=WEEK_1_START, weeks=1)

    assert weeks == [WeekTotals(WEEK_1_START, distance=1000.0, duration=300.0, elevation_gain=0.0)]


async def test_a_null_elevation_gain_counts_as_zero(save_activity, totals):
    # ``make_run`` always leaves elevation_gain None; the week still totals to zero,
    # not NULL.
    await save_activity("strava_1", start_time_local=WEEK_1_MONDAY, laps=_laps(1000.0, 300.0))

    weeks = await totals(first_week_start=WEEK_1_START, weeks=1)

    assert weeks[0].elevation_gain == 0.0
