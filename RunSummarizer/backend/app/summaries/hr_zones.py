import math
from collections.abc import Sequence
from datetime import datetime

from app.domain.models import HeartRateZones, HeartRateZonesRecord, Lap, ZoneBounds, ZoneTimes

DEFAULT_ZONE_FRACTIONS = (0.60, 0.70, 0.80, 0.90)  # zones 2-5 start at these fractions of max HR
HR_ZONES = range(1, 6)


def default_zone_bounds(max_hr: float) -> ZoneBounds:
    """Zone bounds at ``DEFAULT_ZONE_FRACTIONS`` of ``max_hr``."""
    return tuple(max_hr * fraction for fraction in DEFAULT_ZONE_FRACTIONS)


def whole_bpm(bounds: ZoneBounds) -> ZoneBounds:
    """``bounds`` rounded up to whole bpm: a whole-bpm heart rate stays in the same zone."""
    # round() first, so that float error just above a whole bpm doesn't round up past it
    return tuple(math.ceil(round(bound, 6)) for bound in bounds)


def zone_bounds(zones: HeartRateZones) -> ZoneBounds:
    """Bounds of the user's ``zones``; heart rate below ``zone2_bpm`` is zone 1."""
    return (zones.zone2_bpm, zones.zone3_bpm, zones.zone4_bpm, zones.zone5_bpm)


def zones_in_effect(history: Sequence[HeartRateZonesRecord], at: datetime) -> HeartRateZones | None:
    """Zones of the latest record valid from ``at`` or earlier, or of the oldest record
    when ``at`` is before every record; None for an empty ``history``.
    """
    if not history:
        return None
    started = [record for record in history if record.valid_from <= at]
    if started:
        return max(started, key=lambda record: record.valid_from).zones
    return min(history, key=lambda record: record.valid_from).zones


def bounds_in_effect(
    history: Sequence[HeartRateZonesRecord], at: datetime, *, default: ZoneBounds
) -> ZoneBounds:
    """Bounds of the zones in effect at ``at`` (see ``zones_in_effect``), or ``default``
    for an empty ``history``.
    """
    zones = zones_in_effect(history, at)
    return default if zones is None else zone_bounds(zones)


def hr_zone(hr: float, bounds: ZoneBounds) -> int:
    """Heart-rate zone (1-5) of a heart rate."""
    return 1 + sum(hr >= bound for bound in bounds)


def time_in_zones(
    heartrate: list[float], time: list[float], *, bounds: ZoneBounds, max_gap_s: float
) -> ZoneTimes:
    """Seconds spent in each HR zone.

    ``heartrate`` and ``time`` (seconds since the start) are aligned stream samples. The
    time to the next sample counts toward the zone of the sample's heart rate; a gap
    longer than ``max_gap_s`` is time the watch was stopped and doesn't count. Missing
    or misaligned streams give zero in every zone.
    """
    seconds = dict.fromkeys(HR_ZONES, 0.0)
    if len(heartrate) == len(time):
        for i in range(len(time) - 1):
            gap = time[i + 1] - time[i]
            if gap <= max_gap_s:
                seconds[hr_zone(heartrate[i], bounds)] += gap
    return ZoneTimes(*(round(total, 1) for total in seconds.values()))


def lap_zone_times(laps: Sequence[Lap], bounds: ZoneBounds) -> ZoneTimes:
    """Seconds spent in each HR zone, each lap's duration counted in the zone of its
    average heart rate; a lap without heart rate counts in none."""
    seconds = dict.fromkeys(HR_ZONES, 0.0)
    for lap in laps:
        if lap.avg_hr:
            seconds[hr_zone(lap.avg_hr, bounds)] += lap.duration or 0
    return ZoneTimes(*seconds.values())
