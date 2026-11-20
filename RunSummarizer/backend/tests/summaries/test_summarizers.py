from dataclasses import replace

import pytest

from app.domain.enums import LapType, RunType
from app.domain.models import Lap
from app.summaries.summarizers import (
    SUMMARIZERS,
    easy,
    long_intervals,
    race,
    short_intervals,
    time_intervals,
)


def _lap(index: int, lap_type: LapType, distance: float, duration: float) -> Lap:
    return Lap(
        index=index,
        distance=distance,
        duration=duration,
        speed=distance / duration,
        avg_hr=150,
        max_hr=None,
        elevation_gain=None,
        type=lap_type,
    )


def _reps(rep_distance: float, rep_duration: float, count: int) -> list[Lap]:
    laps = []
    for _ in range(count):
        laps.append(_lap(len(laps), LapType.RUN, rep_distance, rep_duration))
        laps.append(_lap(len(laps), LapType.RECOVERY, 150, 90))
    return laps


def test_every_run_type_has_a_summarizer():
    assert set(SUMMARIZERS) == set(RunType)


def test_easy_pace_follows_an_edited_distance():
    params = easy.generate_params([_lap(0, LapType.RUN, 8000, 2400)])
    edited = replace(params, distance_m=8200)

    assert easy.derive(params).pace_s_per_km == pytest.approx(300)
    assert easy.render(edited, easy.derive(edited)).startswith("8.20 km\nŚrednie tempo: 4:53 /km")


def test_short_interval_pace_and_distance_follow_an_edited_rep_distance():
    params = short_intervals.generate_params(_reps(250, 48, 10))
    edited = replace(params, rep_distance_m=200)

    derived = short_intervals.derive(edited)

    assert params.rep_distance_m == 250
    assert derived.distance_m == 2000
    assert derived.avg_rep_pace_s_per_km == pytest.approx(240)
    assert short_intervals.render(edited, derived).startswith("10x200m\n")


def test_time_interval_pace_follows_an_edited_rep_distance():
    params = time_intervals.generate_params(_reps(300, 60, 5))
    edited = replace(params, avg_rep_distance_m=250)

    assert time_intervals.derive(edited).avg_rep_pace_s_per_km == pytest.approx(240)


def test_long_interval_totals_follow_edited_reps():
    params = long_intervals.generate_params(_reps(1950, 420, 3))
    edited = replace(params, reps=tuple(replace(rep, distance_m=2000) for rep in params.reps))

    derived = long_intervals.derive(edited)

    assert derived.distance_m == 6000
    assert derived.duration_s == 1260
    assert derived.pace_s_per_km == pytest.approx(210)


@pytest.mark.parametrize("module", [short_intervals, time_intervals, long_intervals])
def test_interval_params_need_a_run_lap(module):
    laps = [_lap(0, LapType.RECOVERY, 150, 90)]

    assert module.generate_params(laps) is None
    assert module.SUMMARIZER.summarize(laps) == ""


@pytest.mark.parametrize(
    ("distance", "written"), [(5050, "5 km"), (21300, "21.1 km"), (7020, "7.0 km")]
)
def test_race_distance_is_snapped_and_written_as_a_race_distance(distance, written):
    summary = race.SUMMARIZER.summarize([_lap(0, LapType.RUN, distance, distance * 0.2)])

    assert summary.startswith(f"{written}\n")
