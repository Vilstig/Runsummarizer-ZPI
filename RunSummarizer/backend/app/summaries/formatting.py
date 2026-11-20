"""Shared formatting helpers for summary generation."""

import math


def round_to_nearest_50(number):
    return round(number / 50) * 50


def round_to_nearest_100(number):
    return round(number / 100) * 100


def format_duration(seconds: float, *, decimals: int = 0) -> str:
    """``seconds`` as ``h:mm:ss``, e.g. ``1:02:05``, or ``m:ss`` under an hour, e.g.
    ``5:03`` and ``0:45``.

    The seconds are rounded to ``decimals`` places, halves up, e.g. ``1:18.5``.
    """
    factor = 10**decimals
    scaled = math.floor(seconds * factor + 0.5)  # in units of 1 / factor s
    minutes, secs = divmod(scaled, 60 * factor)
    hours, minutes = divmod(minutes, 60)
    width = 2 + (decimals + 1 if decimals else 0)  # two digits, then the point and decimals
    secs_text = f"{secs / factor:0{width}.{decimals}f}"
    if hours:
        return f"{hours}:{minutes:02d}:{secs_text}"
    return f"{minutes}:{secs_text}"


def pace_s_per_km(distance_m: float, duration_s: float) -> float:
    """Seconds per kilometre; 0 when the distance or the duration is 0."""
    if distance_m == 0 or duration_s == 0:
        return 0.0
    return (duration_s / distance_m) * 1000


def whole_seconds(seconds: float) -> int:
    """``seconds`` to the nearest whole second, halves rounded up."""
    return math.floor(seconds + 0.5)


def format_pace(seconds_per_km: float) -> str:
    """``m:ss /km`` of a pace in seconds per kilometre, to the nearest second."""
    return f"{format_duration(seconds_per_km)} /km"


def get_pace_str(distance_m: float, duration_s: float) -> str:
    return format_pace(pace_s_per_km(distance_m, duration_s))


def segment_stats(laps) -> dict:
    distance = sum(lap.distance or 0 for lap in laps)
    duration = sum(lap.duration or 0 for lap in laps)
    if duration > 0:
        avg_hr = int(sum((lap.avg_hr or 0) * (lap.duration or 0) for lap in laps) / duration)
    else:
        avg_hr = 0
    speed = distance / duration if duration > 0 else 0
    return {
        "distance": distance,
        "duration": duration,
        "avg_hr": avg_hr,
        "speed": speed,
        "distance_km": distance / 1000,
    }
