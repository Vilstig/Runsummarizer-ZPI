"""normalize_strava_streams: Strava's stream keys to the app's stream types."""

from app.domain.enums import StreamType
from app.providers.strava.normalizer import normalize_strava_streams


def test_strava_keys_become_stream_types():
    strava_streams = {
        "time": [0, 1],
        "distance": [0.0, 3.0],
        "heartrate": [140, 141],
        "velocity_smooth": [3.0, 3.1],
        "altitude": [100.0, 100.2],
    }

    assert normalize_strava_streams(strava_streams) == {
        StreamType.TIME: [0, 1],
        StreamType.DISTANCE: [0.0, 3.0],
        StreamType.HEARTRATE: [140, 141],
        StreamType.VELOCITY: [3.0, 3.1],
        StreamType.ALTITUDE: [100.0, 100.2],
    }


def test_missing_and_unknown_keys_are_left_out():
    assert normalize_strava_streams({"time": [0, 1], "cadence": [80, 81]}) == {
        StreamType.TIME: [0, 1]
    }
