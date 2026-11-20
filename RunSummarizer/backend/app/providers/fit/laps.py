from app.domain.models import Lap


def normalize_laps(laps: list[dict]) -> list[Lap]:
    """The ``Lap`` of each FIT lap message, indexed in order from 0, not yet classified.

    The speed is ``enhanced_avg_speed``, which the decoder fills from ``avg_speed`` when
    the device wrote only that.
    """
    return [
        Lap(
            index=index,
            distance=lap.get("total_distance"),
            duration=lap.get("total_timer_time"),
            speed=lap.get("enhanced_avg_speed"),
            avg_hr=lap.get("avg_heart_rate"),
            max_hr=lap.get("max_heart_rate"),
            elevation_gain=lap.get("total_ascent"),
        )
        for index, lap in enumerate(laps)
    ]
