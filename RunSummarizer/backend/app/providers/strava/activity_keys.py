"""The keys activities are stored under, as in ``activities.activity_key``."""


def strava_activity_key(activity_id: int | str) -> str:
    """The key of the Strava activity ``activity_id``: ``strava_<id>``."""
    return f"strava_{activity_id}"


def strava_activity_id(activity_key: str) -> int:
    """The Strava activity ID in a ``strava_activity_key``."""
    return int(activity_key.removeprefix("strava_"))
