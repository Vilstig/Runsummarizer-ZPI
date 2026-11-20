import unittest
from dataclasses import replace
from datetime import UTC, datetime

from app.domain.enums import LapType, Provider, RunType
from app.domain.models import Activity, Lap, Segment, ZoneTimes
from app.summaries.segmentation import relabel_laps, segment_activity
from app.summaries.summary import summarize


def _lap_dict(
    index: int,
    type_id: LapType,
    *,
    distance: float = 1000,
    duration: float = 300,
    speed: float = 3.0,
    avg_hr: int = 150,
) -> Lap:
    return Lap(
        index=index,
        type=type_id,
        distance=distance,
        duration=duration,
        speed=speed,
        avg_hr=avg_hr,
        max_hr=None,
        elevation_gain=None,
    )


def _processed(laps: list[Lap], **overrides) -> Activity:
    activity = Activity(
        key="1",
        source=Provider.STRAVA,
        name="Test run",
        start_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        utc_offset=0,
        timezone=None,
        distance=sum(lap.distance for lap in laps),
        duration=sum(lap.duration for lap in laps),
        speed=None,
        avg_hr=150,
        max_hr=None,
        elevation_gain=None,
        zone_times=ZoneTimes(),
        laps=laps,
    )
    return replace(activity, **overrides)


def build_segments(activity: Activity) -> tuple[list[Segment], RunType]:
    segmented = segment_activity(activity)
    return segmented.segments, segmented.training_type


