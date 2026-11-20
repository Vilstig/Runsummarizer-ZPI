import unittest
from dataclasses import replace
from datetime import UTC, datetime

from app.domain.enums import LapType, Provider, RunType
from app.domain.models import Activity, Lap, ZoneTimes
from app.summaries.classification import classify_segment, segment_zone_times
from app.summaries.segmentation import segment_activity
from app.summaries.summary import summarize


def _run_lap(index: int, distance: float, duration: float, avg_hr: float) -> Lap:
    return Lap(
        index=index,
        type=LapType.RUN,
        distance=distance,
        duration=duration,
        speed=distance / duration,
        avg_hr=avg_hr,
        max_hr=None,
        elevation_gain=None,
    )


def _run_laps(paces: str) -> list[Lap]:
    """1 km run laps from space-separated "m:ss" paces."""
    laps = []
    for index, pace in enumerate(paces.split()):
        minutes, seconds = pace.split(":")
        duration = int(minutes) * 60 + int(seconds)
        laps.append(_run_lap(index, 1000.0, float(duration), 150))
    return laps


def _classify(laps: list[Lap], zone_times: ZoneTimes | None = None) -> RunType:
    duration = sum(lap.duration for lap in laps)
    return classify_segment(laps, zone_times or ZoneTimes(), duration)


class TestProgressionRun(unittest.TestCase):
    def test_smooth_progression(self):
        laps = _run_laps("6:00 5:47 5:34 5:21 5:09 4:56 4:43 4:30")
        self.assertEqual(_classify(laps), RunType.PROGRESSION_RUN)

    def test_three_step_progression(self):
        laps = _run_laps("5:30 5:31 5:29 5:00 5:01 4:59 4:30 4:31 4:29")
        self.assertEqual(_classify(laps), RunType.PROGRESSION_RUN)

    def test_two_step_progression(self):
        laps = _run_laps("5:30 5:30 5:30 5:30 4:30 4:30 4:30 4:30")
        self.assertEqual(_classify(laps), RunType.PROGRESSION_RUN)

    def test_slow_partial_last_lap_is_ignored_by_line_fit(self):
        laps = _run_laps("6:00 5:47 5:34 5:21 5:09 4:56 4:43 4:30")
        laps.append(_run_lap(len(laps), 300.0, 117.0, 140))
        self.assertEqual(_classify(laps), RunType.PROGRESSION_RUN)

    def test_progression_is_checked_before_tempo(self):
        laps = _run_laps("6:00 5:47 5:34 5:21 5:09 4:56 4:43 4:30")
        self.assertEqual(_classify(laps, ZoneTimes(zone4=10**9)), RunType.PROGRESSION_RUN)

    def test_pace_gain_below_55_s_per_km_is_not_progression(self):
        # first 2 km average 5:25.5, last 2 km average 4:34.5
        laps = _run_laps("5:30 5:21 5:13 5:04 4:56 4:47 4:39 4:30")
        self.assertEqual(_classify(laps), RunType.EASY)

    def test_progression_under_6_km_is_not_progression(self):
        laps = _run_laps("6:00 5:40 5:15 4:50 4:30")
        self.assertEqual(_classify(laps), RunType.EASY)

    def test_flat_run_with_fast_finish_is_not_progression(self):
        laps = _run_laps("5:30 5:31 5:29 5:30 5:32 5:30 4:20 4:20")
        self.assertEqual(_classify(laps), RunType.EASY)

    def test_progression_summary_has_polish_header(self):
        laps = _run_laps("6:00 5:47 5:34 5:21 5:09 4:56 4:43 4:30")
        activity = Activity(
            key="1",
            source=Provider.STRAVA,
            name=None,
            start_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
            utc_offset=0,
            timezone=None,
            distance=None,
            duration=sum(lap.duration for lap in laps),
            speed=None,
            avg_hr=None,
            max_hr=None,
            elevation_gain=None,
            zone_times=ZoneTimes(),
            laps=laps,
        )
        segmented = segment_activity(activity)

        self.assertEqual(segmented.training_type, RunType.PROGRESSION_RUN)
        self.assertEqual(len(segmented.segments), 1)
        self.assertEqual(segmented.segments[0].run_type, RunType.PROGRESSION_RUN)
        summary = summarize(replace(activity, segments=segmented.segments)).text
        self.assertTrue(summary.startswith("Bieg progresywny:\n"))


# A steady segment of four 4:00/km laps, 960 s.
STEADY_LAPS = _run_laps("4:00 4:00 4:00 4:00")

ZONE_BOUNDS = (120, 140, 160, 180)  # zones 2-5 start here, in bpm
ACTIVITY_ZONE_TIMES = ZoneTimes(zone5=900)
# 240 s in zone 3 and 240 s in zone 4 of ZONE_BOUNDS
ZONE_3_AND_4_LAPS = [_run_lap(0, 1000.0, 240.0, 150), _run_lap(1, 1000.0, 240.0, 165)]


class TestEffort(unittest.TestCase):
    def test_more_than_half_in_zone_5_is_a_race(self):
        self.assertEqual(_classify(STEADY_LAPS, ZoneTimes(zone4=300, zone5=600)), RunType.RACE)

    def test_more_than_half_in_zones_4_and_5_together_is_tempo(self):
        self.assertEqual(_classify(STEADY_LAPS, ZoneTimes(zone4=250, zone5=250)), RunType.TEMPO)

    def test_more_than_half_in_zone_4_is_tempo(self):
        self.assertEqual(_classify(STEADY_LAPS, ZoneTimes(zone4=500)), RunType.TEMPO)

    def test_exactly_half_in_zones_4_and_5_is_easy(self):
        self.assertEqual(_classify(STEADY_LAPS, ZoneTimes(zone4=240, zone5=240)), RunType.EASY)

    def test_without_heart_rate_data_it_is_easy(self):
        self.assertEqual(_classify(STEADY_LAPS), RunType.EASY)


class TestSegmentZoneTimes(unittest.TestCase):
    def test_a_lone_work_segment_takes_the_activity_zone_times(self):
        zone_times = segment_zone_times(
            ZONE_3_AND_4_LAPS, ACTIVITY_ZONE_TIMES, ZONE_BOUNDS, work_segments=1
        )
        self.assertEqual(zone_times, ACTIVITY_ZONE_TIMES)

    def test_one_of_several_work_segments_takes_its_laps_zone_times(self):
        zone_times = segment_zone_times(
            ZONE_3_AND_4_LAPS, ACTIVITY_ZONE_TIMES, ZONE_BOUNDS, work_segments=2
        )
        self.assertEqual(zone_times, ZoneTimes(zone3=240, zone4=240))


if __name__ == "__main__":
    unittest.main()
