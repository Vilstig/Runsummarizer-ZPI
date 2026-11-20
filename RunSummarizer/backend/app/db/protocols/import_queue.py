import uuid
from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from app.domain.enums import (
    ImportErrorCode,
    ImportPriority,
    ImportSource,
    ImportStatus,
)


@dataclass(frozen=True)
class QueuedItem:
    """A claimable item, locked by ``lock_next`` until the transaction ends."""

    user_id: str
    provider: str  # 'strava' | 'garmin' | 'intervals'
    activity_key: str  # as in activities.activity_key
    source: ImportSource  # what last queued the item
    priority: ImportPriority
    generation: int
    raw_payload: dict | None  # provider data saved by an earlier attempt
    # what the provider sent with the webhook that last queued the item; may hold a
    # download token, so it is left out of the repr
    sent_data: dict | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Claim:
    """A running item, owned by whoever holds ``lease_token``."""

    user_id: str
    provider: str
    activity_key: str
    generation: int  # the item's generation when it was claimed
    attempts: int  # including this claim
    lease_token: uuid.UUID
    sent_data: dict | None = field(default=None, repr=False)  # as in ``QueuedItem``


class FinishOutcome(StrEnum):
    DONE = "done"  # the item was deleted
    REQUEUED = "requeued"  # a webhook queued the item again during the run; it is queued
    LOST = "lost"  # another claim owns the item, or it was deleted; nothing was written


@dataclass(frozen=True)
class ImportFailure:
    """A dead item."""

    activity_key: str
    error_code: ImportErrorCode | None
    attempts: int
    failed_at: datetime


