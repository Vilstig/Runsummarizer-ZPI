"""
Translates an Intervals.icu activity and its FIT file into a ``NormalizedActivity``, over
the shared FIT module.
"""

import base64
import gzip
from datetime import datetime

from app.domain.enums import Provider
from app.providers.base import NormalizedActivity
from app.providers.fit.decode import FitMessages, decode_fit
from app.providers.fit.normalize import normalize_fit_activity, normalize_fit_streams
from app.providers.fit.session import utc_offset as fit_utc_offset
from app.providers.intervals.activity_keys import intervals_activity_key

# The "format" tag of the payloads the importer fetches: {"activity": ..., "file": ...}
PAYLOAD_FORMAT = "intervals_v1"
PAYLOAD_KIND = "intervals_activity"  # activity_raw_payloads.payload_kind of the stored activity

# Run types the app imports. Strava stubs carry no type at all, and are dropped by the
# same check.
RUN_TYPES = {"Run", "TrailRun"}

GZIP_MAGIC = b"\x1f\x8b"


def build_payload(activity: dict, *, file_source: str, file: bytes) -> dict:
    """The raw payload for an Intervals.icu activity: ``activity`` (a ``GET
    /activity/{id}`` response) and its ``file``, gzip-compressed and base64-encoded.

    ``file_source`` is ``"original"`` for the athlete's uploaded file, read only when it
    is already FIT, or ``"generated"`` for the ``/fit-file`` fallback used for GPX and TCX
    originals and for activities without an original file.
    """
    return {
        "format": PAYLOAD_FORMAT,
        "activity": activity,
        "file_source": file_source,
        "file": base64.b64encode(file).decode("ascii"),
    }


def _decoded_file(payload: dict) -> bytes:
    """The payload's FIT file, gunzipped when it is gzip-compressed."""
    data = base64.b64decode(payload["file"])
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def _utc_offset(activity: dict, messages: FitMessages) -> int:
    """Seconds east of UTC the activity was recorded at, to the whole minute: from
    ``start_date_local`` minus ``start_date``, falling back to the FIT activity message
    when either is missing or unreadable.
    """
    try:
        local = datetime.fromisoformat(activity["start_date_local"]).replace(tzinfo=None)
        utc = datetime.fromisoformat(activity["start_date"]).replace(tzinfo=None)
    except (KeyError, ValueError):
        return fit_utc_offset(messages)
    return round((local - utc).total_seconds() / 60) * 60


def normalize_intervals_payload(payload: dict) -> NormalizedActivity | None:
    """The activity of a ``build_payload`` payload, its FIT file decoded through the
    shared FIT module; None when the file has no running session.

    The activity is kept as the stored payload, under ``PAYLOAD_KIND``.
    """
    activity = payload["activity"]
    messages = decode_fit(_decoded_file(payload))
    built = normalize_fit_activity(
        messages,
        key=intervals_activity_key(activity["id"]),
        source=Provider.INTERVALS,
        name=activity.get("name"),
        timezone=activity.get("timezone"),
        utc_offset=_utc_offset(activity, messages),
    )
    if built is None:
        return None
    return NormalizedActivity(
        activity=built,
        streams=normalize_fit_streams(messages),
        payload_kind=PAYLOAD_KIND,
        stored_payload=activity,
    )
