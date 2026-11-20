"""
Translates raw Strava data into an ``Activity`` and the app's streams.

Normalized streams: { StreamType: samples }, the samples aligned by index; a stream the
activity lacks is left out.
"""

from datetime import datetime

from app.domain.enums import Provider, StreamType
from app.domain.models import Activity, Lap, ZoneTimes
from app.providers.strava.activity_keys import strava_activity_key

# The "format" tag of the payloads the importer fetches: {"detail": ..., "streams": ...}
PAYLOAD_FORMAT = "strava_v1"
PAYLOAD_KIND = "strava_detail"  # activity_raw_payloads.payload_kind of the stored detail

# Strava's key for each stream, as GET /activities/{id}/streams takes and returns it
STRAVA_STREAM_KEYS = {
    StreamType.TIME: "time",
    StreamType.DISTANCE: "distance",
    StreamType.HEARTRATE: "heartrate",
    StreamType.VELOCITY: "velocity_smooth",
    StreamType.ALTITUDE: "altitude",
}


def normalize_strava_streams(strava_streams: dict) -> dict:
    """The normalized streams for Strava's ``{key: samples}``; keys it doesn't name a
    stream for are dropped.
    """
    return {
        stream_type: strava_streams[key]
        for stream_type, key in STRAVA_STREAM_KEYS.items()
        if key in strava_streams
    }


def normalize_strava_activity(activity: dict, laps: list) -> Activity:
    """The ``Activity`` of a raw Strava activity and its laps, the laps not yet classified
    and the HR-zone times zero.
    """
    return Activity(
        key=strava_activity_key(activity.get("id", "")),
        source=Provider.STRAVA,
        name=activity.get("name"),
        start_time_utc=datetime.fromisoformat(activity["start_date"]),
        utc_offset=int(activity["utc_offset"]),
        timezone=activity.get("timezone"),
        distance=activity.get("distance"),
        duration=activity.get("moving_time"),
        speed=activity.get("average_speed") or 0,
        avg_hr=activity.get("average_heartrate"),
        max_hr=activity.get("max_heartrate"),
        elevation_gain=activity.get("total_elevation_gain"),
        zone_times=ZoneTimes(),
        laps=[_normalize_strava_lap(lap, i) for i, lap in enumerate(laps)],
    )


def _normalize_strava_lap(lap: dict, fallback_index: int) -> Lap:
    return Lap(
        index=lap.get("lap_index", fallback_index),
        distance=lap.get("distance"),
        duration=lap.get("moving_time"),
        speed=lap.get("average_speed"),
        avg_hr=lap.get("average_heartrate"),
        max_hr=lap.get("max_heartrate"),
        elevation_gain=lap.get("total_elevation_gain"),
    )