class AsyncImportQueueRepository(Protocol):
    """Activities waiting to be imported, one item per (user, provider, activity key).

    Every method works on one ``provider`` (a ``Provider`` value). ``user_id`` is a
    Clerk user id. Methods take the current time as ``now`` (timezone-aware).

    A claim is one transaction: ``lock_next``, then the provider's budget
    reservation, then ``claim``. Every later write takes the ``Claim`` and changes
    nothing unless the item still carries its lease token.
    """

    @abstractmethod
    async def enqueue_sync(
        self,
        user_id: str,
        provider: str,
        activity_keys: Sequence[str],
        *,
        spacing: timedelta,
        now: datetime,
    ) -> int:
        """Queue a sync item for each of ``activity_keys``, claimable from ``now``.

        Keys stored as the user's activities from ``provider``, and keys that already
        have an item in any status, are skipped. The items are ordered as given,
        ``spacing`` apart, starting one ``spacing`` after the later of ``now`` and the
        user's last queued item for ``provider``. Returns the number of items queued.
        """

    @abstractmethod
    async def enqueue_webhook(
        self,
        user_id: str,
        provider: str,
        activity_key: str,
        *,
        sent_data: dict | None = None,
        now: datetime,
    ) -> None:
        """Queue a webhook item for ``activity_key``, or merge into the existing item.

        A new item is queued at webhook priority from generation 0, ordered by ``now``
        and claimable from ``now``, holding ``sent_data``. An existing item:

        - gets its generation increased by 1, ``source`` webhook and webhook priority;
        - keeps the earlier of its order and ``now``;
        - stays running if it is running, and is queued otherwise;
        - restarts from 0 attempts and is claimable from ``now`` if it was dead or
          blocked, and otherwise keeps its attempts and the time it is claimable from;
        - loses its saved raw payload;
        - holds ``sent_data`` in place of what it held.
        """

    @abstractmethod
    async def lock_next(
        self, provider: str, *, now: datetime, saved_payload_only: bool = False
    ) -> QueuedItem | None:
        """Lock the next item claimable at ``now``, or return None.

        Items are taken by priority, then in queue order. Items locked by another
        transaction are skipped. With ``saved_payload_only``, only items holding a
        saved raw payload are considered. The lock holds until the transaction ends.
        """

    @abstractmethod
    async def claim(self, item: QueuedItem, *, lease: timedelta, now: datetime) -> Claim:
        """Mark ``item`` running for ``lease`` from ``now``, under a new lease token.

        The claim uses an attempt and carries the item's ``sent_data``. ``item`` must
        have been locked by ``lock_next`` in the same transaction.
        """

    @abstractmethod
    async def save_payload(self, claim: Claim, raw_payload: dict, *, now: datetime) -> bool:
        """Save ``raw_payload`` on the claimed item, which stays running.

        It is saved only if no webhook queued the item during the run. Returns whether
        the lease was still held.
        """

    @abstractmethod
    async def finish(self, claim: Claim, *, now: datetime) -> FinishOutcome:
        """Delete the claimed item, unless a webhook queued it again during the run.

        Such an item is queued again instead, claimable from ``now`` with 0 attempts.
        ``LOST`` means the transaction should be rolled back.
        """

    @abstractmethod
    async def retry_later(
        self,
        claim: Claim,
        *,
        run_after: datetime,
        error_code: ImportErrorCode,
        last_error: str,
        raw_payload: dict | None = None,
        now: datetime,
    ) -> bool:
        """Queue the claimed item again, claimable from ``run_after``.

        ``raw_payload`` is saved only if no webhook queued the item during the run;
        without it, a saved payload is kept. Returns whether the lease was still held.
        """

    @abstractmethod
    async def mark_dead(
        self,
        claim: Claim,
        *,
        error_code: ImportErrorCode,
        last_error: str,
        raw_payload: dict | None = None,
        now: datetime,
    ) -> bool:
        """Make the claimed item dead.

        ``raw_payload`` is saved as for ``retry_later``. Returns whether the lease was
        still held.
        """

    @abstractmethod
    async def release(self, claim: Claim, *, run_after: datetime, now: datetime) -> bool:
        """Queue the claimed item again, claimable from ``run_after``, giving back the
        attempt the claim used. Returns whether the lease was still held.
        """

    @abstractmethod
    async def block(self, claim: Claim, *, last_error: str, now: datetime) -> int:
        """Block the claimed item and the user's queued items for its provider, with
        ``authorization_revoked``.

        The claimed item is blocked only while the lease is held; the queued items
        either way. Returns the number of items blocked.
        """

    @abstractmethod
    async def unblock(self, user_id: str, provider: str, *, now: datetime) -> int:
        """Queue the user's blocked items again, claimable from ``now`` with 0 attempts.
        Returns the number of items queued.
        """

    @abstractmethod
    async def retry_failures(
        self,
        user_id: str,
        provider: str,
        *,
        activity_keys: Sequence[str] | None = None,
        now: datetime,
    ) -> int:
        """Queue the user's dead items again, claimable from ``now`` with 0 attempts.

        Only ``activity_keys``, when given. Saved raw payloads are kept. Returns the
        number of items queued.
        """

    @abstractmethod
    async def dismiss_failures(
        self, user_id: str, provider: str, *, activity_keys: Sequence[str] | None = None
    ) -> int:
        """Delete the user's dead items, only ``activity_keys`` when given. Returns the
        number deleted.
        """

    @abstractmethod
    async def delete(self, user_id: str, provider: str, activity_key: str) -> bool:
        """Delete the item, whatever its status. Returns whether there was one."""

    @abstractmethod
    async def delete_user_items(self, user_id: str, provider: str) -> int:
        """Delete all the user's items for ``provider``. Returns the number deleted."""

    @abstractmethod
    async def count_by_status(self, user_id: str, provider: str) -> dict[ImportStatus, int]:
        """The number of the user's items in each status, 0 for a status with none."""

    @abstractmethod
    async def count_by_status_per_provider(
        self, user_id: str
    ) -> dict[str, dict[ImportStatus, int]]:
        """``count_by_status`` for each provider the user has items of, by provider
        (a ``Provider`` value), in one read. A provider without items is left out.
        """

    @abstractmethod
    async def recent_failures(
        self, user_id: str, provider: str, *, limit: int = 20
    ) -> list[ImportFailure]:
        """The user's dead items, the most recently failed first."""

    @abstractmethod
    async def earliest_run_after(
        self, user_id: str, provider: str
    ) -> dict[ImportPriority, datetime]:
        """The earliest time one of the user's queued items is claimable from, by
        priority. A priority without queued items is left out.
        """

    @abstractmethod
    async def expire_leases(self, provider: str, *, max_attempts: int, now: datetime) -> int:
        """Queue running items whose lease ended before ``now`` again, claimable from
        ``now``. One that has used ``max_attempts`` becomes dead with ``worker_lost``
        instead. Returns the number of items changed.
        """

    @abstractmethod
    async def purge_failures(self, provider: str, *, max_age: timedelta, now: datetime) -> int:
        """Delete dead and blocked items last changed more than ``max_age`` before
        ``now``. Returns the number deleted.
        """
