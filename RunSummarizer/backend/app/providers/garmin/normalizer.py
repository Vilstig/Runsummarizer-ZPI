"""
Translates a decoded Garmin FIT activity file into an ``Activity`` and the app's streams,
over the shared FIT module.
"""

from app.domain.enums import Provider
from app.domain.models import Activity
from app.providers.fit.decode import FitMessages
from app.providers.fit.device import product_name
from app.providers.fit.normalize import normalize_fit_activity, normalize_fit_streams
from app.providers.fit.session import utc_offset
from app.providers.garmin.activity_keys import garmin_activity_key


def normalize_garmin_activity(
    activity_id: int | str,
    messages: FitMessages,
    *,
    name: str | None = None,
    device_name: str | None = None,
) -> Activity | None:
    """The ``Activity`` of the Garmin activity ``activity_id`` from its FIT file's
    ``messages``, the laps not yet classified and the HR-zone times zero; None when the
    file has no running session.

    FIT files carry no time zone name, so ``timezone`` is None. The device is
    ``device_name``, else the file's ``product_name``. Raises ``InvalidFitFileError`` when
    the session has no start time.
    """
    return normalize_fit_activity(
        messages,
        key=garmin_activity_key(activity_id),
        source=Provider.GARMIN,
        name=name,
        timezone=None,
        utc_offset=utc_offset(messages),
        device_name=device_name or product_name(messages),
    )


def normalize_garmin_streams(messages: FitMessages) -> dict:
    """The normalized streams of the FIT file's running session, time counted from its
    start; empty when it has none.
    """
    return normalize_fit_streams(messages)
