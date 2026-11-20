from enum import StrEnum


class ActivitySortKey(StrEnum):
    """What an activity search orders its results by."""

    START_TIME = "startTime"
    DISTANCE = "distance"
    DURATION = "duration"
    PACE = "pace"  # ascending: fastest first
