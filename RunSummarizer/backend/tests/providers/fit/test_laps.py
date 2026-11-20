"""normalize_laps: FIT lap messages to the app's laps."""

from app.domain.models import Lap
from app.providers.fit.laps import normalize_laps


def test_lap_fields_map_to_the_lap():
    lap = {
        "total_distance": 1000.0,
        "total_timer_time": 300.0,
        "enhanced_avg_speed": 3.333,
        "avg_heart_rate": 150,
        "max_heart_rate": 162,
        "total_ascent": 4,
    }

    assert normalize_laps([lap]) == [
        Lap(
            index=0,
            distance=1000.0,
            duration=300.0,
            speed=3.333,
            avg_hr=150,
            max_hr=162,
            elevation_gain=4,
        )
    ]


def test_laps_are_indexed_in_order_and_missing_fields_are_none():
    laps = normalize_laps([{}, {"total_distance": 400.0}])

    assert [lap.index for lap in laps] == [0, 1]
    assert laps[0] == Lap(
        index=0,
        distance=None,
        duration=None,
        speed=None,
        avg_hr=None,
        max_hr=None,
        elevation_gain=None,
    )
