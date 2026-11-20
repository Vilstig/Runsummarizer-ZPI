"""HR zones: zone of a heart rate, and seconds per zone from aligned heart-rate and time
streams or from laps."""

from dataclasses import astuple, replace
from datetime import UTC, datetime

from app.domain.models import HeartRateZones, HeartRateZonesRecord, ZoneTimes
from app.summaries.hr_zones import (
    bounds_in_effect,
    default_zone_bounds,
    hr_zone,
    lap_zone_times,
    time_in_zones,
    whole_bpm,
    zone_bounds,
    zones_in_effect,
)
from tests.db.builders import make_lap

BOUNDS = (120, 140, 160, 180)  # zones 2-5 start here, in bpm
MAX_GAP_S = 10


def zones(heartrate: list, time: list) -> ZoneTimes:
    return time_in_zones(heartrate, time, bounds=BOUNDS, max_gap_s=MAX_GAP_S)


def test_default_bounds_are_fractions_of_max_hr():
    assert default_zone_bounds(200) == (120, 140, 160, 180)


def test_whole_bpm_rounds_bounds_up():
    assert whole_bpm(default_zone_bounds(199)) == (120, 140, 160, 180)


def test_whole_bpm_keeps_whole_bounds():
    assert whole_bpm(default_zone_bounds(190)) == (114, 133, 152, 171)


def test_a_heart_rate_on_a_bound_is_in_the_zone_it_starts():
    assert [hr_zone(hr, BOUNDS) for hr in (119, 120, 140, 160, 180)] == [1, 2, 3, 4, 5]


def test_a_heart_rate_below_the_zone_2_bound_is_in_zone_1():
    assert hr_zone(40, BOUNDS) == 1


def test_the_time_to_the_next_sample_counts_toward_the_samples_zone():
    assert zones([110, 130, 150, 170, 190], [0, 1, 3, 6, 10]) == ZoneTimes(
        zone1=1.0, zone2=2.0, zone3=3.0, zone4=4.0, zone5=0.0
    )


def test_a_gap_longer_than_the_limit_is_left_out():
    assert zones([150, 150, 150], [0, 1, 1 + MAX_GAP_S + 1]).zone3 == 1.0


def test_a_gap_of_exactly_the_limit_counts():
    assert zones([150, 150], [0, MAX_GAP_S]).zone3 == MAX_GAP_S


def test_the_last_sample_adds_nothing():
    assert not any(astuple(zones([190], [0])))


def test_missing_streams_give_zero_in_every_zone():
    assert zones([], []) == ZoneTimes()


def test_misaligned_streams_give_zero_in_every_zone():
    assert not any(astuple(zones([150, 150, 150], [0, 1])))


def test_each_lap_counts_in_the_zone_of_its_average_heart_rate():
    laps = [
        make_lap(1, duration=300.0, avg_hr=150.0),
        make_lap(2, duration=200.0, avg_hr=185.0),
        make_lap(3, duration=100.0, avg_hr=155.0),
    ]

    assert lap_zone_times(laps, BOUNDS) == ZoneTimes(zone3=400.0, zone5=200.0)


def test_a_lap_without_heart_rate_counts_in_no_zone():
    laps = [make_lap(1, duration=300.0, avg_hr=150.0), replace(make_lap(2), avg_hr=None)]

    assert lap_zone_times(laps, BOUNDS) == ZoneTimes(zone3=300.0)


def test_user_zone_bounds_start_at_zone_2():
    zones = HeartRateZones(
        zone1_bpm=100, zone2_bpm=120, zone3_bpm=140, zone4_bpm=160, zone5_bpm=175
    )
    assert zone_bounds(zones) == (120, 140, 160, 175)


def _zones(zone1_bpm: int) -> HeartRateZones:
    return HeartRateZones(
        zone1_bpm=zone1_bpm,
        zone2_bpm=zone1_bpm + 20,
        zone3_bpm=zone1_bpm + 40,
        zone4_bpm=zone1_bpm + 60,
        zone5_bpm=zone1_bpm + 75,
    )


OCT_1 = datetime(2026, 10, 1, tzinfo=UTC)
OCT_10 = datetime(2026, 10, 10, tzinfo=UTC)
HISTORY = [
    HeartRateZonesRecord(valid_from=OCT_1, zones=_zones(100)),
    HeartRateZonesRecord(valid_from=OCT_10, zones=_zones(105)),
]


def test_zones_in_effect_are_the_latest_record_valid_from_before():
    assert zones_in_effect(HISTORY, datetime(2026, 10, 5, tzinfo=UTC)) == _zones(100)
    assert zones_in_effect(HISTORY, datetime(2026, 10, 20, tzinfo=UTC)) == _zones(105)


def test_a_record_is_in_effect_from_its_valid_from():
    assert zones_in_effect(HISTORY, OCT_10) == _zones(105)


def test_before_every_record_the_oldest_is_in_effect():
    assert zones_in_effect(HISTORY, datetime(2024, 5, 1, tzinfo=UTC)) == _zones(100)


def test_the_order_of_the_history_does_not_matter():
    assert zones_in_effect(HISTORY[::-1], datetime(2026, 10, 5, tzinfo=UTC)) == _zones(100)
    assert zones_in_effect(HISTORY[::-1], datetime(2024, 5, 1, tzinfo=UTC)) == _zones(100)


def test_without_records_no_zones_are_in_effect():
    assert zones_in_effect([], OCT_1) is None


def test_bounds_in_effect_are_those_of_the_zones_in_effect():
    at = datetime(2026, 10, 5, tzinfo=UTC)
    assert bounds_in_effect(HISTORY, at, default=BOUNDS) == (120, 140, 160, 175)


def test_without_records_the_default_bounds_are_in_effect():
    assert bounds_in_effect([], OCT_1, default=BOUNDS) == BOUNDS
