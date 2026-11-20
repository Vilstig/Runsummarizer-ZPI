"""The ``activities`` clauses and order of an activity search."""

from datetime import date, datetime, time

from sqlalchemy import ColumnElement, UnaryExpression, exists

from app.db import models
from app.domain.enums import ActivitySortKey, SegmentRole
from app.domain.models import ActivityFilter, ActivityOrder, NumberRange, SegmentCriteria

activities = models.Activity.__table__
activity_segments = models.ActivitySegment.__table__

METRES_PER_KM = 1000

# The ``activity_segments`` column each ``SegmentCriteria`` range applies to.
_SEGMENT_RANGE_COLUMNS = {
    "distance": activity_segments.c.distance_m,
    "duration": activity_segments.c.duration_s,
    "pace": activity_segments.c.pace_s_per_km,
    "avg_hr": activity_segments.c.avg_hr,
    "rep_count": activity_segments.c.rep_count,
    "rep_distance": activity_segments.c.rep_distance_m,
    "avg_rep_duration": activity_segments.c.avg_rep_s,
    "avg_recovery": activity_segments.c.avg_recovery_s,
}

# The column each sort key orders by, and whether its ascending order is the column's
# descending one.
_SORT_COLUMNS = {
    ActivitySortKey.START_TIME: (activities.c.start_time_local, False),
    ActivitySortKey.DISTANCE: (activities.c.distance_m, False),
    ActivitySortKey.DURATION: (activities.c.duration_s, False),
    ActivitySortKey.PACE: (activities.c.speed_mps, True),  # a faster pace is a higher speed
}


def date_clauses(after: date | None, before: date | None) -> list[ColumnElement[bool]]:
    """The clauses bounding the local start date: ``after`` inclusive, ``before`` exclusive."""
    clauses = []
    if after is not None:
        clauses.append(activities.c.start_time_local >= datetime.combine(after, time.min))
    if before is not None:
        clauses.append(activities.c.start_time_local < datetime.combine(before, time.min))
    return clauses


def range_clauses(column: ColumnElement, values: NumberRange | None) -> list[ColumnElement[bool]]:
    """The clauses keeping ``column`` within ``values``; a NULL is outside any range."""
    if values is None:
        return []
    clauses = []
    if values.min is not None:
        clauses.append(column >= values.min)
    if values.max is not None:
        clauses.append(column <= values.max)
    return clauses


def speed_range(pace: NumberRange) -> NumberRange:
    """The speeds (m/s) of the paces (s/km) in ``pace``: the slowest pace bounds the lowest
    speed."""
    return NumberRange(
        min=METRES_PER_KM / pace.max if pace.max is not None else None,
        max=METRES_PER_KM / pace.min if pace.min is not None else None,
    )


def segment_exists(criteria: SegmentCriteria) -> ColumnElement[bool]:
    """The clause an activity with a work segment meeting every condition of ``criteria``
    meets."""
    clauses = [
        activity_segments.c.activity_id == activities.c.id,
        activity_segments.c.role == SegmentRole.WORK.value,
    ]
    if criteria.run_types is not None:
        clauses.append(
            activity_segments.c.run_type_id.in_([run_type.value for run_type in criteria.run_types])
        )
    for field, column in _SEGMENT_RANGE_COLUMNS.items():
        clauses += range_clauses(column, getattr(criteria, field))
    return exists().where(*clauses)


def search_clauses(activity_filter: ActivityFilter) -> list[ColumnElement[bool]]:
    """The clauses an activity matching ``activity_filter`` meets."""
    clauses = [
        activities.c.user_id == activity_filter.user_id,
        *date_clauses(activity_filter.after, activity_filter.before),
    ]
    if activity_filter.sources is not None:
        clauses.append(
            activities.c.source.in_([source.value for source in activity_filter.sources])
        )
    if activity_filter.training_types is not None:
        clauses.append(
            activities.c.training_type_id.in_(
                [training_type.value for training_type in activity_filter.training_types]
            )
        )
    clauses += range_clauses(activities.c.distance_m, activity_filter.distance)
    clauses += range_clauses(activities.c.duration_s, activity_filter.duration)
    if activity_filter.pace is not None:
        clauses += range_clauses(activities.c.speed_mps, speed_range(activity_filter.pace))
    clauses += range_clauses(activities.c.avg_hr, activity_filter.avg_hr)
    clauses += [segment_exists(criteria) for criteria in activity_filter.segments]
    return clauses


def search_order(order: ActivityOrder) -> list[UnaryExpression]:
    """The ORDER BY of ``order``: missing values last, ties by id in the same direction, so
    pages neither repeat nor skip activities."""
    column, inverted = _SORT_COLUMNS[order.key]
    by_column = column.desc() if order.descending != inverted else column.asc()
    by_id = activities.c.id.desc() if order.descending else activities.c.id.asc()
    return [by_column.nulls_last(), by_id]
