"""normalize_streams: FIT record messages to the app's streams."""

from app.domain.enums import StreamType
from app.providers.fit.streams import fill_gaps, normalize_streams, record_samples
from tests.providers.fit.fit_builder import START, record_mesg


def test_record_fields_become_streams():
    records = [
        record_mesg(0, distance=0.0, heart_rate=140, enhanced_speed=3.0, enhanced_altitude=100.0),
        record_mesg(2, distance=6.0, heart_rate=141, enhanced_speed=3.1, enhanced_altitude=100.2),
    ]

    assert normalize_streams(records, start=START) == {
        StreamType.TIME: [0, 2],
        StreamType.DISTANCE: [0.0, 6.0],
        StreamType.HEARTRATE: [140, 141],
        StreamType.VELOCITY: [3.0, 3.1],
        StreamType.ALTITUDE: [100.0, 100.2],
    }


def test_a_stream_no_record_has_is_left_out():
    streams = normalize_streams([record_mesg(0, heart_rate=140)], start=START)
    assert set(streams) == {StreamType.TIME, StreamType.HEARTRATE}


def test_missing_samples_are_filled_from_neighbours():
    records = [
        record_mesg(0),
        record_mesg(1, heart_rate=140),
        record_mesg(2),
        record_mesg(3, heart_rate=142),
    ]
    assert normalize_streams(records, start=START)[StreamType.HEARTRATE] == [140, 140, 140, 142]


def test_record_samples_keep_the_gaps():
    records = [record_mesg(0), record_mesg(1, heart_rate=140)]
    assert record_samples(records, start=START)[StreamType.HEARTRATE] == [None, 140]


def test_records_without_a_timestamp_are_left_out():
    records = [record_mesg(0, heart_rate=140), {"heart_rate": 150}]
    assert normalize_streams(records, start=START)[StreamType.HEARTRATE] == [140]


def test_no_records_are_no_streams():
    assert normalize_streams([], start=START) == {}


def test_fill_gaps():
    assert fill_gaps([None, 1, None, None, 4, None]) == [1, 1, 1, 1, 4, 4]
    assert fill_gaps([None, None]) is None
    assert fill_gaps([]) is None
