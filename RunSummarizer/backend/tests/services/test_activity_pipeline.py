import json
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx
import pytest

from app.domain.enums import Provider
from app.domain.models import (
    HeartRateZones,
    HeartRateZonesRecord,
    Summary,
    ZoneTimes,
)
from app.providers.strava.importer import StravaImporter
from app.services import activity_pipeline
from app.services.activity_pipeline import ImportedActivity
from tests.services.fakes import USER_HR_ZONES, run_payload, strava_run

USER_ID = "user-1"


def build(payload: dict, *, hr_zones: Sequence[HeartRateZonesRecord] = ()) -> ImportedActivity:
    """``build_import`` of a Strava payload, as the importer normalizes it."""
    normalized = StravaImporter().normalize(payload)
    return activity_pipeline.build_import(normalized, USER_ID, hr_zones)


def failing_classifier(activity):
    raise RuntimeError("model unavailable")


def test_build_makes_the_users_record_without_calling_the_provider(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("an HTTP request was sent")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    payload = run_payload(7)

    imported = build(payload)

    assert imported.record.activity.key == "strava_7"
    assert imported.record.user_id == USER_ID
    assert imported.record.activity.source == Provider.STRAVA
    assert imported.raw_payload == strava_run(7)
    assert imported.payload_kind == "strava_detail"
    assert imported.record.summary.text
    assert imported.record.activity.zone_times != ZoneTimes()
    assert payload == run_payload(7)


def test_build_keeps_the_normalized_streams():
    imported = build(run_payload(7))

    assert imported.streams == {
        "time": [0, 1, 2],
        "distance": [0.0, 3.0, 6.0],
        "heartrate": [140, 150, 160],
        "velocity": [3.0, 3.0, 3.0],
        "altitude": [100.0, 100.5, 101.0],
    }


def test_build_counts_heart_rate_zone_time_from_the_time_stream():
    # 100 bpm is zone 1 and 150 bpm zone 3; the 24 s gap is longer than the limit
    streams = {"time": [0, 4, 6, 30, 31], "heartrate": [100, 150, 150, 150, 150]}

    imported = build({"detail": strava_run(7), "streams": streams})

    assert imported.record.activity.zone_times == ZoneTimes(zone1=4.0, zone3=3.0)


def test_build_counts_heart_rate_zone_time_in_the_default_zones_without_user_zones():
    imported = build(run_payload(7))

    assert imported.record.activity.zone_times == ZoneTimes(zone3=2.0)
    assert imported.record.activity.zone_bounds == (120, 140, 160, 180)


def test_build_counts_heart_rate_zone_time_in_the_zones_in_effect_at_the_start():
    later_zones = HeartRateZones(
        zone1_bpm=80, zone2_bpm=90, zone3_bpm=100, zone4_bpm=110, zone5_bpm=120
    )
    hr_zones = [
        # the run starts on 2026-05-01
        HeartRateZonesRecord(valid_from=datetime(2026, 4, 1, tzinfo=UTC), zones=USER_HR_ZONES),
        HeartRateZonesRecord(valid_from=datetime(2026, 6, 1, tzinfo=UTC), zones=later_zones),
    ]

    imported = build(run_payload(7), hr_zones=hr_zones)

    assert imported.record.activity.zone_times == ZoneTimes(zone2=1.0, zone3=1.0)
    assert imported.record.activity.zone_bounds == (120, 145, 155, 175)


def test_build_counts_heart_rate_zone_time_in_the_oldest_zones_for_an_earlier_run():
    hr_zones = [
        HeartRateZonesRecord(valid_from=datetime(2026, 10, 1, tzinfo=UTC), zones=USER_HR_ZONES)
    ]

    imported = build(run_payload(7), hr_zones=hr_zones)

    assert imported.record.activity.zone_times == ZoneTimes(zone2=1.0, zone3=1.0)


def test_build_makes_the_same_record_from_a_json_round_tripped_payload():
    payload = run_payload(7)
    # jsonb doesn't keep key order; sort_keys changes it as storing the payload would
    stored = json.loads(json.dumps(payload, sort_keys=True))

    assert build(stored) == build(payload)


def test_build_raises_on_a_classifier_failure(monkeypatch):
    monkeypatch.setattr(activity_pipeline, "classify_laps", failing_classifier)

    with pytest.raises(RuntimeError, match="model unavailable"):
        build(run_payload(1))


def test_build_gives_empty_heart_rate_zones_without_stream_data():
    imported = build({"detail": strava_run(7), "streams": {}})

    assert imported.record.activity.zone_times == ZoneTimes()


def test_build_keeps_an_activity_without_laps_with_an_empty_summary(monkeypatch):
    monkeypatch.setattr(activity_pipeline, "classify_laps", failing_classifier)

    imported = build({"detail": strava_run(1, laps=0), "streams": {}})

    assert imported.record.summary == Summary(text="")
    assert imported.record.activity.laps == []