class TestSegmentation(unittest.TestCase):
    def test_pure_easy_run_single_segment(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=3000, duration=1200, speed=2.5, avg_hr=130),
            _lap_dict(1, LapType.RUN, distance=3000, duration=1180, speed=2.55, avg_hr=132),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(len(segments), 1)
        self.assertEqual(dominant, RunType.EASY)
        summary = summarize(replace(processed, segments=segments)).text
        self.assertIn("km", summary)
        self.assertIn("Średnie tempo", summary)

    def test_short_intervals_between_a_slow_first_and_last_lap(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=360, speed=2.5, avg_hr=120),
            _lap_dict(1, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(2, LapType.RECOVERY, distance=200, duration=90, speed=2.0, avg_hr=130),
            _lap_dict(3, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=172),
            _lap_dict(4, LapType.RECOVERY, distance=200, duration=88, speed=2.1, avg_hr=128),
            _lap_dict(5, LapType.RUN, distance=1000, duration=380, speed=2.4, avg_hr=118),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0].role, "preamble")
        self.assertEqual(segments[1].role, "work")
        self.assertEqual(segments[2].role, "epilogue")
        self.assertEqual(segments[1].run_type, RunType.SHORT_INTERVALS)
        self.assertEqual(dominant, RunType.SHORT_INTERVALS)

    def test_run_labeled_warmup_and_cooldown(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=3000, duration=1200, speed=2.3, avg_hr=125),
            _lap_dict(1, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(2, LapType.RECOVERY, distance=200, duration=90, speed=2.0, avg_hr=130),
            _lap_dict(3, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=172),
            _lap_dict(4, LapType.RECOVERY, distance=200, duration=88, speed=2.1, avg_hr=128),
            _lap_dict(5, LapType.RUN, distance=2000, duration=800, speed=2.4, avg_hr=120),
        ]
        processed = _processed(laps)
        segments, _ = build_segments(processed)

        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0].run_type, RunType.EASY)
        self.assertEqual(segments[2].run_type, RunType.EASY)
        summary = summarize(replace(processed, segments=segments)).text
        self.assertIn("Rozgrzewka", summary)
        self.assertIn("Schłodzenie", summary)

    def test_long_intervals_rest_short_intervals(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=1600, duration=420, speed=3.8, avg_hr=165),
            _lap_dict(1, LapType.RECOVERY, distance=400, duration=120, speed=2.5, avg_hr=130),
            _lap_dict(2, LapType.RUN, distance=1600, duration=430, speed=3.7, avg_hr=166),
            _lap_dict(3, LapType.REST, distance=200, duration=400, speed=1.0, avg_hr=110),
            _lap_dict(4, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(5, LapType.RECOVERY, distance=200, duration=90, speed=2.0, avg_hr=130),
            _lap_dict(6, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=172),
            _lap_dict(7, LapType.RECOVERY, distance=200, duration=88, speed=2.1, avg_hr=128),
        ]
        processed = _processed(laps)
        segments, _ = build_segments(processed)

        roles = [seg.role for seg in segments]
        self.assertIn("break", roles)
        break_idx = roles.index("break")
        self.assertEqual(segments[break_idx].start_lap_index, 3)
        self.assertEqual(segments[break_idx].end_lap_index, 3)

        work_segments = [seg for seg in segments if seg.role == "work"]
        self.assertGreaterEqual(len(work_segments), 2)
        for work in work_segments:
            work_laps = [
                lap
                for lap in processed.laps
                if work.start_lap_index <= lap.index <= work.end_lap_index
            ]
            self.assertFalse(any(lap.type == LapType.REST for lap in work_laps))

        work_types = [seg.run_type for seg in work_segments]
        self.assertIn(RunType.SHORT_INTERVALS, work_types)

    def test_apply_lap_type_updates_rebuilds_segments(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=3000, duration=1200, speed=2.3, avg_hr=125),
            _lap_dict(1, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(2, LapType.RECOVERY, distance=200, duration=90, speed=2.0, avg_hr=130),
            _lap_dict(3, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=172),
            _lap_dict(4, LapType.RECOVERY, distance=200, duration=88, speed=2.1, avg_hr=128),
        ]
        before, _ = build_segments(_processed(laps))
        processed = relabel_laps(_processed(laps), {4: LapType.REST})

        def spans(segments: list[Segment]) -> list[tuple]:
            return [(seg.role, seg.start_lap_index, seg.end_lap_index) for seg in segments]

        self.assertEqual(spans(before), [("preamble", 0, 0), ("work", 1, 4)])
        self.assertEqual(
            spans(processed.segments), [("preamble", 0, 0), ("work", 1, 3), ("break", 4, 4)]
        )
        self.assertEqual(processed.segments[0].run_type, RunType.EASY)

    def test_tempo_then_short_intervals_without_rest(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=3000, duration=900, speed=3.3, avg_hr=165),
            _lap_dict(1, LapType.RUN, distance=3000, duration=910, speed=3.2, avg_hr=166),
            _lap_dict(2, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=175),
            _lap_dict(3, LapType.RECOVERY, distance=200, duration=90, speed=2.0, avg_hr=130),
            _lap_dict(4, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=172),
            _lap_dict(5, LapType.RECOVERY, distance=200, duration=88, speed=2.1, avg_hr=128),
        ]
        processed = _processed(laps, zone_times=ZoneTimes(zone4=500))
        segments, _ = build_segments(processed)

        work_segments = [seg for seg in segments if seg.role == "work"]
        self.assertGreaterEqual(len(work_segments), 2)

    def test_easy_run(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=286, speed=3.5, avg_hr=140),
            _lap_dict(1, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=140),
            _lap_dict(2, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=140),
            _lap_dict(3, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=140),
            _lap_dict(4, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=140),
            _lap_dict(5, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=140),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].role, "work")
        self.assertEqual(segments[0].run_type, RunType.EASY)
        self.assertEqual(dominant, RunType.EASY)

    def test_rest_between_work_blocks_renders_przerwa(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=3000, duration=900, speed=3.3, avg_hr=165),
            _lap_dict(1, LapType.RUN, distance=3000, duration=910, speed=3.2, avg_hr=166),
            _lap_dict(2, LapType.REST, distance=0, duration=300, speed=0, avg_hr=110),
            _lap_dict(3, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(4, LapType.RECOVERY, distance=200, duration=90, speed=2.0, avg_hr=130),
            _lap_dict(5, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=172),
            _lap_dict(6, LapType.RECOVERY, distance=200, duration=88, speed=2.1, avg_hr=128),
        ]
        processed = _processed(laps)
        segments, _ = build_segments(processed)
        summary = summarize(replace(processed, segments=segments)).text

        roles = [seg.role for seg in segments]
        self.assertEqual(roles.count("break"), 1)
        self.assertIn("Przerwa: 5:00", summary)
        przerwa_pos = summary.index("Przerwa:")
        self.assertGreater(przerwa_pos, 0)
        self.assertLess(przerwa_pos, len(summary) - 1)

    def test_warmup_tempo_intervals_cooldown(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=300, speed=3.3, avg_hr=140),
            _lap_dict(1, LapType.RUN, distance=1000, duration=300, speed=3.3, avg_hr=140),
            _lap_dict(2, LapType.RUN, distance=1000, duration=300, speed=3.3, avg_hr=140),
            _lap_dict(3, LapType.REST, distance=200, duration=1000, speed=1, avg_hr=110),
            _lap_dict(4, LapType.RUN, distance=1000, duration=217, speed=4.61, avg_hr=154.1),
            _lap_dict(5, LapType.RUN, distance=1014, duration=217, speed=4.67, avg_hr=157),
            _lap_dict(6, LapType.RUN, distance=1006, duration=234, speed=4.3, avg_hr=164),
            _lap_dict(7, LapType.RUN, distance=1000.5, duration=224, speed=4.47, avg_hr=164.1),
            _lap_dict(8, LapType.RUN, distance=1011.5, duration=215, speed=4.7, avg_hr=159.1),
            _lap_dict(9, LapType.REST, distance=200, duration=1000, speed=1, avg_hr=120),
            _lap_dict(10, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(11, LapType.RECOVERY, distance=100, duration=60, speed=1.66, avg_hr=140),
            _lap_dict(12, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(13, LapType.RECOVERY, distance=100, duration=60, speed=1.66, avg_hr=140),
            _lap_dict(14, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(15, LapType.RECOVERY, distance=100, duration=60, speed=1.66, avg_hr=140),
            _lap_dict(16, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=172),
            _lap_dict(17, LapType.REST, distance=200, duration=1200, speed=0.8, avg_hr=128),
            _lap_dict(18, LapType.RUN, distance=1000, duration=290, speed=3.34, avg_hr=140),
            _lap_dict(19, LapType.RUN, distance=1000, duration=290, speed=3.34, avg_hr=140),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(
            [seg.role for seg in segments],
            ["work", "break", "work", "break", "work", "break", "work"],
        )
        work_segments = [seg for seg in segments if seg.role == "work"]
        self.assertEqual(work_segments[0].run_type, RunType.EASY)
        self.assertEqual(work_segments[1].run_type, RunType.EASY)
        self.assertEqual(work_segments[2].run_type, RunType.SHORT_INTERVALS)
        self.assertEqual(work_segments[3].run_type, RunType.EASY)
        self.assertEqual(dominant, RunType.SHORT_INTERVALS)

        summary = summarize(replace(processed, segments=segments)).text
        self.assertIn("Przerwa:", summary)
        self.assertEqual(summary.count("Przerwa:"), 3)
        print(summary)

    def test_easy_run_with_short_last_lap(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=286, speed=3.5, avg_hr=140),
            _lap_dict(1, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=142),
            _lap_dict(2, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=145),
            _lap_dict(3, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=144),
            _lap_dict(4, LapType.RUN, distance=1000, duration=250, speed=3.5, avg_hr=146),
            _lap_dict(5, LapType.RUN, distance=43, duration=10, speed=4.38, avg_hr=150),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].role, "work")
        self.assertEqual(segments[0].run_type, RunType.EASY)
        self.assertEqual(dominant, RunType.EASY)

    def test_trailing_rest_and_recovery_omitted_from_summary(self):
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=300, speed=3.3, avg_hr=140),
            _lap_dict(1, LapType.REST, distance=0, duration=180, speed=0, avg_hr=110),
            _lap_dict(2, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=170),
            _lap_dict(3, LapType.RECOVERY, distance=200, duration=90, speed=2.0, avg_hr=130),
            _lap_dict(4, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=172),
            _lap_dict(5, LapType.RECOVERY, distance=200, duration=88, speed=2.1, avg_hr=128),
            _lap_dict(6, LapType.REST, distance=0, duration=600, speed=0, avg_hr=100),
        ]
        processed = _processed(laps)
        segments, _ = build_segments(processed)
        summary = summarize(replace(processed, segments=segments)).text

        self.assertTrue(any(seg.role == "break" for seg in segments))
        self.assertEqual(segments[-1].role, "break")
        self.assertIn("Przerwa:", summary)
        self.assertEqual(summary.count("Przerwa:"), 1)
        self.assertNotRegex(summary, r"Przerwa: 10:00\s*$")

    def test_time_intervals_same_duration_varying_distance(self):
        # Fixed-time intervals (e.g. 4x1min): identical run duration, distances vary slightly.
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=360, speed=2.5, avg_hr=120),
            _lap_dict(1, LapType.RUN, distance=285, duration=60, speed=4.75, avg_hr=168),
            _lap_dict(2, LapType.RECOVERY, distance=100, duration=60, speed=1.67, avg_hr=135),
            _lap_dict(3, LapType.RUN, distance=300, duration=60, speed=5.0, avg_hr=170),
            _lap_dict(4, LapType.RECOVERY, distance=105, duration=60, speed=1.75, avg_hr=134),
            _lap_dict(5, LapType.RUN, distance=310, duration=60, speed=5.17, avg_hr=172),
            _lap_dict(6, LapType.RECOVERY, distance=95, duration=60, speed=1.58, avg_hr=133),
            _lap_dict(7, LapType.RUN, distance=295, duration=60, speed=4.92, avg_hr=169),
            _lap_dict(8, LapType.RECOVERY, distance=100, duration=60, speed=1.67, avg_hr=132),
            _lap_dict(9, LapType.RUN, distance=1000, duration=380, speed=2.4, avg_hr=118),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0].role, "preamble")
        self.assertEqual(segments[1].role, "work")
        self.assertEqual(segments[2].role, "epilogue")
        self.assertEqual(segments[1].run_type, RunType.TIME_INTERVALS)
        self.assertEqual(dominant, RunType.TIME_INTERVALS)

    def test_easy_10k_then_10x200m_then_easy_2k(self):
        # Activity 01a121a9-8608-73c4-9c3e-05b73d595f2c
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000.0, duration=275.0, speed=3.64, avg_hr=141.8),
            _lap_dict(1, LapType.RUN, distance=1000.0, duration=278.0, speed=3.6, avg_hr=150.4),
            _lap_dict(2, LapType.RUN, distance=1000.0, duration=275.0, speed=3.64, avg_hr=148.1),
            _lap_dict(3, LapType.RUN, distance=1000.0, duration=274.0, speed=3.65, avg_hr=150.3),
            _lap_dict(4, LapType.RUN, distance=1000.0, duration=273.0, speed=3.66, avg_hr=152.7),
            _lap_dict(5, LapType.RUN, distance=1000.0, duration=271.0, speed=3.69, avg_hr=152.5),
            _lap_dict(6, LapType.RUN, distance=1000.0, duration=268.0, speed=3.73, avg_hr=152.0),
            _lap_dict(7, LapType.RUN, distance=1000.0, duration=273.0, speed=3.66, avg_hr=149.4),
            _lap_dict(8, LapType.RUN, distance=1000.0, duration=265.0, speed=3.77, avg_hr=149.2),
            _lap_dict(9, LapType.RUN, distance=949.21, duration=258.0, speed=3.68, avg_hr=150.8),
            _lap_dict(10, LapType.RUN, distance=197.12, duration=36.0, speed=5.48, avg_hr=150.0),
            _lap_dict(
                11, LapType.RECOVERY, distance=73.41, duration=60.0, speed=1.22, avg_hr=160.7
            ),
            _lap_dict(12, LapType.RUN, distance=196.15, duration=35.0, speed=5.6, avg_hr=156.1),
            _lap_dict(
                13, LapType.RECOVERY, distance=125.59, duration=59.0, speed=2.13, avg_hr=157.0
            ),
            _lap_dict(14, LapType.RUN, distance=193.92, duration=34.0, speed=5.7, avg_hr=164.4),
            _lap_dict(
                15, LapType.RECOVERY, distance=95.45, duration=60.0, speed=1.59, avg_hr=165.0
            ),
            _lap_dict(16, LapType.RUN, distance=194.21, duration=33.0, speed=5.89, avg_hr=164.5),
            _lap_dict(
                17, LapType.RECOVERY, distance=123.06, duration=60.0, speed=2.05, avg_hr=164.2
            ),
            _lap_dict(18, LapType.RUN, distance=196.2, duration=34.0, speed=5.77, avg_hr=165.8),
            _lap_dict(19, LapType.RECOVERY, distance=94.14, duration=59.0, speed=1.6, avg_hr=167.4),
            _lap_dict(20, LapType.RUN, distance=200.38, duration=34.0, speed=5.89, avg_hr=163.6),
            _lap_dict(
                21, LapType.RECOVERY, distance=121.45, duration=60.0, speed=2.02, avg_hr=161.1
            ),
            _lap_dict(22, LapType.RUN, distance=192.62, duration=34.0, speed=5.67, avg_hr=164.6),
            _lap_dict(23, LapType.RECOVERY, distance=93.1, duration=60.0, speed=1.55, avg_hr=166.1),
            _lap_dict(24, LapType.RUN, distance=198.11, duration=34.0, speed=5.83, avg_hr=165.4),
            _lap_dict(
                25, LapType.RECOVERY, distance=124.45, duration=59.0, speed=2.11, avg_hr=164.8
            ),
            _lap_dict(26, LapType.RUN, distance=196.8, duration=33.0, speed=5.96, avg_hr=170.2),
            _lap_dict(
                27, LapType.RECOVERY, distance=90.77, duration=60.0, speed=1.51, avg_hr=172.9
            ),
            _lap_dict(28, LapType.RUN, distance=193.43, duration=33.0, speed=5.86, avg_hr=169.1),
            _lap_dict(29, LapType.RUN, distance=1000.0, duration=312.0, speed=3.21, avg_hr=148.7),
            _lap_dict(30, LapType.RUN, distance=1000.0, duration=282.0, speed=3.55, avg_hr=147.3),
            _lap_dict(31, LapType.RUN, distance=126.71, duration=35.0, speed=3.62, avg_hr=148.4),
        ]
        processed = _processed(
            laps,
            zone_times=ZoneTimes(zone1=10.3, zone2=134.6, zone3=3456.8, zone4=615.8, zone5=0.0),
        )
        segments, dominant = build_segments(processed)

        self.assertEqual(
            [(seg.start_lap_index, seg.end_lap_index, seg.run_type) for seg in segments],
            [
                (0, 9, RunType.EASY),
                (10, 28, RunType.SHORT_INTERVALS),
                (29, 31, RunType.EASY),
            ],
        )
        self.assertEqual(dominant, RunType.SHORT_INTERVALS)

    def test_warmup_3x3km_one_recovery_between_reps_cooldown(self):
        # Each 3 km rep is three 1 km RUN laps.
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=130),
            _lap_dict(1, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=132),
            _lap_dict(2, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=134),
            _lap_dict(3, LapType.RUN, distance=1000, duration=215, speed=4.65, avg_hr=165),
            _lap_dict(4, LapType.RUN, distance=1000, duration=214, speed=4.67, avg_hr=170),
            _lap_dict(5, LapType.RUN, distance=1000, duration=216, speed=4.63, avg_hr=172),
            _lap_dict(6, LapType.RECOVERY, distance=300, duration=180, speed=1.67, avg_hr=140),
            _lap_dict(7, LapType.RUN, distance=1000, duration=215, speed=4.65, avg_hr=166),
            _lap_dict(8, LapType.RUN, distance=1000, duration=215, speed=4.65, avg_hr=171),
            _lap_dict(9, LapType.RUN, distance=1000, duration=216, speed=4.63, avg_hr=173),
            _lap_dict(10, LapType.RECOVERY, distance=300, duration=180, speed=1.67, avg_hr=141),
            _lap_dict(11, LapType.RUN, distance=1000, duration=214, speed=4.67, avg_hr=167),
            _lap_dict(12, LapType.RUN, distance=1000, duration=215, speed=4.65, avg_hr=172),
            _lap_dict(13, LapType.RUN, distance=1000, duration=213, speed=4.69, avg_hr=175),
            _lap_dict(14, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=140),
            _lap_dict(15, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=128),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(
            [(seg.start_lap_index, seg.end_lap_index, seg.role, seg.run_type) for seg in segments],
            [
                (0, 2, "preamble", RunType.EASY),
                (3, 13, "work", RunType.LONG_INTERVALS),
                (14, 15, "epilogue", RunType.EASY),
            ],
        )
        self.assertEqual(dominant, RunType.LONG_INTERVALS)

    def test_warmup_2x3km_one_recovery_between_reps_cooldown(self):
        # A single recovery: the reps count as intervals because both sides are 3 km.
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=130),
            _lap_dict(1, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=132),
            _lap_dict(2, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=134),
            _lap_dict(3, LapType.RUN, distance=1000, duration=215, speed=4.65, avg_hr=165),
            _lap_dict(4, LapType.RUN, distance=1000, duration=214, speed=4.67, avg_hr=170),
            _lap_dict(5, LapType.RUN, distance=1000, duration=216, speed=4.63, avg_hr=172),
            _lap_dict(6, LapType.RECOVERY, distance=300, duration=180, speed=1.67, avg_hr=140),
            _lap_dict(7, LapType.RUN, distance=1000, duration=215, speed=4.65, avg_hr=166),
            _lap_dict(8, LapType.RUN, distance=1000, duration=215, speed=4.65, avg_hr=171),
            _lap_dict(9, LapType.RUN, distance=1000, duration=216, speed=4.63, avg_hr=173),
            _lap_dict(10, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=140),
            _lap_dict(11, LapType.RUN, distance=1000, duration=330, speed=3.03, avg_hr=128),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(
            [(seg.start_lap_index, seg.end_lap_index, seg.role, seg.run_type) for seg in segments],
            [
                (0, 2, "preamble", RunType.EASY),
                (3, 9, "work", RunType.LONG_INTERVALS),
                (10, 11, "epilogue", RunType.EASY),
            ],
        )
        self.assertEqual(dominant, RunType.LONG_INTERVALS)

    def test_single_recovery_with_unequal_sides_is_not_intervals(self):
        # 5 km, one recovery lap, 3 km at the same pace: the sides differ, so not 2 reps.
        laps = [
            _lap_dict(0, LapType.RUN, distance=1000, duration=286, speed=3.5, avg_hr=140),
            _lap_dict(1, LapType.RUN, distance=1000, duration=286, speed=3.5, avg_hr=142),
            _lap_dict(2, LapType.RUN, distance=1000, duration=285, speed=3.5, avg_hr=144),
            _lap_dict(3, LapType.RUN, distance=1000, duration=286, speed=3.5, avg_hr=145),
            _lap_dict(4, LapType.RUN, distance=1000, duration=286, speed=3.5, avg_hr=146),
            _lap_dict(5, LapType.RECOVERY, distance=200, duration=120, speed=1.67, avg_hr=135),
            _lap_dict(6, LapType.RUN, distance=1000, duration=286, speed=3.5, avg_hr=143),
            _lap_dict(7, LapType.RUN, distance=1000, duration=285, speed=3.5, avg_hr=145),
            _lap_dict(8, LapType.RUN, distance=1000, duration=286, speed=3.5, avg_hr=147),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        interval_types = {
            RunType.SHORT_INTERVALS,
            RunType.LONG_INTERVALS,
            RunType.TIME_INTERVALS,
        }
        self.assertFalse(any(seg.run_type in interval_types for seg in segments))
        self.assertEqual(dominant, RunType.EASY)

    def test_single_lap_easy_run(self):
        # Easy run without automatic laps.
        laps = [
            _lap_dict(0, LapType.RUN, distance=14567, duration=4046, speed=3.6, avg_hr=144),
        ]
        processed = _processed(laps)
        segments, dominant = build_segments(processed)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].role, "work")

        self.assertEqual(dominant, RunType.EASY)


