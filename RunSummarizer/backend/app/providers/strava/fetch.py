"""Fetching a single Strava activity's raw payload."""

import logging
import time

from app.core.clock import elapsed_ms
from app.providers.strava.client import StravaClient
from app.providers.strava.errors import StravaNotFoundError
from app.providers.strava.normalizer import PAYLOAD_FORMAT, STRAVA_STREAM_KEYS

logger = logging.getLogger(__name__)


async def fetch_strava_payload(client: StravaClient, activity_id: int) -> dict | None:
    """The raw payload for the Strava activity ``activity_id``, or None if it is not a Run.

    The payload is plain JSON, ``{"format": PAYLOAD_FORMAT, "detail": ..., "streams":
    {...}}``:

    - ``detail``: Strava's ``GET /activities/{id}`` response, laps included;
    - ``streams``: ``{key: samples}`` for each stream in ``STRAVA_STREAM_KEYS`` the
      activity has, under Strava's keys; empty for an activity without stream data.

    An activity that is not a Run costs one call (the detail); a Run costs two. A 404 on
    the streams means the activity has no stream data (e.g. it was entered by hand), and
    gives empty streams. Any other error, from either call, propagates as
    ``StravaClient`` raises it.
    """
    t0 = time.perf_counter()
    detail = await client.get_activity_detail(activity_id)
    logger.debug("strava activity %s: detail %.0fms", activity_id, elapsed_ms(t0))
    if detail.get("type") != "Run":
        return None

    t0 = time.perf_counter()
    try:
        streams = await client.get_activity_streams(activity_id, STRAVA_STREAM_KEYS.values())
    except StravaNotFoundError:
        streams = {}
    logger.debug("strava activity %s: streams %.0fms", activity_id, elapsed_ms(t0))
    return {"format": PAYLOAD_FORMAT, "detail": detail, "streams": streams}
