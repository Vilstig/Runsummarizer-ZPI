import pytest

from app.domain.enums import LapType
from app.domain.models import Lap, SegmentStats
from app.summaries.params import BreakParams
from app.summaries.stats import stats_from_params
from app.summaries.summarizers import (
    easy,
    long_intervals,
    race,
    short_intervals,
    time_intervals,
)
from tests.db.builders import make_lap


def _reps(rep_distance: float, rep_durations: list[float]) -> list[Lap]:
    """RUN laps of ``rep_distance`` lasting ``rep_durations``, with a RECOVERY lap of
    200 m in 90 s between each two."""
    laps = []
    for number, duration in enumerate(rep_durations):
        if number:
            laps.append(
                make_lap(len(laps) + 1, type_id=LapType.RECOVERY, distance=200, duration=90)
            )
        laps.append(make_lap(len(laps) + 1, distance=rep_distance, duration=duration))
    return laps


def test_easy_stats_are_the_segments_distance_duration_heart_rate_and_pace():
    params = easy.generate_params([make_lap(1, distance=8000, duration=2400, avg_hr=145.6)])

    assert stats_from_params(params) == SegmentStats(
        distance=8000, duration=2400, avg_hr=145, pace=pytest.approx(300)
    )


def test_race_pace_is_over_the_snapped_race_distance():
    params = race.generate_params([make_lap(1, distance=5050, duration=1010, avg_hr=182)])

    stats = stats_from_params(params)

    assert stats.distance == 5000
    assert stats.pace == pytest.approx(202)
    assert stats.avg_hr == 182


def test_short_interval_stats_use_the_rep_distance_rounded_to_50_m():
    params = short_intervals.generate_params(_reps(1020, [208, 210, 212]))

    assert stats_from_params(params) == SegmentStats(
        distance=3000,
        duration=pytest.approx(630),
        pace=pytest.approx(210),
        rep_count=3,
        rep_distance=1000,
        avg_rep_duration=pytest.approx(210),
        avg_recovery=90,
    )


def test_time_interval_stats_use_the_average_rep_distance():
    params = time_intervals.generate_params(_reps(310, [60, 60, 60, 60]))

    assert stats_from_params(params) == SegmentStats(
        distance=pytest.approx(1240),
        duration=240,
        pace=pytest.approx(60 / 310 * 1000),
        rep_count=4,
        rep_distance=pytest.approx(310),
        avg_rep_duration=60,
        avg_recovery=90,
    )


def test_long_intervals_have_totals_but_no_rep_figures():
    params = long_intervals.generate_params(_reps(2000, [420, 420, 420]))

    assert stats_from_params(params) == SegmentStats(
        distance=6000, duration=1260, pace=pytest.approx(210)
    )


@pytest.mark.parametrize("params", [BreakParams(duration_s=120), None], ids=["break", "none"])
def test_a_break_or_a_segment_with_nothing_to_summarize_has_no_figures(params):
    assert stats_from_params(params) == SegmentStats()


def test_missing_heart_rate_and_distance_are_no_figures():
    lap = Lap(
        index=1,
        distance=None,
        duration=1800,
        speed=None,
        avg_hr=None,
        max_hr=None,
        elevation_gain=None,
        type=LapType.RUN,
    )

    stats = stats_from_params(easy.generate_params([lap]))

    assert stats.avg_hr is None
    assert stats.pace is None
    assert stats.duration == 1800


def test_intervals_without_recovery_laps_have_no_average_recovery():
    laps = [
        make_lap(1, distance=400, duration=80),
        make_lap(2, type_id=LapType.REST, distance=0, duration=120),
        make_lap(3, distance=400, duration=82),
    ]

    assert stats_from_params(short_intervals.generate_params(laps)).avg_recovery is None
