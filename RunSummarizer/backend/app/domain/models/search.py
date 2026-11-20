from dataclasses import dataclass
from datetime import date

from app.domain.enums import ActivitySortKey, Provider, RunType
from app.domain.models.activity import ActivityRecord


@dataclass(frozen=True)
class NumberRange:
    """Values from ``min`` to ``max``, both inclusive; a None end is open."""

    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class SegmentCriteria:
    """The conditions one work segment of an activity meets: every field that isn't None,
    all by the same segment. A segment missing a value a range filters on doesn't match."""

    run_types: frozenset[RunType] | None = None
    distance: NumberRange | None = None  # m; for intervals, the reps together
    duration: NumberRange | None = None  # s; for intervals, the reps together
    pace: NumberRange | None = None  # s/km; for intervals, of the reps
    avg_hr: NumberRange | None = None  # bpm
    rep_count: NumberRange | None = None
    rep_distance: NumberRange | None = None  # m, the reps' average
    avg_rep_duration: NumberRange | None = None  # s
    avg_recovery: NumberRange | None = None  # s


@dataclass(frozen=True)
class ActivityFilter:
    """The activities of ``user_id`` an activity search finds: those matching every field
    that isn't None, with a work segment meeting each of ``segments``, a different one or
    the same. ``after`` (inclusive) and ``before`` (exclusive) bound the local start date.
    An activity missing a value a range filters on doesn't match."""

    user_id: str
    after: date | None = None
    before: date | None = None
    sources: frozenset[Provider] | None = None
    training_types: frozenset[RunType] | None = None
    distance: NumberRange | None = None  # m
    duration: NumberRange | None = None  # s
    pace: NumberRange | None = None  # s/km, both ends above 0
    avg_hr: NumberRange | None = None  # bpm
    segments: tuple[SegmentCriteria, ...] = ()

    def __post_init__(self):
        if not self.user_id:
            raise ValueError("An activity search needs a user_id")


@dataclass(frozen=True)
class ActivityOrder:
    """The order of an activity search's results; activities missing the value come last."""

    key: ActivitySortKey = ActivitySortKey.START_TIME
    descending: bool = True


NEWEST_FIRST = ActivityOrder()


@dataclass(frozen=True)
class ActivityPage:
    """One page of the activities a search found, and how many it found in all."""

    records: list[ActivityRecord]
    total: int


@dataclass(frozen=True)
class WeekTotals:
    """A user's activity totals of the Monday-based week starting ``week_start``; zero
    when the week has no activities."""

    week_start: date
    distance: float  # m
    duration: float  # s
    elevation_gain: float  # m
