"""The keys Garmin activities are stored under, as in ``activities.activity_key``."""


def garmin_activity_key(activity_id: int | str) -> str:
    """The key of the Garmin activity ``activity_id``: ``garmin_<id>``."""
    return f"garmin_{activity_id}"


def garmin_activity_id(activity_key: str) -> int:
    """The Garmin activity ID in a ``garmin_activity_key``."""
    return int(activity_key.removeprefix("garmin_"))
