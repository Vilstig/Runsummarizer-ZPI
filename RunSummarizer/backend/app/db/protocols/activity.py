from abc import abstractmethod
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Protocol

from app.domain.enums import StreamType
from app.domain.models import (
    NEWEST_FIRST,
    Activity,
    ActivityFilter,
    ActivityOrder,
    ActivityPage,
    ActivityRecord,
    Lap,
    Summary,
    WeekTotals,
)


class AsyncActivityRepository(Protocol):
    """Activity persistence contract.

    A lap is stored as imported (``Lap.version`` 0) and, once the user edited its distance,
    as edited (1). Every read gives each lap in its newest version.
    """

    @abstractmethod
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
        """Activities newest first. ``after`` (inclusive) and ``before`` (exclusive) bound
        the local start date. Without ``include_laps`` their activities have no laps.
        """

    @abstractmethod
    async def search_activities(
        self,
        activity_filter: ActivityFilter,
        *,
        order: ActivityOrder = NEWEST_FIRST,
        limit: int = 50,
        offset: int = 0,
    ) -> ActivityPage:
        """The page ``offset``/``limit`` of the activities ``activity_filter`` finds, in
        ``order``, and how many it finds in all. Their activities have no laps.
        """

    @abstractmethod
    async def weekly_totals(
        self, user_id: str, *, first_week_start: date, weeks: int
    ) -> list[WeekTotals]:
        """The user's distance, duration and elevation gain summed by Monday-based week,
        oldest first, one entry per week from ``first_week_start`` for ``weeks`` weeks. A
        week without activities is zero, not left out. Totals are over every source.
        """

    @abstractmethod
    async def get_by_id(
        self, activity_id: str, *, user_id: str | None = None
    ) -> ActivityRecord | None: ...

    @abstractmethod
    async def get_and_lock_by_id(
        self, activity_id: str, *, user_id: str | None = None
    ) -> ActivityRecord | None:
        """``get_by_id``, locking the activity until the transaction ends.

        Another transaction's ``get_and_lock_by_id``, update or delete of the same
        activity waits for the lock. Plain reads don't.
        """

    @abstractmethod
    async def is_stored(self, user_id: str, activity_key: str) -> bool:
        """Whether the user has an activity stored under ``activity_key``."""

    @abstractmethod
    async def get_laps(
        self, activity_id: str, *, user_id: str | None = None
    ) -> list[Lap] | None: ...

    @abstractmethod
    async def get_streams(
        self,
        activity_id: str,
        *,
        user_id: str | None = None,
        stream_types: Iterable[StreamType] | None = None,
    ) -> dict[str, list] | None:
        """The activity's ``stream_types`` (all of them when None) as ``{stream type:
        samples}``, each in its ``StreamType`` unit; a stream the activity lacks is left
        out. None when the activity isn't found.
        """

    @abstractmethod
    async def get_raw_payload(self, activity_id: str, *, user_id: str | None = None) -> dict | None:
        """The raw provider payload the activity was saved with, the newest when it has
        several kinds; None when it has none or isn't found."""

    @abstractmethod
    async def update_activity(
        self,
        activity_id: str,
        activity: Activity,
        *,
        summary: Summary,
        user_id: str | None = None,
    ) -> ActivityRecord | None:
        """Replace the stored activity's fields and summary, and set the type of every
        version of each of its laps. Lap distances and the other measured lap values are not
        written; neither are its device name, raw payload and streams. None when the activity
        isn't found.
        """

    @abstractmethod
    async def set_lap_distances(
        self, activity_id: str, distances: Mapping[int, float], *, user_id: str | None = None
    ) -> ActivityRecord | None:
        """Store the user's ``distances`` (``Lap.index`` -> m) as the edited version of
        those laps: the imported version with the distance replaced and the speed over its
        duration (None without a duration). An edited version already stored is updated.
        None when the activity isn't found; raises ``ValueError`` for an index the activity
        has no lap at, writing nothing.
        """

    @abstractmethod
    async def reset_lap_distances(
        self,
        activity_id: str,
        lap_indexes: Iterable[int] | None = None,
        *,
        user_id: str | None = None,
    ) -> ActivityRecord | None:
        """Delete the edited version of the laps at ``lap_indexes``, or of every lap when
        None. None when the activity isn't found; raises ``ValueError`` for an index the
        activity has no lap at, writing nothing.
        """

    @abstractmethod
    async def update_summary(
        self, activity_id: str, summary: Summary, *, user_id: str | None = None
    ) -> ActivityRecord | None:
        """Replace the stored activity's summary; everything else about it is kept. None
        when the activity isn't found.
        """

    @abstractmethod
    async def save(
        self,
        record: ActivityRecord,
        *,
        raw_payload: dict | None = None,
        payload_kind: str | None = None,  # activity_raw_payloads.payload_kind, e.g. 'strava_detail'
        streams: dict | None = None,
    ) -> bool:
        """Insert ``record``, its laps as imported versions, ``raw_payload`` under
        ``payload_kind`` and ``streams``, unless its user already has an activity under
        its key, which is then left untouched. Returns whether it was inserted. A
        ``raw_payload`` needs a ``payload_kind``.
        """

    @abstractmethod
    async def delete(self, activity_id: str, *, user_id: str | None = None) -> bool: ...
