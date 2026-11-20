from dataclasses import replace

import pytest

from app.domain.enums import LapType, RunType, SegmentRole
from app.domain.models import Lap, SegmentStats
from app.summaries.segmentation import segment_activity
from tests.db.builders import make_lap, make_run

WARM_UP = [make_lap(1, duration=330, avg_hr=130), make_lap(2, duration=330, avg_hr=130)]
REPS = [
    make_lap(3, duration=208, avg_hr=170),
    make_lap(4, type_id=LapType.RECOVERY, distance=200, duration=90, avg_hr=170),
    make_lap(5, duration=210, avg_hr=170),
    make_lap(6, type_id=LapType.RECOVERY, distance=200, duration=90, avg_hr=170),
    make_lap(7, duration=212, avg_hr=170),
]
COOL_DOWN = [
    make_lap(8, type_id=LapType.REST, distance=10, duration=60, avg_hr=120),
    make_lap(9, duration=340, avg_hr=130),
]


def _role_type_and_stats(laps: list[Lap]) -> list[tuple[SegmentRole, RunType, SegmentStats]]:
    activity = make_run("strava_1", laps=laps)
    return [(segment.role, segment.run_type, segment.stats) for segment in activity.segments]


def test_segment_activity_gives_each_segment_its_stats():
    assert _role_type_and_stats(WARM_UP + REPS + COOL_DOWN) == [
        (
            SegmentRole.PREAMBLE,
            RunType.EASY,
            SegmentStats(distance=2000, duration=660, avg_hr=130, pace=330),
        ),
        (
            SegmentRole.WORK,
            RunType.SHORT_INTERVALS,
            SegmentStats(
                distance=3000,
                duration=pytest.approx(630),
                pace=pytest.approx(210),
                rep_count=3,
                rep_distance=1000,
                avg_rep_duration=pytest.approx(210),
                avg_recovery=90,
            ),
        ),
        (SegmentRole.BREAK, RunType.EASY, SegmentStats()),
        (
            SegmentRole.EPILOGUE,
            RunType.EASY,
            SegmentStats(distance=1000, duration=340, avg_hr=130, pace=340),
        ),
    ]


def test_segment_stats_follow_edited_lap_distances():
    activity = make_run("strava_1", laps=WARM_UP + REPS + COOL_DOWN)
    edited = [
        replace(lap, distance=1100, version=1) if lap.index in (1, 2) else lap
        for lap in activity.laps
    ]

    warm_up = segment_activity(replace(activity, laps=edited)).segments[0]

    assert warm_up.stats.distance == 2200
    assert warm_up.stats.pace == pytest.approx(300)
