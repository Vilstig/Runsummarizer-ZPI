"""normalize_fit_activity and normalize_fit_streams, from a FIT file built in memory."""

import pytest

from app.domain.enums import Provider, StreamType
from app.domain.models import ZoneTimes
from app.providers.fit.decode import decode_fit
from app.providers.fit.normalize import normalize_fit_activity, normalize_fit_streams
from tests.providers.fit.fit_builder import (
    START,
    activity_mesg,
    build_fit,
    lap_mesg,
    record_mesg,
    session_mesg,
)


def running_fit(**session_fields) -> bytes:
    return build_fit(
        sessions=(
            session_mesg(
                total_distance=2000.0,
                total_timer_time=600.0,
                total_elapsed_time=630.0,
                enhanced_avg_speed=3.333,
                avg_heart_rate=152,
                max_heart_rate=171,
                total_ascent=12,
                first_lap_index=0,
                num_laps=2,
                **session_fields,
            ),
        ),
        laps=(
            lap_mesg(0, total_distance=1000.0, total_timer_time=290.0, avg_heart_rate=148),
            lap_mesg(300, total_distance=1000.0, total_timer_time=310.0, avg_heart_rate=156),
        ),
        records=(
            record_mesg(0, distance=0.0, heart_rate=140, enhanced_speed=3.2),
            record_mesg(1, distance=3.2, enhanced_speed=3.3),
        ),
        activity=activity_mesg(7200),
    )


def build(messages, **fields):
    return normalize_fit_activity(
        messages,
        key=fields.pop("key", "intervals_i1"),
        source=fields.pop("source", Provider.INTERVALS),
        name=fields.pop("name", "Morning Run"),
        timezone=fields.pop("timezone", "Europe/Warsaw"),
        utc_offset=fields.pop("utc_offset", 7200),
    )


def test_a_running_fit_file_becomes_an_activity():
    activity = build(decode_fit(running_fit()))

    assert activity.key == "intervals_i1"
    assert activity.source == Provider.INTERVALS
    assert activity.name == "Morning Run"
    assert activity.start_time_utc == START
    assert activity.utc_offset == 7200
    assert activity.timezone == "Europe/Warsaw"
    assert activity.distance == pytest.approx(2000.0)
    assert activity.duration == pytest.approx(600.0)
    assert activity.speed == pytest.approx(3.333)
    assert (activity.avg_hr, activity.max_hr) == (152, 171)
    assert activity.elevation_gain == 12
    assert activity.zone_times == ZoneTimes()
    assert [lap.index for lap in activity.laps] == [0, 1]
    assert [lap.avg_hr for lap in activity.laps] == [148, 156]
    assert all(lap.type is None for lap in activity.laps)


def test_the_caller_chooses_the_key_source_name_timezone_and_utc_offset():
    activity = build(
        decode_fit(running_fit()),
        key="garmin_42",
        source=Provider.GARMIN,
        name=None,
        timezone=None,
        utc_offset=0,
    )

    assert activity.key == "garmin_42"
    assert activity.source == Provider.GARMIN
    assert activity.name is None
    assert activity.timezone is None
    assert activity.utc_offset == 0


def test_a_file_without_a_running_session_is_no_activity():
    messages = decode_fit(running_fit(sport="cycling", sub_sport="road"))

    assert build(messages) is None
    assert normalize_fit_streams(messages) == {}


def test_the_running_session_gives_the_streams():
    streams = normalize_fit_streams(decode_fit(running_fit()))

    assert streams[StreamType.TIME] == [0, 1]
    assert streams[StreamType.HEARTRATE] == [140, 140]
    assert streams[StreamType.VELOCITY] == pytest.approx([3.2, 3.3])
    assert StreamType.ALTITUDE not in streams
