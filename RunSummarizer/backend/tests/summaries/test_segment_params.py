from app.domain.enums import LapType, RunType, SegmentRole
from app.summaries.params import BreakParams, EasyParams
from app.summaries.segment_params import segment_params
from app.summaries.summarizers import easy
from tests.db.builders import make_lap


def test_a_break_is_summarized_by_its_duration():
    laps = [make_lap(1, type_id=LapType.REST, duration=60), make_lap(2, duration=30)]

    assert segment_params(laps, SegmentRole.BREAK, None) == BreakParams(duration_s=90)


def test_trailing_rest_and_recovery_laps_are_left_out_of_the_params():
    laps = [
        make_lap(1, distance=1000, duration=300, avg_hr=140),
        make_lap(2, type_id=LapType.RECOVERY, distance=200, duration=90),
        make_lap(3, type_id=LapType.REST, distance=10, duration=60),
    ]

    params = segment_params(laps, SegmentRole.EPILOGUE, RunType.EASY)

    assert params == EasyParams(distance_m=1000, duration_s=300, avg_hr=140)


def test_a_segment_of_only_rest_and_recovery_laps_has_no_params():
    laps = [make_lap(1, type_id=LapType.RECOVERY), make_lap(2, type_id=LapType.REST)]

    assert segment_params(laps, SegmentRole.WORK, RunType.EASY) is None


def test_a_segment_without_a_run_type_is_summarized_as_easy():
    laps = [make_lap(1, distance=1000, duration=300, avg_hr=140)]

    assert segment_params(laps, SegmentRole.WORK, None) == easy.generate_params(laps)
