import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import (
    ColumnElement,
    Date,
    Double,
    Row,
    SmallInteger,
    and_,
    bindparam,
    case,
    cast,
    delete,
    false,
    func,
    literal,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.db.protocols import AsyncActivityRepository
from app.db.repositories.postgres.activity_search import (
    date_clauses,
    search_clauses,
    search_order,
)
from app.domain.enums import LapType, Provider, RunType, SegmentRole, StreamType
from app.domain.models import (
    NEWEST_FIRST,
    Activity,
    ActivityFilter,
    ActivityOrder,
    ActivityPage,
    ActivityRecord,
    Lap,
    Segment,
    SegmentStats,
    Summary,
    UserSegment,
    WeekTotals,
    ZoneBounds,
    ZoneTimes,
)

activities = models.Activity.__table__
laps = models.Lap.__table__
activity_segments = models.ActivitySegment.__table__
raw_payloads = models.ActivityRawPayload.__table__
activity_streams = models.ActivityStream.__table__

# Column of each stream, and the factor its samples are multiplied by when stored:
# decimal streams are kept as whole numbers of a smaller unit.
_STREAM_COLUMNS: dict[StreamType, tuple[str, int]] = {
    StreamType.TIME: ("time_s", 1),
    StreamType.DISTANCE: ("distance_dm", 10),
    StreamType.HEARTRATE: ("heartrate_bpm", 1),
    StreamType.VELOCITY: ("velocity_cms", 100),
    StreamType.ALTITUDE: ("altitude_dm", 10),
}

# The ``activity_segments`` column of each ``SegmentStats`` field.
_STATS_COLUMNS = {
    "distance": "distance_m",
    "duration": "duration_s",
    "avg_hr": "avg_hr",
    "pace": "pace_s_per_km",
    "rep_count": "rep_count",
    "rep_distance": "rep_distance_m",
    "avg_rep_duration": "avg_rep_s",
    "avg_recovery": "avg_recovery_s",
}

_HR_ZONES = range(1, 6)
_BOUNDED_HR_ZONES = range(2, 6)  # the zones an hr_zone*_bpm column holds the lower bound of

_IMPORTED_VERSION, _EDITED_VERSION = 0, 1  # laps.version


def _start_columns(activity: Activity) -> dict:
    start = activity.start_time_utc
    if start.utcoffset() is None:
        raise ValueError(f"Expected a start time with a UTC offset, got {start!r}")
    return {
        "start_time_utc": start.astimezone(UTC),
        "start_time_local": activity.start_time_local.replace(tzinfo=None),
        "utc_offset_s": activity.utc_offset,
        "timezone": activity.timezone,
    }


def _segment_rows(activity_id: uuid.UUID, segments: list[Segment]) -> list[dict]:
    """The ``activity_segments`` rows of ``segments``, in order."""
    return [
        {
            "activity_id": activity_id,
            "position": position,
            "start_lap_index": segment.start_lap_index,
            "end_lap_index": segment.end_lap_index,
            "role": segment.role.value,
            "run_type_id": segment.run_type.value,
            "label": segment.label,
            **{column: getattr(segment.stats, field) for field, column in _STATS_COLUMNS.items()},
        }
        for position, segment in enumerate(segments)
    ]


def _segment(row: Row) -> Segment:
    return Segment(
        start_lap_index=row.start_lap_index,
        end_lap_index=row.end_lap_index,
        role=SegmentRole(row.role),
        run_type=RunType(row.run_type_id),
        label=row.label,
        stats=SegmentStats(
            **{field: getattr(row, column) for field, column in _STATS_COLUMNS.items()}
        ),
    )


def _user_segment_document(segment: UserSegment) -> dict:
    return {
        "startLapIndex": segment.start_lap_index,
        "role": segment.role.value,
        "runTypeId": segment.run_type.value if segment.run_type is not None else None,
    }


def _user_segment(document: dict) -> UserSegment:
    run_type = document["runTypeId"]
    return UserSegment(
        start_lap_index=document["startLapIndex"],
        role=SegmentRole(document["role"]),
        run_type=RunType(run_type) if run_type is not None else None,
    )


def _user_segments_document(user_segments: tuple[UserSegment, ...] | None) -> list[dict] | None:
    """The ``user_segments`` jsonb of an activity; None when it is segmented automatically."""
    if user_segments is None:
        return None
    return [_user_segment_document(segment) for segment in user_segments]


def _user_segments(documents: list[dict] | None) -> tuple[UserSegment, ...] | None:
    if documents is None:
        return None
    return tuple(_user_segment(document) for document in documents)


def _summary_columns(summary: Summary) -> dict:
    """The ``activities`` columns a summary is held in."""
    return {"summary": summary.text, "summary_text_edited_at": summary.text_edited_at}


def _activity_columns(activity: Activity) -> dict:
    """The ``activities`` columns an activity's fields are held in."""
    return {
        **_start_columns(activity),
        "name": activity.name,
        "distance_m": activity.distance,
        "duration_s": activity.duration,
        "speed_mps": activity.speed,
        "avg_hr": activity.avg_hr,
        "max_hr": activity.max_hr,
        "elevation_gain_m": activity.elevation_gain,
        **{f"hr_zone{n}_s": activity.zone_times[n] or 0 for n in _HR_ZONES},
        **_zone_bound_columns(activity.zone_bounds),
        "training_type_id": (
            activity.training_type.value if activity.training_type is not None else None
        ),
        "user_segments": _user_segments_document(activity.user_segments),
    }


def _zone_bound_columns(bounds: ZoneBounds | None) -> dict:
    """The ``activities`` columns zone bounds are held in. Raises ``ValueError`` for None."""
    if bounds is None:
        raise ValueError("The activity's HR zone times are not counted")
    return {f"hr_zone{n}_bpm": bound for n, bound in zip(_BOUNDED_HR_ZONES, bounds, strict=True)}


def _activity_values(record: ActivityRecord) -> dict:
    """The ``activities`` row for a record."""
    if not record.user_id:
        raise ValueError(
            f"Activity {record.activity.key!r} needs a user_id, got {record.user_id!r}"
        )
    return {
        "user_id": record.user_id,
        "source": record.activity.source.value,
        "activity_key": record.activity.key,
        "device_name": record.activity.device_name,
        **_summary_columns(record.summary),
        **_activity_columns(record.activity),
    }


def _lap_type_id(lap: Lap) -> int:
    if lap.type is None:
        raise ValueError(f"Lap {lap.index} has no type")
    return lap.type.value


def _lap_rows(activity_id: uuid.UUID, activity_laps: list[Lap]) -> list[dict]:
    """The version-0 ``laps`` rows of ``activity_laps``."""
    rows = []
    for lap in activity_laps:
        rows.append(
            {
                "activity_id": activity_id,
                "lap_index": lap.index,
                "version": _IMPORTED_VERSION,
                "lap_type_id": _lap_type_id(lap),
                "distance_m": lap.distance,
                "duration_s": lap.duration,
                "speed_mps": lap.speed,
                "avg_hr": lap.avg_hr,
                "max_hr": lap.max_hr,
                "elevation_gain_m": lap.elevation_gain,
            }
        )
    return rows


def _lap(row: Row) -> Lap:
    return Lap(
        index=row.lap_index,
        type=LapType(row.lap_type_id),
        distance=row.distance_m,
        duration=row.duration_s,
        speed=row.speed_mps,
        avg_hr=row.avg_hr,
        max_hr=row.max_hr,
        elevation_gain=row.elevation_gain_m,
        version=row.version,
    )


def _edited_lap_upsert(activity_id: uuid.UUID, lap_index: int, distance: float):
    """The statement writing version 1 of a lap as a copy of its version 0 with ``distance``
    and the speed over its duration (NULL without a duration)."""
    distance_value = literal(distance, Double)
    source = select(
        laps.c.activity_id,
        laps.c.lap_index,
        literal(_EDITED_VERSION, SmallInteger),
        laps.c.lap_type_id,
        distance_value,
        laps.c.duration_s,
        case((laps.c.duration_s > 0, distance_value / laps.c.duration_s), else_=None),
        laps.c.avg_hr,
        laps.c.max_hr,
        laps.c.elevation_gain_m,
    ).where(
        laps.c.activity_id == activity_id,
        laps.c.lap_index == lap_index,
        laps.c.version == _IMPORTED_VERSION,
    )
    upsert = insert(laps).from_select(
        [
            "activity_id",
            "lap_index",
            "version",
            "lap_type_id",
            "distance_m",
            "duration_s",
            "speed_mps",
            "avg_hr",
            "max_hr",
            "elevation_gain_m",
        ],
        source,
    )
    return upsert.on_conflict_do_update(
        index_elements=[laps.c.activity_id, laps.c.lap_index, laps.c.version],
        set_={"distance_m": upsert.excluded.distance_m, "speed_mps": upsert.excluded.speed_mps},
    )


def _stream_values(activity_id: uuid.UUID, streams: dict) -> dict:
    """The ``activity_streams`` row for ``{stream type: samples}``; a stream it doesn't
    hold is NULL.
    """
    values = {"activity_id": activity_id}
    for stream_type, (column, scale) in _STREAM_COLUMNS.items():
        samples = streams.get(stream_type)
        values[column] = None if samples is None else [round(value * scale) for value in samples]
    return values


def _streams_document(row: Row, stream_types: list[StreamType]) -> dict[str, list]:
    """``{stream type: samples}`` of ``stream_types`` in an ``activity_streams`` row, each
    in its ``StreamType`` unit; a NULL stream is left out.
    """
    streams = {}
    for stream_type in stream_types:
        column, scale = _STREAM_COLUMNS[stream_type]
        stored = getattr(row, column)
        if stored is not None:
            streams[stream_type.value] = (
                stored if scale == 1 else [value / scale for value in stored]
            )
    return streams


def _activity(row: Row, activity_laps: list[Lap], segments: list[Segment]) -> Activity:
    return Activity(
        key=row.activity_key,
        source=Provider(row.source),
        name=row.name,
        start_time_utc=row.start_time_utc,
        utc_offset=row.utc_offset_s,
        timezone=row.timezone,
        distance=row.distance_m,
        duration=row.duration_s,
        speed=row.speed_mps,
        avg_hr=row.avg_hr,
        max_hr=row.max_hr,
        elevation_gain=row.elevation_gain_m,
        zone_times=ZoneTimes(*(getattr(row, f"hr_zone{n}_s") for n in _HR_ZONES)),
        zone_bounds=tuple(getattr(row, f"hr_zone{n}_bpm") for n in _BOUNDED_HR_ZONES),
        laps=activity_laps,
        segments=segments,
        training_type=(RunType(row.training_type_id) if row.training_type_id is not None else None),
        user_segments=_user_segments(row.user_segments),
        device_name=row.device_name,
    )


def _check_payload_kind(raw_payload: dict | None, payload_kind: str | None) -> None:
    """Raise ``ValueError`` for a ``raw_payload`` without a ``payload_kind``."""
    if raw_payload is not None and payload_kind is None:
        raise ValueError("a raw payload needs a payload_kind")


def _record(row: Row, activity_laps: list[Lap], segments: list[Segment]) -> ActivityRecord:
    return ActivityRecord(
        user_id=str(row.user_id),
        activity=_activity(row, activity_laps, segments),
        summary=Summary(text=row.summary, text_edited_at=row.summary_text_edited_at),
    )


def _week_starts(first_week_start: date, weeks: int):
    """A ``week_start`` column of the Monday-based weeks from ``first_week_start``, one row
    per week."""
    last_week_start = first_week_start + timedelta(weeks=weeks - 1)
    series = (
        func.generate_series(
            literal(first_week_start, Date),
            literal(last_week_start, Date),
            text("interval '7 days'"),
        )
        .table_valued("week_start", type_=Date)
        .render_derived()
    )
    # Postgres has no date/date/interval generate_series overload: it runs the
    # timestamp one and returns timestamps, so the column is cast back to a date.
    week_start = cast(series.c.week_start, Date).label("week_start")
    return select(week_start).subquery("week_starts")


def _week_totals(row: Row) -> WeekTotals:
    return WeekTotals(
        week_start=row.week_start,
        distance=row.distance,
        duration=row.duration,
        elevation_gain=row.elevation_gain,
    )


def _owner_filter(user_id: str | None) -> ColumnElement[bool] | None:
    """The clause restricting activities to ``user_id``; None when unrestricted.

    An empty ``user_id`` matches nothing.
    """
    if user_id is None:
        return None
    if not user_id:
        return false()
    return activities.c.user_id == user_id


class PostgresActivityRepository(AsyncActivityRepository):
    """Postgres store for ``AsyncActivityRepository``."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_activities(
        self,
        *,
        user_id: str | None = None,
        source: str | None = None,
        after: date | None = None,
        before: date | None = None,
        limit: int = 50,
        skip: int = 0,
        include_laps: bool = False,
    ) -> list[ActivityRecord]:
        query = select(activities).where(*date_clauses(after, before))
        owner = _owner_filter(user_id)
        if owner is not None:
            query = query.where(owner)
        if source:
            query = query.where(activities.c.source == source)
        query = (
            query.order_by(activities.c.start_time_local.desc(), activities.c.id.desc())
            .offset(skip)
            .limit(limit)
        )

        rows = (await self._session.execute(query)).all()
        return await self._records(rows, include_laps=include_laps)

    async def search_activities(
        self,
        activity_filter: ActivityFilter,
        *,
        order: ActivityOrder = NEWEST_FIRST,
        limit: int = 50,
        offset: int = 0,
    ) -> ActivityPage:
        clauses = search_clauses(activity_filter)
        total = (
            await self._session.execute(
                select(func.count()).select_from(activities).where(*clauses)
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                select(activities)
                .where(*clauses)
                .order_by(*search_order(order))
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return ActivityPage(records=await self._records(rows, include_laps=False), total=total)

    async def weekly_totals(
        self, user_id: str, *, first_week_start: date, weeks: int
    ) -> list[WeekTotals]:
        week_starts = _week_starts(first_week_start, weeks)
        last_week_start = first_week_start + timedelta(weeks=weeks - 1)
        range_start = datetime.combine(first_week_start, time.min)
        range_end = datetime.combine(last_week_start + timedelta(days=7), time.min)
        week_bucket = cast(func.date_trunc("week", activities.c.start_time_local), Date)

        query = (
            select(
                week_starts.c.week_start,
                func.coalesce(func.sum(activities.c.distance_m), 0.0).label("distance"),
                func.coalesce(func.sum(activities.c.duration_s), 0.0).label("duration"),
                func.coalesce(func.sum(activities.c.elevation_gain_m), 0.0).label("elevation_gain"),
            )
            .select_from(week_starts)
            .outerjoin(
                activities,
                and_(
                    week_bucket == week_starts.c.week_start,
                    activities.c.user_id == user_id,
                    activities.c.start_time_local >= range_start,
                    activities.c.start_time_local < range_end,
                ),
            )
            .group_by(week_starts.c.week_start)
            .order_by(week_starts.c.week_start)
        )
        rows = (await self._session.execute(query)).all()
        return [_week_totals(row) for row in rows]

    async def get_by_id(
        self, activity_id: str, *, user_id: str | None = None
    ) -> ActivityRecord | None:
        return await self._read_record(activity_id, user_id, lock=False)

    async def get_and_lock_by_id(
        self, activity_id: str, *, user_id: str | None = None
    ) -> ActivityRecord | None:
        return await self._read_record(activity_id, user_id, lock=True)

    async def is_stored(self, user_id: str, activity_key: str) -> bool:
        return await self._find_id(activity_key, user_id) is not None

    async def get_laps(self, activity_id: str, *, user_id: str | None = None) -> list[Lap] | None:
        found = await self._find_id(activity_id, user_id)
        if found is None:
            return None
        return (await self._laps_by_activity([found])).get(found, [])

    async def get_streams(
        self,
        activity_id: str,
        *,
        user_id: str | None = None,
        stream_types: Iterable[StreamType] | None = None,
    ) -> dict[str, list] | None:
        found = await self._find_id(activity_id, user_id)
        if found is None:
            return None
        selected = list(dict.fromkeys(StreamType if stream_types is None else stream_types))
        if not selected:
            return {}
        columns = [activity_streams.c[_STREAM_COLUMNS[stream_type][0]] for stream_type in selected]
        row = (
            await self._session.execute(
                select(*columns).where(activity_streams.c.activity_id == found)
            )
        ).first()
        return _streams_document(row, selected) if row is not None else {}

    async def get_raw_payload(self, activity_id: str, *, user_id: str | None = None) -> dict | None:
        found = await self._find_id(activity_id, user_id)
        if found is None:
            return None
        return (
            await self._session.execute(
                select(raw_payloads.c.payload)
                .where(raw_payloads.c.activity_id == found)
                .order_by(raw_payloads.c.fetched_at.desc(), raw_payloads.c.payload_kind)
                .limit(1)
            )
        ).scalar_one_or_none()

    async def update_activity(
        self,
        activity_id: str,
        activity: Activity,
        *,
        summary: Summary,
        user_id: str | None = None,
    ) -> ActivityRecord | None:
        found = await self._find_id(activity_id, user_id)
        if found is None:
            return None

        async with self._session.begin_nested():
            await self._session.execute(
                update(activities)
                .where(activities.c.id == found)
                .values(
                    **_activity_columns(activity),
                    **_summary_columns(summary),
                    updated_at=func.now(),
                )
            )
            await self._set_lap_types(found, activity.laps)
            await self._replace_segments(found, activity.segments)

        return await self._stored_record(found)

    async def set_lap_distances(
        self, activity_id: str, distances: Mapping[int, float], *, user_id: str | None = None
    ) -> ActivityRecord | None:
        found = await self._find_id(activity_id, user_id)
        if found is None:
            return None
        await self._check_lap_indexes(found, activity_id, distances)

        async with self._session.begin_nested():
            for lap_index, distance in distances.items():
                await self._session.execute(_edited_lap_upsert(found, lap_index, distance))

        return await self._stored_record(found)

    async def reset_lap_distances(
        self,
        activity_id: str,
        lap_indexes: Iterable[int] | None = None,
        *,
        user_id: str | None = None,
    ) -> ActivityRecord | None:
        found = await self._find_id(activity_id, user_id)
        if found is None:
            return None

        query = delete(laps).where(laps.c.activity_id == found, laps.c.version == _EDITED_VERSION)
        if lap_indexes is not None:
            lap_indexes = list(lap_indexes)
            await self._check_lap_indexes(found, activity_id, lap_indexes)
            query = query.where(laps.c.lap_index.in_(lap_indexes))
        await self._session.execute(query)

        return await self._stored_record(found)

    async def update_summary(
        self, activity_id: str, summary: Summary, *, user_id: str | None = None
    ) -> ActivityRecord | None:
        found = await self._find_id(activity_id, user_id)
        if found is None:
            return None

        await self._session.execute(
            update(activities)
            .where(activities.c.id == found)
            .values(**_summary_columns(summary), updated_at=func.now())
        )
        return await self._stored_record(found)

    async def save(
        self,
        record: ActivityRecord,
        *,
        raw_payload: dict | None = None,
        payload_kind: str | None = None,
        streams: dict | None = None,
    ) -> bool:
        _check_payload_kind(raw_payload, payload_kind)
        insert_activity = (
            insert(activities)
            .values(_activity_values(record))
            .on_conflict_do_nothing(
                index_elements=[activities.c.user_id, activities.c.activity_key]
            )
            .returning(activities.c.id)
        )

        async with self._session.begin_nested():
            activity_id = (await self._session.execute(insert_activity)).scalar_one_or_none()
            if activity_id is not None:
                await self._save_details(
                    activity_id, record.activity, raw_payload, payload_kind, streams
                )
        return activity_id is not None

    async def delete(self, activity_id: str, *, user_id: str | None = None) -> bool:
        found = await self._find_id(activity_id, user_id)
        if found is None:
            return False
        await self._session.execute(delete(activities).where(activities.c.id == found))
        return True

    async def _find_id(self, activity_key: str, user_id: str | None) -> uuid.UUID | None:
        query = select(activities.c.id).where(activities.c.activity_key == activity_key)
        owner = _owner_filter(user_id)
        if owner is not None:
            query = query.where(owner)
        return (await self._session.execute(query.limit(1))).scalar_one_or_none()

    async def _read_record(
        self, activity_key: str, user_id: str | None, *, lock: bool
    ) -> ActivityRecord | None:
        """The user's record under ``activity_key``, with its laps; with ``lock``, its
        ``activities`` row is locked until the transaction ends.
        """
        query = select(activities).where(activities.c.activity_key == activity_key)
        owner = _owner_filter(user_id)
        if owner is not None:
            query = query.where(owner)
        if lock:
            query = query.with_for_update()
        row = (await self._session.execute(query.limit(1))).first()
        if row is None:
            return None
        return (await self._records([row], include_laps=True))[0]

    async def _stored_record(self, activity_id: uuid.UUID) -> ActivityRecord:
        """The record of the activity with primary key ``activity_id``, with its laps."""
        row = (
            await self._session.execute(select(activities).where(activities.c.id == activity_id))
        ).one()
        return (await self._records([row], include_laps=True))[0]

    async def _records(self, rows: list[Row], *, include_laps: bool) -> list[ActivityRecord]:
        """The records of ``activities`` rows, with their segments, and with their laps when
        ``include_laps``."""
        activity_ids = [row.id for row in rows]
        laps_by_activity = await self._laps_by_activity(activity_ids) if include_laps else {}
        segments_by_activity = await self._segments_by_activity(activity_ids)
        return [
            _record(row, laps_by_activity.get(row.id, []), segments_by_activity.get(row.id, []))
            for row in rows
        ]

    async def _laps_by_activity(self, activity_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Lap]]:
        """The newest version of each lap of ``activity_ids``, in lap order."""
        if not activity_ids:
            return {}
        result = await self._session.execute(
            select(laps)
            .ext(distinct_on(laps.c.activity_id, laps.c.lap_index))
            .where(laps.c.activity_id.in_(activity_ids))
            .order_by(laps.c.activity_id, laps.c.lap_index, laps.c.version.desc())
        )
        grouped: dict[uuid.UUID, list[Lap]] = {}
        for row in result:
            grouped.setdefault(row.activity_id, []).append(_lap(row))
        return grouped

    async def _segments_by_activity(
        self, activity_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[Segment]]:
        """The segments of ``activity_ids``, in lap order."""
        if not activity_ids:
            return {}
        result = await self._session.execute(
            select(activity_segments)
            .where(activity_segments.c.activity_id.in_(activity_ids))
            .order_by(activity_segments.c.activity_id, activity_segments.c.position)
        )
        grouped: dict[uuid.UUID, list[Segment]] = {}
        for row in result:
            grouped.setdefault(row.activity_id, []).append(_segment(row))
        return grouped

    async def _save_details(
        self,
        activity_id: uuid.UUID,
        activity: Activity,
        raw_payload: dict | None,
        payload_kind: str | None,
        streams: dict | None,
    ) -> None:
        """Write the activity's laps and segments, replacing the stored ones, ``raw_payload``
        under ``payload_kind`` when given, and ``streams`` (``{stream type: samples}``),
        replacing the stored ones as a whole, when given.
        """
        await self._replace_laps(activity_id, activity.laps)
        await self._replace_segments(activity_id, activity.segments)

        if raw_payload is not None:
            insert_payload = insert(raw_payloads).values(
                activity_id=activity_id,
                payload_kind=payload_kind,
                payload=raw_payload,
            )
            await self._session.execute(
                insert_payload.on_conflict_do_update(
                    index_elements=[raw_payloads.c.activity_id, raw_payloads.c.payload_kind],
                    set_={"payload": insert_payload.excluded.payload, "fetched_at": func.now()},
                )
            )

        if streams is not None:
            insert_streams = insert(activity_streams).values(_stream_values(activity_id, streams))
            await self._session.execute(
                insert_streams.on_conflict_do_update(
                    index_elements=[activity_streams.c.activity_id],
                    set_={
                        column: insert_streams.excluded[column]
                        for column, _ in _STREAM_COLUMNS.values()
                    },
                )
            )

    async def _check_lap_indexes(
        self, activity_id: uuid.UUID, activity_key: str, lap_indexes: Iterable[int]
    ) -> None:
        """Raise ``ValueError`` for an index of ``lap_indexes`` the activity has no lap at."""
        stored = set(
            (
                await self._session.execute(
                    select(laps.c.lap_index).where(
                        laps.c.activity_id == activity_id, laps.c.version == _IMPORTED_VERSION
                    )
                )
            ).scalars()
        )
        unknown = sorted(set(lap_indexes) - stored)
        if unknown:
            raise ValueError(f"Activity {activity_key!r} has no lap {unknown[0]}")

    async def _set_lap_types(self, activity_id: uuid.UUID, activity_laps: list[Lap]) -> None:
        """Set the type of every version of each lap of ``activity_laps``."""
        if not activity_laps:
            return
        await self._session.execute(
            update(laps)
            .where(laps.c.activity_id == activity_id, laps.c.lap_index == bindparam("b_lap_index"))
            .values(lap_type_id=bindparam("b_lap_type_id")),
            [
                {"b_lap_index": lap.index, "b_lap_type_id": _lap_type_id(lap)}
                for lap in activity_laps
            ],
        )

    async def _replace_laps(self, activity_id: uuid.UUID, activity_laps: list[Lap]) -> None:
        """Replace every version of the activity's laps with version-0 rows of
        ``activity_laps``."""
        await self._session.execute(delete(laps).where(laps.c.activity_id == activity_id))
        if activity_laps:
            await self._session.execute(insert(laps), _lap_rows(activity_id, activity_laps))

    async def _replace_segments(self, activity_id: uuid.UUID, segments: list[Segment]) -> None:
        """Replace the activity's segments with ``segments``."""
        await self._session.execute(
            delete(activity_segments).where(activity_segments.c.activity_id == activity_id)
        )
        if segments:
            await self._session.execute(
                insert(activity_segments), _segment_rows(activity_id, segments)
            )
