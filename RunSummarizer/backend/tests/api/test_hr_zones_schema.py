"""HeartRateZoneResponse: an activity's seconds per HR zone, with the heart rates each zone
covers."""

from app.api.schemas.activities import HeartRateZoneResponse
from app.domain.models import ZoneTimes

TIMES = ZoneTimes(zone1=10.0, zone2=20.0, zone3=30.0, zone4=40.0, zone5=50.0)


def test_each_zone_runs_from_its_bound_to_1_bpm_below_the_next_ones():
    zones = HeartRateZoneResponse.list_from(TIMES, (121, 142, 158, 176))

    assert [zone.model_dump() for zone in zones] == [
        {"zone": 1, "minBpm": 0, "maxBpm": 120, "time": 10.0},
        {"zone": 2, "minBpm": 121, "maxBpm": 141, "time": 20.0},
        {"zone": 3, "minBpm": 142, "maxBpm": 157, "time": 30.0},
        {"zone": 4, "minBpm": 158, "maxBpm": 175, "time": 40.0},
        {"zone": 5, "minBpm": 176, "maxBpm": None, "time": 50.0},
    ]


def test_zones_of_unknown_bounds_have_null_bpm():
    zones = HeartRateZoneResponse.list_from(TIMES, None)

    assert [(zone.zone, zone.minBpm, zone.maxBpm, zone.time) for zone in zones] == [
        (1, None, None, 10.0),
        (2, None, None, 20.0),
        (3, None, None, 30.0),
        (4, None, None, 40.0),
        (5, None, None, 50.0),
    ]
