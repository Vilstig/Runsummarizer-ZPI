from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta

from app.core.clock import utc_now
from app.db.protocols import AsyncActivityRepository
from app.domain.enums import LapType, Provider, StreamType
from app.domain.errors import ActivityNotFoundError, UnknownLapError
from app.domain.models import (
    NEWEST_FIRST,
    Activity,
    ActivityFilter,
    ActivityOrder,
    ActivityPage,
    ActivityRecord,
    Lap,
    Summary,
    UserSegment,
    WeekTotals,
)
from app.summaries.editing import (
    TextPolicy,
    check_text_policy,
    edit_text,
    refreshed_summary,
)
from app.summaries.segmentation import relabel_laps, segment_activity
from app.summaries.summary import summarize


def _check_lap_indexes(activity: Activity, lap_indexes: Iterable[int]) -> None:
    """Raise ``UnknownLapError`` for an index of ``lap_indexes`` the activity has no lap
    at."""
    unknown = sorted(set(lap_indexes) - {lap.index for lap in activity.laps})
    if unknown:
        raise UnknownLapError(f"Unknown lapIndex: {unknown[0]}")


class ActivityService:
    """Reads and edits a user's activities. ``clock`` gives the current time."""

    def __init__(self, repo: AsyncActivityRepository, clock: Callable[[], datetime] = utc_now):
        self._repo = repo
        self._clock = clock

    async def list_activities(
        self,
        *,
        limit: int = 50,
        skip: int = 0,
        source: Provider | None = None,
        include_laps: bool = False,
        after: date | None = None,
        before: date | None = None,
        user_id: str | None = None,
    ) -> list[ActivityRecord]:
        return await self._repo.list_activities(
            user_id=user_id,
            source=source,
            after=after,
            before=before,
            limit=limit,
            skip=skip,
            include_laps=include_laps,
        )

    async def search_activities(
        self,
        activity_filter: ActivityFilter,
        *,
        order: ActivityOrder = NEWEST_FIRST,
        limit: int = 50,
        offset: int = 0,
    ) -> ActivityPage:
        """The page ``offset``/``limit`` of the user's activities ``activity_filter`` finds,
        in ``order``, without their laps, and how many it finds in all."""
        return await self._repo.search_activities(
            activity_filter, order=order, limit=limit, offset=offset
        )

    async def weekly_summary(
        self, *, weeks: int, user_id: str, as_of: date | None = None
    ) -> list[WeekTotals]:
        """The user's distance, duration and elevation gain by Monday-based week, oldest
        first, for the ``weeks`` weeks ending with the week containing ``as_of`` (today, by
        the service's clock, when None). A week without activities is zero.
        """
        reference = as_of if as_of is not None else self._clock().date()
        current_week_start = reference - timedelta(days=reference.weekday())
        first_week_start = current_week_start - timedelta(weeks=weeks - 1)
        return await self._repo.weekly_totals(
            user_id, first_week_start=first_week_start, weeks=weeks
        )

    async def get_activity(self, activity_id: str, *, user_id: str | None = None) -> ActivityRecord:
        """The activity, or ``ActivityNotFoundError`` when it isn't found."""
        record = await self._repo.get_by_id(activity_id, user_id=user_id)
        if not record:
            raise ActivityNotFoundError("Activity not found")
        return record

    async def get_activity_laps(self, activity_id: str, *, user_id: str | None = None) -> list[Lap]:
        """The activity's classified laps, or ``ActivityNotFoundError`` when it isn't found."""
        laps = await self._repo.get_laps(activity_id, user_id=user_id)
        if laps is None:
            raise ActivityNotFoundError("Activity not found")
        return laps

    async def get_activity_streams(
        self,
        activity_id: str,
        *,
        user_id: str | None = None,
        stream_types: Sequence[StreamType] = tuple(StreamType),
    ) -> dict:
        """``{stream type: samples}`` of each of ``stream_types``, with None for a stream
        the activity lacks. Raises ``ActivityNotFoundError`` when the activity isn't found.
        """
        streams = await self._repo.get_streams(
            activity_id, user_id=user_id, stream_types=stream_types
        )
        if streams is None:
            raise ActivityNotFoundError("Activity not found")
        return {stream_type.value: streams.get(stream_type.value) for stream_type in stream_types}

    async def edit_laps(
        self,
        activity_id: str,
        lap_types: Mapping[int, LapType],
        distances: Mapping[int, float],
        *,
        text_policy: TextPolicy | None = None,
        user_id: str | None = None,
    ) -> ActivityRecord:
        """Retype the activity's laps (``Lap.index`` -> type) and store the user's lap
        ``distances`` (``Lap.index`` -> m), then segment it again and fit its summary to it
        as ``refreshed_summary`` does. Raises ``ActivityNotFoundError`` when the activity
        isn't found; ``UnknownLapError`` for an index the activity has no lap at and
        ``TextPolicyRequiredError`` when the user edited the summary text and ``text_policy``
        is None, both before anything is written.
        """
        record = await self._repo.get_and_lock_by_id(activity_id, user_id=user_id)
        if not record:
            raise ActivityNotFoundError("Activity not found")
        _check_lap_indexes(record.activity, [*lap_types, *distances])
        check_text_policy(record.summary, text_policy)

        if distances:
            record = await self._repo.set_lap_distances(activity_id, distances, user_id=user_id)
        activity = relabel_laps(record.activity, dict(lap_types))
        return await self._store_resegmented(record, activity, text_policy, user_id=user_id)

    async def reset_laps(
        self,
        activity_id: str,
        lap_indexes: Iterable[int] | None = None,
        *,
        text_policy: TextPolicy | None = None,
        user_id: str | None = None,
    ) -> ActivityRecord:
        """Drop the user's distances of the laps at ``lap_indexes``, or of every lap when
        None, then segment the activity again and fit its summary to it as
        ``refreshed_summary`` does. Raises as ``edit_laps`` does, before anything is written.
        """
        record = await self._repo.get_and_lock_by_id(activity_id, user_id=user_id)
        if not record:
            raise ActivityNotFoundError("Activity not found")
        if lap_indexes is not None:
            lap_indexes = list(lap_indexes)
            _check_lap_indexes(record.activity, lap_indexes)
        check_text_policy(record.summary, text_policy)

        record = await self._repo.reset_lap_distances(activity_id, lap_indexes, user_id=user_id)
        activity = segment_activity(record.activity)
        return await self._store_resegmented(record, activity, text_policy, user_id=user_id)

    async def set_segments(
        self,
        activity_id: str,
        user_segments: Sequence[UserSegment] | None,
        *,
        text_policy: TextPolicy | None = None,
        user_id: str | None = None,
    ) -> ActivityRecord:
        """Split the activity into the user's segments, or back into automatic segments when
        ``user_segments`` is None, and fit its summary to them as ``refreshed_summary`` does.
        Raises ``ActivityNotFoundError`` when the activity isn't found;
        ``InvalidSegmentationError`` for segments that don't cover its laps, and
        ``TextPolicyRequiredError`` when the user edited the summary text and ``text_policy``
        is None.
        """
        record = await self._repo.get_and_lock_by_id(activity_id, user_id=user_id)
        if not record:
            raise ActivityNotFoundError("Activity not found")

        user_segments = tuple(user_segments) if user_segments is not None else None
        activity = segment_activity(replace(record.activity, user_segments=user_segments))
        return await self._store_resegmented(record, activity, text_policy, user_id=user_id)

    async def edit_summary(
        self, activity_id: str, text: str, *, user_id: str | None = None
    ) -> ActivityRecord:
        """Replace the activity's summary text with the user's ``text``, as ``edit_text``
        does. Raises ``ActivityNotFoundError`` when the activity isn't found.
        """
        return await self._replace_summary(
            activity_id,
            lambda record: edit_text(record.summary, text, self._clock()),
            user_id=user_id,
        )

    async def reset_summary(
        self, activity_id: str, *, user_id: str | None = None
    ) -> ActivityRecord:
        """Write the activity's summary again from its laps and segments, dropping the user's
        edits of the summary; the user's segments stay. Raises ``ActivityNotFoundError`` when
        the activity isn't found.
        """
        return await self._replace_summary(
            activity_id, lambda record: summarize(record.activity), user_id=user_id
        )

    async def delete_activity(self, activity_id: str, *, user_id: str | None = None) -> None:
        """Delete the activity. Raises ``ActivityNotFoundError`` when it isn't found."""
        if not await self._repo.delete(activity_id, user_id=user_id):
            raise ActivityNotFoundError("Activity not found")

    async def _store_resegmented(
        self,
        record: ActivityRecord,
        activity: Activity,
        text_policy: TextPolicy | None,
        *,
        user_id: str | None,
    ) -> ActivityRecord:
        """Store ``activity``, the record's activity segmented again, with the record's
        summary fitted to it as ``refreshed_summary`` does."""
        summary = refreshed_summary(record.summary, summarize(activity), text_policy)
        updated = await self._repo.update_activity(
            record.activity.key, activity, summary=summary, user_id=user_id
        )
        if updated is None:
            raise ActivityNotFoundError("Activity not found")
        return updated

    async def _replace_summary(
        self,
        activity_id: str,
        new_summary: Callable[[ActivityRecord], Summary],
        *,
        user_id: str | None,
    ) -> ActivityRecord:
        """Store ``new_summary(record)`` as the activity's summary. Raises
        ``ActivityNotFoundError`` when the activity isn't found.
        """
        record = await self._repo.get_and_lock_by_id(activity_id, user_id=user_id)
        if not record:
            raise ActivityNotFoundError("Activity not found")
        updated = await self._repo.update_summary(activity_id, new_summary(record), user_id=user_id)
        if updated is None:
            raise ActivityNotFoundError("Activity not found")
        return updated
