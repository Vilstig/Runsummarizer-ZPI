"""Building an imported activity from a provider's normalized one: HR-zone bounds and
times, lap classification, segmentation and the summary.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.config.loader import CONFIG
from app.domain.enums import StreamType
from app.domain.models import (
    Activity,
    ActivityRecord,
    HeartRateZonesRecord,
    Summary,
    ZoneBounds,
    ZoneTimes,
)
from app.ml.classifier import classify_laps
from app.providers.base import NormalizedActivity
from app.summaries.hr_zones import (
    bounds_in_effect,
    default_zone_bounds,
    time_in_zones,
    whole_bpm,
)
from app.summaries.segmentation import segment_activity
from app.summaries.summary import summarize

HR_ZONE_MAX_SAMPLE_GAP_S = CONFIG.get("HR_ZONE_MAX_SAMPLE_GAP_SECONDS", 10)
DEFAULT_ZONE_BOUNDS = whole_bpm(default_zone_bounds(int(CONFIG.get("MAX_HR", 200))))


@dataclass(frozen=True)
class ImportedActivity:
    """An activity built from a provider payload, as ``activities.save`` takes it."""

    record: ActivityRecord
    raw_payload: dict  # the provider's activity, as it sent it
    payload_kind: str  # activity_raw_payloads.payload_kind
    streams: dict  # {stream type: samples}


def build_import(
    normalized: NormalizedActivity, user_id: str, hr_zones: Sequence[HeartRateZonesRecord]
) -> ImportedActivity:
    """The user's activity, built from ``normalized``.

    The HR-zone times are counted in the zones of ``hr_zones``, the user's zone history,
    in effect at the activity's start, or in ``DEFAULT_ZONE_BOUNDS`` when it is empty.
    CPU-bound (the classifier): callers run it in a worker thread. A classifier or
    summary failure raises.
    """
    streams = normalized.streams
    activity = normalized.activity
    bounds = bounds_in_effect(hr_zones, activity.start_time_utc, default=DEFAULT_ZONE_BOUNDS)
    activity = replace(activity, zone_times=_zone_times(streams, bounds), zone_bounds=bounds)
    activity, summary = _classify(activity)
    return ImportedActivity(
        record=ActivityRecord(user_id=user_id, activity=activity, summary=summary),
        raw_payload=normalized.stored_payload,
        payload_kind=normalized.payload_kind,
        streams=streams,
    )


def _classify(activity: Activity) -> tuple[Activity, Summary]:
    """The classified and segmented activity, and its summary.

    An activity without laps has nothing to classify: it is kept as it is, with an
    empty summary. With laps, a classifier or summary failure raises.
    """
    if not activity.laps:
        return activity, summarize(activity)
    activity = segment_activity(classify_laps(activity))
    return activity, summarize(activity)


def _zone_times(streams: dict, bounds: ZoneBounds) -> ZoneTimes:
    """Seconds in each HR zone of ``bounds``, from the normalized ``streams``' ``time`` and
    ``heartrate`` (see ``time_in_zones``); zero without them.
    """
    return time_in_zones(
        streams.get(StreamType.HEARTRATE, []),
        streams.get(StreamType.TIME, []),
        bounds=bounds,
        max_gap_s=HR_ZONE_MAX_SAMPLE_GAP_S,
    )
