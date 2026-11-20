"""Builders for the records the repository contract suite seeds."""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.domain.enums import LapType, Provider
from app.domain.models import (
    Activity,
    ActivityRecord,
    Lap,
    Summary,
    UserSegment,
    ZoneTimes,
)
from app.summaries.segmentation import segment_activity

# Start times carry an explicit offset, so a lexicographic sort and a chronological
# sort agree.
DEFAULT_START_TIME_LOCAL = "2026-01-31T16:34:18Z"


def make_lap(
    lap_index: int,
    *,
    type_id: LapType = LapType.RUN,
    distance: float = 1000.0,
    duration: float = 257.0,
    avg_hr: float = 139.3,
    max_hr: float = 150.0,
    elevation_gain: float = 3.0,
) -> Lap:
    return Lap(
        index=lap_index,
        type=LapType(type_id),
        distance=distance,
        duration=duration,
        speed=round(distance / duration, 2) if duration else 0.0,
        avg_hr=avg_hr,
        max_hr=max_hr,
        elevation_gain=elevation_gain,
    )


def make_run(
    activity_id: str,
    *,
    source: str = "strava",
    name: str = "Morning Run",
    start_time_local: str = DEFAULT_START_TIME_LOCAL,
    laps: Sequence[Lap] | None = None,
    user_segments: Sequence[UserSegment] | None = None,
    avg_hr: float | None = 139.3,
) -> Activity:
    """An activity of ``laps``, starting at ``start_time_local`` (ISO 8601, with its offset),
    segmented into ``user_segments`` when given, otherwise automatically."""
    laps = list(laps) if laps is not None else [make_lap(1), make_lap(2)]
    start = datetime.fromisoformat(start_time_local)
    distance = sum(lap.distance for lap in laps)
    duration = sum(lap.duration for lap in laps)
    activity = Activity(
        key=activity_id,
        source=Provider(source),
        name=name,
        start_time_utc=start.astimezone(UTC),
        utc_offset=int(start.utcoffset().total_seconds()),
        timezone=None,
        distance=distance,
        duration=duration,
        speed=round(distance / duration, 2) if duration else 0.0,
        avg_hr=avg_hr,
        max_hr=150.0,
        elevation_gain=None,
        zone_times=ZoneTimes(zone1=120.0, zone2=300.0, zone3=90.0, zone4=0.0, zone5=0.0),
        zone_bounds=(120, 140, 160, 180),
        laps=laps,
        user_segments=tuple(user_segments) if user_segments is not None else None,
    )
    return segment_activity(activity)


def make_activity(
    activity_id: str,
    *,
    user_id: str,
    summary: str = "5 km easy",
    **run,
) -> ActivityRecord:
    """A record of ``make_run(activity_id, **run)``, ready for
    ``AsyncActivityRepository.save``."""
    return ActivityRecord(
        user_id=user_id, activity=make_run(activity_id, **run), summary=text_summary(summary)
    )


def text_summary(text: str) -> Summary:
    """A summary of ``text``, not edited by the user."""
    return Summary(text=text)


def raw_payload_of(activity_id: str) -> dict:
    """The raw payload ``save_activity`` stores when given none."""
    return {"id": activity_id, "type": "Run"}
