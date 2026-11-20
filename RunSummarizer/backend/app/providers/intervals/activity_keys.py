"""The keys activities are stored under, as in ``activities.activity_key``."""


def intervals_activity_key(activity_id: int | str) -> str:
    """The key of the Intervals.icu activity ``activity_id``, e.g. ``i55751783``:
    ``intervals_i55751783``.
    """
    return f"intervals_{activity_id}"


def intervals_activity_id(activity_key: str) -> str:
    """The Intervals.icu activity id (with its leading ``i``) in an
    ``intervals_activity_key``.
    """
    return activity_key.removeprefix("intervals_")
