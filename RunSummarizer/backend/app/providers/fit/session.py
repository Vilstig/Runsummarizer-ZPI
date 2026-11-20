"""A FIT activity's running session, and the laps, samples and UTC offset that go with it."""

from datetime import datetime

from garmin_fit_sdk import FIT_EPOCH_S

from app.providers.fit.decode import FitMessages
from app.providers.fit.errors import InvalidFitFileError

RUNNING = "running"  # FIT sport of every running activity; sub_sport tells treadmill, trail, …


def running_session(messages: FitMessages) -> dict | None:
    """The first session whose sport is running, whatever its sub-sport; None if none is."""
    return next((session for session in messages.sessions if session.get("sport") == RUNNING), None)


def sub_sport(session: dict) -> str | None:
    """The session's FIT sub-sport, e.g. 'generic', 'treadmill', 'trail', 'track'."""
    return session.get("sub_sport")


def start_time(session: dict) -> datetime:
    """When the session started, timezone-aware in UTC.

    Raises ``InvalidFitFileError`` when the session has no start time.
    """
    try:
        return session["start_time"]
    except KeyError as exc:
        raise InvalidFitFileError("The FIT session has no start time") from exc


def session_laps(messages: FitMessages, session: dict) -> list[dict]:
    """The laps of ``session``: those its ``first_lap_index`` and ``num_laps`` name, or
    every lap when it doesn't name them.
    """
    first = session.get("first_lap_index")
    count = session.get("num_laps")
    if first is None or count is None:
        return list(messages.laps)
    return list(messages.laps[first : first + count])


def session_records(messages: FitMessages, session: dict) -> list[dict]:
    """The timestamped samples from the session's start up to the next session's start,
    or to the end of the file for the last session.

    The session's own ``timestamp`` isn't used as its end: some devices, e.g. the
    Forerunner 255, set it to the start time.
    """
    start = start_time(session)
    end = min(
        (
            other["start_time"]
            for other in messages.sessions
            if other.get("start_time") is not None and other["start_time"] > start
        ),
        default=None,
    )
    return [
        record
        for record in messages.records
        if record.get("timestamp") is not None
        and record["timestamp"] >= start
        and (end is None or record["timestamp"] < end)
    ]


def utc_offset(messages: FitMessages) -> int:
    """Seconds east of UTC the activity was recorded at, to the whole minute, from the
    activity message's local and UTC timestamps; 0 when it lacks either.
    """
    activity = messages.activity
    if activity is None or "local_timestamp" not in activity or "timestamp" not in activity:
        return 0
    local = activity["local_timestamp"] + FIT_EPOCH_S
    return round((local - activity["timestamp"].timestamp()) / 60) * 60
