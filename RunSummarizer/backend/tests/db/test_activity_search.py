"""Contract tests for ``AsyncActivityRepository.search_activities``.

Assertions target the protocol -- the page a search returns -- never the storage layout.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import date

import pytest

from app.domain.enums import ActivitySortKey, LapType, Provider, RunType, SegmentRole
from app.domain.models import (
    NEWEST_FIRST,
    ActivityFilter,
    ActivityOrder,
    ActivityPage,
    Lap,
    NumberRange,
    SegmentCriteria,
    UserSegment,
)
from tests.db.builders import make_activity, make_lap

pytestmark = pytest.mark.anyio

# Ordered oldest to newest, all with an explicit offset.
EARLY = "2026-01-05T07:00:00Z"
MIDDLE = "2026-02-05T07:00:00Z"
LATE = "2026-03-05T07:00:00Z"


def _ids(page: ActivityPage) -> list[str]:
    return [record.activity.key for record in page.records]


def _one_lap(distance: float, duration: float) -> list:
    return [make_lap(1, distance=distance, duration=duration)]


SHORT_INTERVALS = frozenset({RunType.SHORT_INTERVALS})
ABOUT_1000_M = NumberRange(min=950, max=1050)


def _interval_session(*rep_sets: tuple[float, int], pace: float = 200) -> list[Lap]:
    """The laps of an easy 2 km warm-up, then each set of ``(rep distance in m, reps)`` run
    at about ``pace`` (s/km) with 200 m recoveries between the reps, the sets and the 1 km
    cool-down each after a standing rest."""
    laps = [make_lap(1, duration=330, avg_hr=130), make_lap(2, duration=330, avg_hr=130)]
    for set_number, (distance, reps) in enumerate(rep_sets):
        if set_number:
            laps.append(_rest(len(laps) + 1))
        for rep in range(reps):
            if rep:
                laps.append(
                    make_lap(
                        len(laps) + 1,
                        type_id=LapType.RECOVERY,
                        distance=200,
                        duration=90,
                        avg_hr=150,
                    )
                )
            # rep times differ by a second, so the set isn't time intervals
            laps.append(
                make_lap(
                    len(laps) + 1,
                    distance=distance,
                    duration=distance * pace / 1000 + rep,
                    avg_hr=170,
                )
            )
    laps.append(_rest(len(laps) + 1))
    laps.append(make_lap(len(laps) + 1, duration=340, avg_hr=130))
    return laps


def _rest(lap_index: int) -> Lap:
    return make_lap(lap_index, type_id=LapType.REST, distance=10, duration=60, avg_hr=120)


@pytest.fixture
def search(activity_repo, user_id) -> Callable:
    """Search the activities of ``user_id`` with the ``ActivityFilter`` fields given."""

    async def run(
        *, order: ActivityOrder = NEWEST_FIRST, limit: int = 50, offset: int = 0, **filters
    ) -> ActivityPage:
        return await activity_repo.search_activities(
            ActivityFilter(user_id=user_id, **filters), order=order, limit=limit, offset=offset
        )

    return run


async def test_a_search_without_filters_finds_every_activity_newest_first(save_activity, search):
    await save_activity("strava_middle", start_time_local=MIDDLE)
    await save_activity("strava_early", start_time_local=EARLY)
    await save_activity("strava_late", start_time_local=LATE)

    page = await search()

    assert _ids(page) == ["strava_late", "strava_middle", "strava_early"]
    assert page.total == 3


async def test_a_search_returns_each_activitys_segments_without_laps(save_activity, search):
    early = await save_activity("strava_early", start_time_local=EARLY)
    late = await save_activity(
        "strava_late",
        start_time_local=LATE,
        laps=[make_lap(index) for index in range(1, 6)],
        user_segments=[UserSegment(1, SegmentRole.PREAMBLE), UserSegment(3, SegmentRole.WORK)],
    )

    page = await search()

    assert [record.activity.segments for record in page.records] == [
        late.activity.segments,
        early.activity.segments,
    ]
    assert all(record.activity.laps == [] for record in page.records)


async def test_a_search_finds_only_the_users_activities(
    activity_repo, save_activity, other_user_id, search
):
    await save_activity("strava_mine")
    await activity_repo.save(make_activity("strava_theirs", user_id=other_user_id))

    page = await search()

    assert _ids(page) == ["strava_mine"]
    assert page.total == 1


async def test_the_total_counts_every_match_while_the_records_hold_the_page(save_activity, search):
    await save_activity("strava_early", start_time_local=EARLY)
    await save_activity("strava_middle", start_time_local=MIDDLE)
    await save_activity("strava_late", start_time_local=LATE)

    second_page = await search(limit=2, offset=1)
    past_the_end = await search(limit=2, offset=3)

    assert _ids(second_page) == ["strava_middle", "strava_early"]
    assert second_page.total == 3
    assert past_the_end == ActivityPage(records=[], total=3)


async def test_the_date_window_includes_after_and_excludes_before(save_activity, search):
    await save_activity("strava_early", start_time_local=EARLY)
    await save_activity("strava_middle", start_time_local=MIDDLE)
    await save_activity("strava_late", start_time_local=LATE)

    page = await search(after=date(2026, 2, 5), before=date(2026, 3, 5))

    assert _ids(page) == ["strava_middle"]


async def test_a_search_filters_by_source(save_activity, search):
    await save_activity("strava_1")
    await save_activity("garmin_1", source="garmin")

    page = await search(sources=frozenset({Provider.GARMIN}))

    assert _ids(page) == ["garmin_1"]


async def test_a_search_filters_by_training_type(save_activity, search):
    await save_activity("strava_easy", start_time_local=EARLY)
    await save_activity(
        "strava_tempo",
        start_time_local=LATE,
        user_segments=[UserSegment(1, SegmentRole.WORK, RunType.TEMPO)],
    )

    page = await search(training_types=frozenset({RunType.TEMPO, RunType.RACE}))

    assert _ids(page) == ["strava_tempo"]


async def test_a_range_includes_both_ends(save_activity, search):
    for distance in (5000, 8000, 10000, 12000):
        await save_activity(f"strava_{distance}", laps=_one_lap(distance, 3000))

    page = await search(distance=NumberRange(min=8000, max=10000))

    assert sorted(_ids(page)) == ["strava_10000", "strava_8000"]


async def test_a_range_may_leave_an_end_open(save_activity, search):
    for duration in (1800, 3600, 5400):
        await save_activity(f"strava_{duration}", laps=_one_lap(10000, duration))

    page = await search(duration=NumberRange(max=3600))

    assert sorted(_ids(page)) == ["strava_1800", "strava_3600"]


async def test_a_pace_range_runs_from_the_fastest_to_the_slowest_pace(save_activity, search):
    await save_activity("strava_4min", laps=_one_lap(1000, 240))
    await save_activity("strava_5min", laps=_one_lap(1000, 300))
    await save_activity("strava_6min", laps=_one_lap(1000, 360))

    between = await search(pace=NumberRange(min=270, max=330))
    faster = await search(pace=NumberRange(max=270))

    assert _ids(between) == ["strava_5min"]
    assert _ids(faster) == ["strava_4min"]


async def test_a_search_filters_by_average_heart_rate(save_activity, search):
    await save_activity("strava_easy", avg_hr=135.0)
    await save_activity("strava_hard", avg_hr=172.0)

    page = await search(avg_hr=NumberRange(max=150))

    assert _ids(page) == ["strava_easy"]


async def test_an_activity_missing_the_value_a_range_filters_on_does_not_match(
    save_activity, search
):
    await save_activity("strava_with_hr", avg_hr=140.0)
    await save_activity("strava_without_hr", avg_hr=None)

    page = await search(avg_hr=NumberRange(min=0))

    assert _ids(page) == ["strava_with_hr"]


async def test_an_activity_must_match_every_filter(save_activity, search):
    await save_activity("strava_long", laps=_one_lap(20000, 6000))
    await save_activity("strava_short", laps=_one_lap(5000, 1500))
    await save_activity("garmin_long", source="garmin", laps=_one_lap(20000, 6000))

    page = await search(sources=frozenset({Provider.STRAVA}), distance=NumberRange(min=15000))

    assert _ids(page) == ["strava_long"]


async def test_a_search_sorts_by_distance_either_way(save_activity, search):
    for distance in (8000, 5000, 12000):
        await save_activity(f"strava_{distance}", laps=_one_lap(distance, 3000))

    shortest_first = await search(order=ActivityOrder(ActivitySortKey.DISTANCE, descending=False))
    longest_first = await search(order=ActivityOrder(ActivitySortKey.DISTANCE, descending=True))

    assert _ids(shortest_first) == ["strava_5000", "strava_8000", "strava_12000"]
    assert _ids(longest_first) == ["strava_12000", "strava_8000", "strava_5000"]


async def test_pace_ascending_puts_the_fastest_first(save_activity, search):
    await save_activity("strava_5min", laps=_one_lap(1000, 300))
    await save_activity("strava_4min", laps=_one_lap(1000, 240))
    await save_activity("strava_6min", laps=_one_lap(1000, 360))

    page = await search(order=ActivityOrder(ActivitySortKey.PACE, descending=False))

    assert _ids(page) == ["strava_4min", "strava_5min", "strava_6min"]


@pytest.mark.parametrize("descending", [False, True])
async def test_activities_missing_the_sort_value_come_last(
    activity_repo, save_activity, user_id, search, descending
):
    record = make_activity("strava_no_speed", user_id=user_id)
    await activity_repo.save(replace(record, activity=replace(record.activity, speed=None)))
    await save_activity("strava_4min", laps=_one_lap(1000, 240))
    await save_activity("strava_6min", laps=_one_lap(1000, 360))

    page = await search(order=ActivityOrder(ActivitySortKey.PACE, descending=descending))

    assert _ids(page)[-1] == "strava_no_speed"


@pytest.mark.parametrize("descending", [False, True])
async def test_pages_neither_repeat_nor_skip_activities_that_tie(save_activity, search, descending):
    for name in ("a", "b", "c", "d"):
        await save_activity(f"strava_{name}")
    order = ActivityOrder(ActivitySortKey.DISTANCE, descending=descending)

    pages = [await search(order=order, limit=1, offset=offset) for offset in range(4)]

    assert sorted(key for page in pages for key in _ids(page)) == [
        "strava_a",
        "strava_b",
        "strava_c",
        "strava_d",
    ]


async def test_the_activities_found_have_no_laps(save_activity, search):
    await save_activity("strava_1")

    page = await search()

    assert page.records[0].activity.laps == []


async def test_a_segment_group_finds_the_activities_with_a_segment_meeting_it(
    save_activity, search
):
    await save_activity("strava_1000s", laps=_interval_session((1000, 5)))
    await save_activity("strava_400s", laps=_interval_session((400, 8)))
    await save_activity("strava_easy")

    page = await search(
        segments=(SegmentCriteria(run_types=SHORT_INTERVALS, rep_distance=ABOUT_1000_M),)
    )

    assert _ids(page) == ["strava_1000s"]
    assert page.total == 1


async def test_one_segment_must_meet_every_condition_of_a_group(save_activity, search):
    await save_activity("strava_split", laps=_interval_session((1000, 3), (400, 6)))
    await save_activity("strava_together", laps=_interval_session((1000, 6)))

    page = await search(
        segments=(SegmentCriteria(rep_distance=ABOUT_1000_M, rep_count=NumberRange(min=5)),)
    )

    assert _ids(page) == ["strava_together"]
    assert page.total == 1


async def test_an_activity_must_meet_every_segment_group(save_activity, search):
    await save_activity("strava_1000s_and_400s", laps=_interval_session((1000, 4), (400, 6)))
    await save_activity("strava_1000s", laps=_interval_session((1000, 4)))
    await save_activity("strava_400s", laps=_interval_session((400, 6)))

    page = await search(
        segments=(
            SegmentCriteria(rep_distance=ABOUT_1000_M),
            SegmentCriteria(rep_distance=NumberRange(min=380, max=420)),
        )
    )

    assert _ids(page) == ["strava_1000s_and_400s"]


async def test_a_segment_range_includes_both_ends(save_activity, search):
    for distance in (900, 950, 1000, 1050, 1100):
        await save_activity(f"strava_{distance}s", laps=_interval_session((distance, 5)))

    page = await search(segments=(SegmentCriteria(rep_distance=ABOUT_1000_M),))

    assert sorted(_ids(page)) == ["strava_1000s", "strava_1050s", "strava_950s"]


async def test_a_segment_pace_range_runs_from_the_fastest_to_the_slowest_pace(
    save_activity, search
):
    await save_activity("strava_fast", laps=_interval_session((1000, 5), pace=190))
    await save_activity("strava_slow", laps=_interval_session((1000, 5), pace=220))

    page = await search(segments=(SegmentCriteria(pace=NumberRange(max=200)),))

    assert _ids(page) == ["strava_fast"]


async def test_warm_ups_cool_downs_and_breaks_do_not_match_a_segment_group(save_activity, search):
    await save_activity("strava_intervals", laps=_interval_session((1000, 5)))
    await save_activity("strava_easy")

    page = await search(segments=(SegmentCriteria(run_types=frozenset({RunType.EASY})),))

    assert _ids(page) == ["strava_easy"]


async def test_a_segment_missing_the_value_a_range_filters_on_does_not_match(save_activity, search):
    await save_activity("strava_intervals", laps=_interval_session((1000, 5)))

    with_heart_rate = await search(
        segments=(SegmentCriteria(run_types=SHORT_INTERVALS, avg_hr=NumberRange(min=0)),)
    )
    without = await search(segments=(SegmentCriteria(run_types=SHORT_INTERVALS),))

    assert _ids(with_heart_rate) == []
    assert _ids(without) == ["strava_intervals"]


async def test_segment_groups_combine_with_the_activity_filters(save_activity, search):
    await save_activity("strava_1000s", laps=_interval_session((1000, 5)))
    await save_activity("garmin_1000s", source="garmin", laps=_interval_session((1000, 5)))

    page = await search(
        sources=frozenset({Provider.GARMIN}),
        segments=(SegmentCriteria(rep_distance=ABOUT_1000_M),),
    )

    assert _ids(page) == ["garmin_1000s"]


async def test_a_segment_search_finds_only_the_users_activities(
    activity_repo, save_activity, other_user_id, search
):
    await save_activity("strava_mine", laps=_interval_session((1000, 5)))
    await activity_repo.save(
        make_activity("strava_theirs", user_id=other_user_id, laps=_interval_session((1000, 5)))
    )

    page = await search(segments=(SegmentCriteria(rep_distance=ABOUT_1000_M),))

    assert _ids(page) == ["strava_mine"]
    assert page.total == 1