def _typed_segments(segments: list[Segment]) -> list[tuple]:
    """(role, run type) of each segment but the breaks."""
    return [(seg.role, seg.run_type) for seg in segments if seg.role != "break"]


class TestWorkSegmentHeartRate(unittest.TestCase):
    """Which HR zone times a work segment is classified by."""

    bounds = (120, 140, 160, 180)

    def test_a_lone_work_segment_is_classified_by_the_activity_zone_times(self):
        # 400 s in zone 4: over half of the 600 s work segment, under half of the activity
        laps = [
            _lap_dict(0, LapType.RUN, duration=400, speed=2.5, avg_hr=120),
            _lap_dict(1, LapType.REST, distance=0, duration=120, speed=0, avg_hr=110),
            _lap_dict(2, LapType.RUN, speed=3.33),
            _lap_dict(3, LapType.RUN, speed=3.33),
        ]
        processed = _processed(
            laps, zone_times=ZoneTimes(zone2=520, zone4=400), zone_bounds=self.bounds
        )
        segments, dominant = build_segments(processed)

        self.assertEqual(
            _typed_segments(segments), [("preamble", RunType.EASY), ("work", RunType.TEMPO)]
        )
        self.assertEqual(dominant, RunType.TEMPO)

    def test_each_of_several_work_segments_is_classified_by_its_own_laps(self):
        laps = [
            _lap_dict(0, LapType.RUN, avg_hr=185),
            _lap_dict(1, LapType.RUN, avg_hr=185),
            _lap_dict(2, LapType.REST, distance=0, duration=120, speed=0, avg_hr=110),
            _lap_dict(3, LapType.RUN, avg_hr=140),
            _lap_dict(4, LapType.RUN, avg_hr=140),
        ]
        processed = _processed(laps, zone_times=ZoneTimes(zone5=1320), zone_bounds=self.bounds)
        segments, dominant = build_segments(processed)

        self.assertEqual(
            _typed_segments(segments), [("work", RunType.RACE), ("work", RunType.EASY)]
        )
        self.assertEqual(dominant, RunType.RACE)

    def test_a_lead_in_is_easy_when_its_zone_is_below_the_work_in_the_activity_zones(self):
        # 162 and 175 bpm share a default zone; in these bounds 162 is zone 4 and 175 is zone 5
        laps = [
            _lap_dict(0, LapType.RUN, distance=3000, duration=1200, speed=2.3, avg_hr=162),
            _lap_dict(1, LapType.RUN, distance=400, duration=90, speed=4.4, avg_hr=175),
            _lap_dict(2, LapType.RECOVERY, distance=200, duration=90, speed=2.0, avg_hr=130),
            _lap_dict(3, LapType.RUN, distance=400, duration=92, speed=4.3, avg_hr=175),
            _lap_dict(4, LapType.RECOVERY, distance=200, duration=88, speed=2.1, avg_hr=128),
        ]
        processed = _processed(laps, zone_bounds=(120, 145, 160, 170))
        segments, _ = build_segments(processed)

        self.assertEqual(segments[0].role, "preamble")
        self.assertEqual(segments[0].run_type, RunType.EASY)


if __name__ == "__main__":
    unittest.main()
