from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.domain.enums import LapType, Provider, RunType, SegmentRole
from app.domain.models.hr_zones import ZoneBounds
from app.domain.models.summary import Summary


@dataclass
class Lap:
    index: int
    distance: float | None  # m
    duration: float | None  # s
    speed: float | None  # m/s
    avg_hr: float | None  # bpm
    max_hr: float | None  # bpm
    elevation_gain: float | None  # m
    type: LapType | None = None  # None until classified
    version: int = 0  # 0: as imported, 1: edited by the user

    def __add__(self, other: "Lap") -> "Lap":
        """The two laps as one, keeping this lap's index and version; both must be the same
        type."""
        if self.type != other.type:
            raise ValueError("Cant add laps of different types")

        distance = (self.distance or 0) + (other.distance or 0)
        return Lap(
            index=self.index,
            type=self.type,
            distance=distance,
            duration=(self.duration or 0) + (other.duration or 0),
            speed=(
                (
                    (self.speed or 0) * (self.distance or 0)
                    + (other.speed or 0) * (other.distance or 0)
                )
                / distance
                if distance > 0
                else 0
            ),
            avg_hr=(
                int(
                    (
                        (self.avg_hr or 0) * (self.distance or 0)
                        + (other.avg_hr or 0) * (other.distance or 0)
                    )
                    / distance
                )
                if distance > 0
                else 0
            ),
            max_hr=max(self.max_hr or 0, other.max_hr or 0),
            elevation_gain=(self.elevation_gain or 0) + (other.elevation_gain or 0),
            version=self.version,
        )


@dataclass(frozen=True)
class ZoneTimes:
    """Seconds spent in each HR zone."""

    zone1: float = 0
    zone2: float = 0
    zone3: float = 0
    zone4: float = 0
    zone5: float = 0

    def __getitem__(self, zone: int) -> float:
        """Seconds in ``zone`` (1-5)."""
        return getattr(self, f"zone{zone}")


@dataclass(frozen=True)
class SegmentStats:
    """A segment's figures, from the params its part of the summary is written from; None
    where the segment has no such figure."""

    distance: float | None = None  # m; for intervals, the reps together
    duration: float | None = None  # s; for intervals, the reps together
    avg_hr: float | None = None  # bpm
    pace: float | None = None  # s/km; for intervals, of the reps
    rep_count: int | None = None
    rep_distance: float | None = None  # m, average
    avg_rep_duration: float | None = None  # s
    avg_recovery: float | None = None  # s


@dataclass
class Segment:
    """A stretch of an activity's laps, from ``start_lap_index`` to ``end_lap_index``
    (``Lap.index``, inclusive)."""

    start_lap_index: int
    end_lap_index: int
    role: SegmentRole
    run_type: RunType
    label: str | None = None
    stats: SegmentStats = field(default_factory=SegmentStats)


@dataclass(frozen=True)
class UserSegment:
    """A segment the user set, from the lap at ``start_lap_index`` (``Lap.index``) to the
    lap before the next user segment's start lap, or to the activity's last lap."""

    start_lap_index: int
    role: SegmentRole
    # None: easy for a warm-up or cool-down, classified from the laps for work; None for a break
    run_type: RunType | None = None


@dataclass
class Activity:
    key: str  # e.g. 'strava_123'
    source: Provider
    name: str | None
    start_time_utc: datetime  # aware
    utc_offset: int  # seconds east of UTC
    timezone: str | None  # e.g. '(GMT+01:00) Europe/Warsaw'
    distance: float | None  # m
    duration: float | None  # s
    speed: float | None  # m/s
    avg_hr: float | None  # bpm
    max_hr: float | None  # bpm
    elevation_gain: float | None  # m
    zone_times: ZoneTimes
    laps: list[Lap]
    segments: list[Segment] = field(default_factory=list)
    training_type: RunType | None = None  # None until segmented
    zone_bounds: ZoneBounds | None = None  # the bounds zone_times is counted in; None until counted
    # the user's split of the laps, in lap order; None: segments are worked out automatically
    user_segments: tuple[UserSegment, ...] | None = None
    device_name: str | None = None  # the recording device, e.g. 'Forerunner 965'; None if unknown

    @property
    def start_time_local(self) -> datetime:
        """The start time at the activity's own UTC offset."""
        return self.start_time_utc.astimezone(timezone(timedelta(seconds=self.utc_offset)))


@dataclass
class ActivityRecord:
    """A stored activity and who it belongs to."""

    user_id: str
    activity: Activity
    summary: Summary
