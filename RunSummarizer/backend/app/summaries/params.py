"""The segment params a summary text is written from."""

from dataclasses import dataclass

from app.domain.enums import RunType, SegmentRole


@dataclass(frozen=True)
class EasyParams:
    distance_m: float
    duration_s: float
    avg_hr: int


@dataclass(frozen=True)
class RaceParams:
    distance_m: float  # snapped to a race distance, otherwise to the nearest 100 m
    duration_s: float
    avg_hr: int


@dataclass(frozen=True)
class ShortIntervalParams:
    rep_count: int
    rep_distance_m: int  # average rep distance, to the nearest 50 m
    avg_rep_s: float
    avg_recovery_s: float  # 0 without recoveries
    fastest_rep_s: float
    slowest_rep_s: float


@dataclass(frozen=True)
class LongIntervalRep:
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class LongIntervalParams:
    reps: tuple[LongIntervalRep, ...]  # one per RUN lap


@dataclass(frozen=True)
class TimeIntervalParams:
    rep_count: int
    avg_rep_s: float
    avg_recovery_s: float  # 0 without recoveries
    avg_rep_distance_m: float
    longest_rep_m: float
    shortest_rep_m: float


@dataclass(frozen=True)
class BreakParams:
    duration_s: float


type SegmentParams = (
    EasyParams
    | RaceParams
    | ShortIntervalParams
    | LongIntervalParams
    | TimeIntervalParams
    | BreakParams
)


@dataclass(frozen=True)
class SegmentSummary:
    """The params one segment's part of a summary is written from, for the segment's laps
    ``start_lap_index`` to ``end_lap_index`` (``Lap.index``, inclusive)."""

    start_lap_index: int
    end_lap_index: int
    role: SegmentRole
    run_type: RunType | None  # None for a break
    label: str | None
    params: SegmentParams
