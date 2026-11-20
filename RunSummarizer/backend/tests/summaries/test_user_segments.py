"""Segmenting an activity into the user's segments: which segments are refused, the laps,
role, run type and label of each, and what a lap edit and a summary make of them."""

from dataclasses import replace
from itertools import combinations, product

import pytest

from app.domain.enums import LapType, RunType, SegmentRole
from app.domain.errors import InvalidSegmentationError
from app.domain.models import Activity, UserSegment
from app.summaries.segmentation import relabel_laps, run_segments, segment_activity
from app.summaries.summary import summarize
from app.summaries.user_segments import check_user_segments, user_segment_laps
from tests.db.builders import make_lap, make_run

PREAMBLE, WORK, EPILOGUE, BREAK = (
    SegmentRole.PREAMBLE,
    SegmentRole.WORK,
    SegmentRole.EPILOGUE,
    SegmentRole.BREAK,
)

# Lap indexes with gaps: a segment runs to the lap before the next start, not to its index - 1.
GAPPED_LAPS = [make_lap(index) for index in (0, 1, 3, 4, 7, 8)]

# A warm-up, four 400 m reps with jog recoveries and a cool-down.
INTERVAL_SESSION = [
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


def segmented(laps, *user_segments: UserSegment) -> Activity:
    return make_run("strava_1", laps=laps, user_segments=user_segments)


def outline(activity: Activity) -> list[tuple]:
    """(start, end, role, run type, label) of each of the activity's segments."""
    return [
        (
            segment.start_lap_index,
            segment.end_lap_index,
            segment.role,
            segment.run_type,
            segment.label,
        )
        for segment in activity.segments
    ]


# ---------- check_user_segments ----------


@pytest.mark.parametrize(
    ("user_segments", "message"),
    [
        pytest.param([], "Give at least one segment", id="no segments"),
        pytest.param(
            [UserSegment(1, WORK)],
            "Segment 0: the first segment must start at the first lap, 0",
            id="first start after the first lap",
        ),
        pytest.param(
            [UserSegment(0, WORK), UserSegment(4, WORK), UserSegment(3, WORK)],
            "Segment 2: it must start after the previous segment's start lap",
            id="starts out of order",
        ),
        pytest.param(
            [UserSegment(0, WORK), UserSegment(3, WORK), UserSegment(3, BREAK)],
            "Segment 2: it must start after the previous segment's start lap",
            id="two segments at one lap",
        ),
        pytest.param(
            [UserSegment(0, WORK), UserSegment(2, WORK)],
            "Segment 1: the activity has no lap 2",
            id="start at a missing lap index",
        ),
        pytest.param(
            [UserSegment(-1, WORK)],
            "Segment 0: the activity has no lap -1",
            id="start before every lap",
        ),
        pytest.param(
            [UserSegment(0, WORK), UserSegment(4, BREAK, RunType.EASY)],
            "Segment 1: a break has no run type",
            id="break with a run type",
        ),
    ],
)
def test_segments_that_do_not_cover_the_laps_are_refused(user_segments, message):
    with pytest.raises(InvalidSegmentationError) as refused:
        check_user_segments(GAPPED_LAPS, user_segments)

    assert str(refused.value) == message


def test_an_activity_without_laps_takes_no_segments():
    with pytest.raises(InvalidSegmentationError, match="has no lap 0"):
        check_user_segments([], [UserSegment(0, WORK)])


def test_segmenting_with_refused_segments_raises():
    activity = replace(
        make_run("strava_1", laps=GAPPED_LAPS), user_segments=(UserSegment(1, WORK),)
    )

    with pytest.raises(InvalidSegmentationError):
        segment_activity(activity)


@pytest.mark.parametrize("role", list(SegmentRole))
def test_one_segment_of_any_role_covers_every_lap(role):
    check_user_segments(GAPPED_LAPS, [UserSegment(0, role)])


# ---------- the laps of each segment ----------


def test_a_segment_runs_to_the_lap_before_the_next_start():
    laps = user_segment_laps(
        GAPPED_LAPS, [UserSegment(0, PREAMBLE), UserSegment(3, WORK), UserSegment(8, EPILOGUE)]
    )

    assert [[lap.index for lap in segment] for segment in laps] == [[0, 1], [3, 4, 7], [8]]


# Every list of 1-4 starts drawn from the lap indexes, an index between two laps and one
# past the last lap, in any order and with repeats.
CANDIDATE_STARTS = [0, 1, 2, 3, 4, 7, 8, 9]
EVERY_START_LIST = [
    starts for count in range(1, 5) for starts in product(CANDIDATE_STARTS, repeat=count)
]


def test_segments_that_pass_the_check_cover_every_lap_once_in_order():
    accepted = 0
    for starts in EVERY_START_LIST:
        user_segments = [UserSegment(start, WORK) for start in starts]
        try:
            laps = user_segment_laps(GAPPED_LAPS, user_segments)
        except InvalidSegmentationError:
            continue
        accepted += 1
        assert [lap for segment in laps for lap in segment] == GAPPED_LAPS, starts
        assert all(segment for segment in laps), starts
        assert [segment[0].index for segment in laps] == list(starts), starts

    assert accepted == 1 + 5 + 10 + 10  # the first lap, plus 0-3 of the other five laps


def test_the_stored_segments_cover_every_lap_once_in_order():
    roles = [WORK, BREAK, EPILOGUE, PREAMBLE]
    for count in range(len(GAPPED_LAPS)):
        for later_starts in combinations(GAPPED_LAPS[1:], count):
            starts = [GAPPED_LAPS[0].index, *(lap.index for lap in later_starts)]
            user_segments = [
                UserSegment(start, roles[position % 4]) for position, start in enumerate(starts)
            ]

            activity = segmented(GAPPED_LAPS, *user_segments)

            covered = [
                lap
                for segment in activity.segments
                for lap in GAPPED_LAPS
                if segment.start_lap_index <= lap.index <= segment.end_lap_index
            ]
            assert covered == GAPPED_LAPS, starts
            assert [segment.start_lap_index for segment in activity.segments] == starts


# ---------- run type and label ----------


def test_untyped_segments_take_their_role_s_run_type_and_label():
    activity = segmented(
        INTERVAL_SESSION,
        UserSegment(1, PREAMBLE),
        UserSegment(3, WORK),
        UserSegment(10, BREAK),
        UserSegment(11, EPILOGUE),
    )

    assert outline(activity) == [
        (1, 2, PREAMBLE, RunType.EASY, "Rozgrzewka"),
        (3, 9, WORK, RunType.SHORT_INTERVALS, "Interwały"),
        (10, 10, BREAK, RunType.EASY, None),
        (11, 11, EPILOGUE, RunType.EASY, "Schłodzenie"),
    ]
    assert activity.training_type == RunType.SHORT_INTERVALS


def test_a_break_has_no_run_type_while_segmenting():
    user_segments = (UserSegment(1, PREAMBLE), UserSegment(3, WORK), UserSegment(10, BREAK))
    activity = replace(make_run("strava_1", laps=INTERVAL_SESSION), user_segments=user_segments)

    assert [segment.run_type for segment in run_segments(activity)] == [
        RunType.EASY,
        RunType.SHORT_INTERVALS,
        None,
    ]


def test_a_warm_up_the_user_set_is_easy_even_at_work_pace():
    activity = segmented(
        INTERVAL_SESSION, UserSegment(1, PREAMBLE), UserSegment(5, WORK), UserSegment(10, EPILOGUE)
    )

    assert outline(activity) == [
        (1, 4, PREAMBLE, RunType.EASY, "Rozgrzewka"),
        (5, 9, WORK, RunType.SHORT_INTERVALS, "Interwały"),
        (10, 11, EPILOGUE, RunType.EASY, "Schłodzenie"),
    ]


@pytest.mark.parametrize(
    ("user_segment", "run_type", "label"),
    [
        (UserSegment(1, WORK, RunType.TEMPO), RunType.TEMPO, "Tempo"),
        (UserSegment(1, WORK, RunType.EASY), RunType.EASY, None),
        (UserSegment(1, PREAMBLE, RunType.TEMPO), RunType.TEMPO, "Rozgrzewka"),
        (UserSegment(1, EPILOGUE, RunType.RACE), RunType.RACE, "Schłodzenie"),
    ],
)
def test_a_run_type_the_user_set_is_kept(user_segment, run_type, label):
    activity = segmented(INTERVAL_SESSION, user_segment)

    assert outline(activity) == [(1, 11, user_segment.role, run_type, label)]
    assert activity.training_type == run_type


# ---------- lap edits ----------


def test_a_lap_edit_keeps_the_boundaries_and_classifies_untyped_segments_again():
    activity = segmented(
        INTERVAL_SESSION,
        UserSegment(1, PREAMBLE),
        UserSegment(3, WORK),
        UserSegment(10, WORK, RunType.TEMPO),
    )

    relabelled = relabel_laps(activity, {4: LapType.RUN, 6: LapType.RUN, 8: LapType.RUN})

    assert relabelled.user_segments == activity.user_segments
    # one of two work segments: classified by its own laps, 318 of its 591 s in zone 4
    assert outline(relabelled) == [
        (1, 2, PREAMBLE, RunType.EASY, "Rozgrzewka"),
        (3, 9, WORK, RunType.TEMPO, "Tempo"),
        (10, 11, WORK, RunType.TEMPO, "Tempo"),
    ]


def test_without_user_segments_a_lap_edit_segments_automatically():
    activity = make_run("strava_1", laps=INTERVAL_SESSION)

    relabelled = relabel_laps(activity, {10: LapType.RUN})

    assert relabelled.user_segments is None
    assert relabelled.segments == segment_activity(relabelled).segments


# ---------- the user's sessions ----------


def test_a_warm_up_split_off_a_progression_run():
    warm_up = [make_lap(1, duration=400.0, avg_hr=128.0), make_lap(2, duration=395.0)]
    progression = [
        make_lap(3 + position, duration=duration, avg_hr=140.0 + 4 * position)
        for position, duration in enumerate(
            [330.0, 320.0, 305.0, 290.0, 275.0, 260.0, 245.0, 230.0]
        )
    ]

    activity = segmented(warm_up + progression, UserSegment(1, PREAMBLE), UserSegment(3, WORK))

    assert outline(activity) == [
        (1, 2, PREAMBLE, RunType.EASY, "Rozgrzewka"),
        (3, 10, WORK, RunType.PROGRESSION_RUN, "Bieg progresywny"),
    ]
    text = summarize(activity).text
    assert text.startswith("Rozgrzewka:\n2.00 km\n")
    assert "\n\nBieg progresywny:\n8.00 km\n" in text


def _reps(first_index: int, distance: float, durations: list[float]) -> list:
    """A rep of ``distance`` m for each of ``durations`` (s), each followed by a 200 m jog."""
    laps = []
    for position, duration in enumerate(durations):
        index = first_index + 2 * position
        laps.append(make_lap(index, distance=distance, duration=duration, avg_hr=172.0))
        laps.append(make_lap(index + 1, type_id=LapType.RECOVERY, distance=200.0, duration=75.0))
    return laps


def test_two_interval_blocks_split_at_the_first_rep_of_the_second():
    reps_300 = _reps(1, 300.0, [60.0, 61.0, 59.0, 60.5, 61.5, 59.5, 60.0, 62.0, 61.0, 60.0])
    reps_250 = _reps(21, 250.0, [48.0, 49.0, 47.5, 48.5, 49.5, 48.0, 47.0, 48.0, 49.0, 48.5])

    activity = segmented(reps_300 + reps_250, UserSegment(1, WORK), UserSegment(21, WORK))

    assert outline(activity) == [
        (1, 20, WORK, RunType.SHORT_INTERVALS, "Interwały"),
        (21, 40, WORK, RunType.SHORT_INTERVALS, "Interwały"),
    ]
    text = summarize(activity).text
    assert "10x300m" in text
    assert "10x250m" in text


def test_several_work_segments_are_each_classified_by_their_own_laps():
    laps = [
        make_lap(1, duration=300.0, avg_hr=185.0),
        make_lap(2, duration=300.0, avg_hr=185.0),
        make_lap(3, duration=300.0, avg_hr=140.0),
        make_lap(4, duration=300.0, avg_hr=140.0),
    ]

    activity = segmented(laps, UserSegment(1, WORK), UserSegment(3, WORK))

    assert [segment.run_type for segment in activity.segments] == [RunType.RACE, RunType.EASY]
