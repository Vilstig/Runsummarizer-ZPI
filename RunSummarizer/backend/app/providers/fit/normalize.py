"""
Translates a decoded FIT activity file into an ``Activity`` and the app's streams, for any
provider whose activity data is a FIT file.

Normalized streams: { StreamType: samples }, the samples aligned by index; a stream the
activity lacks is left out.
"""

from app.domain.enums import Provider
from app.domain.models import Activity, ZoneTimes
from app.providers.fit.decode import FitMessages
from app.providers.fit.laps import normalize_laps
from app.providers.fit.session import running_session, session_laps, session_records, start_time
from app.providers.fit.streams import normalize_streams


def normalize_fit_activity(
    messages: FitMessages,
    *,
    key: str,
    source: Provider,
    name: str | None,
    timezone: str | None,
    utc_offset: int,
    device_name: str | None = None,
) -> Activity | None:
    """The ``Activity`` of a FIT file's ``messages``, the laps not yet classified and the
    HR-zone times zero; None when the file has no running session.

    The duration is the timer time, pauses left out. ``key``, ``source``, ``name``,
    ``timezone``, ``utc_offset`` and ``device_name`` are the caller's, since none of them
    come from the FIT file itself in every provider's case. Raises ``InvalidFitFileError``
    when the session has no start time.
    """
    session = running_session(messages)
    if session is None:
        return None
    return Activity(
        key=key,
        source=source,
        name=name,
        start_time_utc=start_time(session),
        utc_offset=utc_offset,
        timezone=timezone,
        distance=session.get("total_distance"),
        duration=session.get("total_timer_time"),
        speed=session.get("enhanced_avg_speed") or 0,
        avg_hr=session.get("avg_heart_rate"),
        max_hr=session.get("max_heart_rate"),
        elevation_gain=session.get("total_ascent"),
        zone_times=ZoneTimes(),
        laps=normalize_laps(session_laps(messages, session)),
        device_name=device_name,
    )


def normalize_fit_streams(messages: FitMessages) -> dict:
    """The normalized streams of the FIT file's running session, time counted from its
    start; empty when it has none.
    """
    session = running_session(messages)
    if session is None:
        return {}
    return normalize_streams(session_records(messages, session), start=start_time(session))
