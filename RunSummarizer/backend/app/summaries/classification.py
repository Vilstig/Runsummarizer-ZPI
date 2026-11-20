from statistics import median

from numpy import corrcoef, std

from app.domain.enums import LapType, RunType, SegmentRole
from app.domain.models import Lap, ZoneBounds, ZoneTimes
from app.summaries.hr_zones import lap_zone_times
from app.summaries.reps import LONG_REP_DISTANCE_M, are_interval_reps, rep_distance, run_stretches

# Share of a segment's time in zones 4 and 5 above which a steady segment is Tempo, or Race
# when zone 5 alone holds more than it.
HARD_SHARE = 0.5


def segment_zone_times(
    laps: list[Lap], zone_times: ZoneTimes, zone_bounds: ZoneBounds, *, work_segments: int
) -> ZoneTimes:
    """The HR zone times a work segment of ``laps`` is classified by: the activity's
    ``zone_times`` when it is the activity's only work segment, otherwise those of its own
    laps (see ``lap_zone_times``)."""
    if work_segments == 1:
        return zone_times
    return lap_zone_times(laps, zone_bounds)


def classify_segment(laps: list[Lap], zone_times: ZoneTimes, duration: float) -> RunType:
    """The run type of a segment of ``laps`` lasting ``duration`` seconds, ``zone_times``
    being its time in each HR zone (see ``segment_zone_times``)."""
    run_laps = [lap for lap in laps if lap.type == LapType.RUN]
    recovery_laps = [lap for lap in laps if lap.type in (LapType.RECOVERY, LapType.REST)]

    reps = [laps[first : last + 1] for first, last in run_stretches(laps)]

    if are_interval_reps(reps):
        if (
            median(rep_distance(rep) for rep in reps) > LONG_REP_DISTANCE_M
        ):  # median rep distance over the threshold, it's a long interval (eg. 4x2km, where each kilometer triggers a lap)
            return RunType.LONG_INTERVALS
        if (
            std([lap.duration for lap in run_laps]) == 0
        ):  # if the standard deviation of the duration of run laps is 0, it's a time interval (eg. 20x1min/1min)
            return RunType.TIME_INTERVALS

        return RunType.SHORT_INTERVALS  # otherwise, it's a short interval (eg. 20x300m/1min)

    if run_laps and not recovery_laps:
        if _is_progression(run_laps):
            return RunType.PROGRESSION_RUN
        hard_duration = duration * HARD_SHARE
        if zone_times.zone5 > hard_duration:
            return RunType.RACE
        if zone_times.zone4 + zone_times.zone5 > hard_duration:
            return RunType.TEMPO

    return RunType.EASY


def dominant_run_type(segments) -> RunType:
    work_segments = [
        seg
        for seg in segments
        if seg.role == SegmentRole.WORK
        and seg.run_type is not None
        and seg.run_type != RunType.EASY
    ]
    if not work_segments:
        for seg in segments:
            if seg.role != SegmentRole.BREAK and seg.run_type is not None:
                return seg.run_type
        return RunType.EASY

    return max(work_segments, key=lambda seg: sum(lap.duration or 0 for lap in seg.laps)).run_type


def _is_progression(run_laps: list[Lap]) -> bool:
    if (
        sum(lap.distance or 0 for lap in run_laps) < 6000
    ):  # distance has to be at least 6km in order to talk progression run
        return False

    first_2km_pace = _time_over_distance(run_laps, 2000) / 2  # s/km
    last_2km_pace = _time_over_distance(reversed(run_laps), 2000) / 2  # s/km
    if (
        first_2km_pace - last_2km_pace < 55
    ):  # last 2 km must average at least 55 s/km faster than the first 2 km
        return False

    speeds = [
        lap.speed for lap in run_laps if lap.speed and (lap.distance or 0) >= 500
    ]  # skips laps under 500 m, e.g. a partial last lap
    if len(speeds) < 4:
        return False
    r = corrcoef(range(len(speeds)), speeds)[0, 1]  # correlation of lap speed with lap order
    return bool(r > 0 and r**2 >= 0.7)  # speeds must sit close to a rising line (R² >= 0.7)


def _time_over_distance(laps, meters: float) -> float:
    time = 0.0  # s
    for lap in laps:
        if not lap.distance:
            continue
        covered = min(lap.distance, meters)
        time += (lap.duration or 0) * covered / lap.distance
        meters -= covered
        if meters <= 0:
            break
    return time
