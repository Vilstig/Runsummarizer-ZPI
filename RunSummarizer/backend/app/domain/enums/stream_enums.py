from enum import StrEnum


class StreamType(StrEnum):
    """A sample stream of an activity, as the app names it."""

    TIME = "time"  # seconds since the start
    DISTANCE = "distance"  # metres
    HEARTRATE = "heartrate"  # bpm
    VELOCITY = "velocity"  # m/s
    ALTITUDE = "altitude"  # metres
