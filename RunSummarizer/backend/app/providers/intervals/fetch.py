"""Fetching a single Intervals.icu activity's raw payload."""

import logging

from app.providers.intervals.client import IntervalsClient
from app.providers.intervals.errors import IntervalsNotFoundError
from app.providers.intervals.normalizer import RUN_TYPES, build_payload

logger = logging.getLogger(__name__)


def _is_stub(activity: dict) -> bool:
    """Whether ``activity`` is a Strava-sourced activity the API gives out only as a stub,
    without a type or figures (§1.4)."""
    return "_note" in activity or activity.get("source") == "STRAVA"


async def fetch_intervals_payload(client: IntervalsClient, activity_id: str) -> dict | None:
    """The raw payload for the Intervals.icu activity ``activity_id``, or None when it is
    not one to import: a Strava stub or not a run.

    The athlete's original file is downloaded when it is already FIT. A GPX or TCX
    original, or no original at all (e.g. a manual entry), falls back to the FIT file
    Intervals.icu generates, whose laps are its own detected intervals rather than the
    device's. A 404 on the file means it has since disappeared, and also gives None.
    """
    activity = await client.get_activity(activity_id)
    if _is_stub(activity) or activity.get("type") not in RUN_TYPES:
        return None

    file_source = "original" if activity.get("file_type") == "fit" else "generated"
    try:
        file = (
            await client.get_activity_file(activity_id)
            if file_source == "original"
            else await client.get_activity_fit_file(activity_id)
        )
    except IntervalsNotFoundError:
        return None

    return build_payload(activity, file_source=file_source, file=file)
