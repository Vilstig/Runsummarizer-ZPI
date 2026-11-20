"""normalize_garmin_activity and normalize_garmin_streams, from a FIT file built in memory."""

import pytest

from app.domain.enums import Provider, StreamType
from app.domain.models import ZoneTimes
from app.providers.fit.decode import decode_fit
from app.providers.garmin.normalizer import normalize_garmin_activity, normalize_garmin_streams
from tests.providers.fit.fit_builder import (
    START,
    build_fit,
    lap_mesg,
    record_mesg,
    running_fit,
    session_mesg,
)


def test_a_running_fit_file_becomes_an_activity():
    activity = normalize_garmin_activity(42, decode_fit(running_fit()), name="Morning Run")

    assert activity.key == "garmin_42"
    assert activity.source == Provider.GARMIN
    assert activity.name == "Morning Run"
    assert activity.start_time_utc == START
    assert activity.utc_offset == 7200
    assert activity.timezone is None
    assert activity.distance == pytest.approx(2000.0)
    assert activity.duration == pytest.approx(600.0)
    assert activity.speed == pytest.approx(3.333)
    assert (activity.avg_hr, activity.max_hr) == (152, 171)
    assert activity.elevation_gain == 12
    assert activity.zone_times == ZoneTimes()
    assert [lap.index for lap in activity.laps] == [0, 1]
    assert [lap.avg_hr for lap in activity.laps] == [148, 156]
    assert all(lap.type is None for lap in activity.laps)


@pytest.mark.parametrize("sub_sport", ["treadmill", "track", "trail"])
def test_running_sub_sports_are_activities(sub_sport):
    assert normalize_garmin_activity(1, decode_fit(running_fit(sub_sport=sub_sport))) is not None


def test_a_cycling_fit_file_is_no_activity():
    messages = decode_fit(running_fit(sport="cycling", sub_sport="road"))

    assert normalize_garmin_activity(1, messages) is None
    assert normalize_garmin_streams(messages) == {}


def test_a_device_writing_plain_speed_and_altitude_fields_gets_them_read():
    messages = decode_fit(
        build_fit(
            sessions=(session_mesg(avg_speed=3.1),),
            laps=(lap_mesg(0, avg_speed=3.2),),
            records=(record_mesg(0, speed=3.3, altitude=101.4),),
        )
    )

    activity = normalize_garmin_activity(1, messages)
    streams = normalize_garmin_streams(messages)

    assert activity.speed == pytest.approx(3.1)
    assert activity.laps[0].speed == pytest.approx(3.2)
    assert streams[StreamType.VELOCITY] == pytest.approx([3.3])
    assert streams[StreamType.ALTITUDE] == pytest.approx([101.4])


def test_the_running_session_gives_the_streams():
    streams = normalize_garmin_streams(decode_fit(running_fit()))

    assert streams[StreamType.TIME] == [0, 1]
    assert streams[StreamType.HEARTRATE] == [140, 140]
    assert streams[StreamType.VELOCITY] == pytest.approx([3.2, 3.3])
    assert StreamType.ALTITUDE not in streams


def test_the_normalized_activity_prefers_the_given_device_name():
    messages = decode_fit(running_fit(file_id={"product_name": "Forerunner 265"}))

    named = normalize_garmin_activity(1, messages, device_name="Forerunner 965")
    unnamed = normalize_garmin_activity(1, messages)

    assert named.device_name == "Forerunner 965"
    assert unnamed.device_name == "Forerunner 265"
