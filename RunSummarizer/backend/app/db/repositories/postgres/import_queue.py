import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import (
    ColumnElement,
    SmallInteger,
    Text,
    and_,
    case,
    delete,
    exists,
    func,
    literal,
    or_,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Activity, ImportItem
from app.db.protocols.import_queue import (
    AsyncImportQueueRepository,
    Claim,
    FinishOutcome,
    ImportFailure,
    QueuedItem,
)
from app.domain.enums import (
    ImportErrorCode,
    ImportPriority,
    ImportSource,
    ImportStatus,
)

import_items = ImportItem.__table__
activities = Activity.__table__


def _user_items(user_id: str, provider: str) -> ColumnElement[bool]:
    """The clause selecting the user's items for ``provider``."""
    i = import_items.c
    return and_(i.user_id == user_id, i.provider == provider)


def _selected(activity_keys: Sequence[str] | None) -> ColumnElement[bool]:
    """The clause selecting ``activity_keys``; every item when None."""
    if activity_keys is None:
        return true()
    return import_items.c.activity_key.in_(list(activity_keys))


def _claimed(claim: Claim) -> ColumnElement[bool]:
    """The clause selecting the claimed item while it carries the claim's lease token."""
    i = import_items.c
    return and_(
        i.user_id == claim.user_id,
        i.provider == claim.provider,
        i.activity_key == claim.activity_key,
        i.lease_token == claim.lease_token,
    )


class PostgresImportQueueRepository(AsyncImportQueueRepository):
    """Postgres store for ``AsyncImportQueueRepository``, in ``import_items``."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def enqueue_sync(
        self,
        user_id: str,
        provider: str,
        activity_keys: Sequence[str],
        *,
        spacing: timedelta,
        now: datetime,
    ) -> int:
        keys = list(dict.fromkeys(activity_keys))
        if not keys:
            return 0
        i, a = import_items.c, activities.c

        last_queued = (
            select(func.max(i.sort_key))
            .where(i.user_id == user_id, i.provider == provider, i.status == ImportStatus.QUEUED)
            .scalar_subquery()
        )
        start = func.greatest(now, func.coalesce(last_queued, now))
        # ids.n is the key's 1-based position in ``keys``
        ids = (
            func.unnest(literal(keys, ARRAY(Text)))
            .table_valued("activity_key", with_ordinality="n")
            .render_derived(name="ids")
        )
        stored = exists().where(
            a.user_id == user_id, a.source == provider, a.activity_key == ids.c.activity_key
        )
        rows = select(
            literal(user_id, Text),
            literal(provider, Text),
            ids.c.activity_key,
            literal(ImportSource.SYNC, Text),
            literal(ImportPriority.SYNC, SmallInteger),
            start + ids.c.n * spacing,
            literal(ImportStatus.QUEUED, Text),
            literal(now),
            literal(now),
            literal(now),
        ).where(~stored)
        statement = (
            insert(import_items)
            .from_select(
                [
                    i.user_id,
                    i.provider,
                    i.activity_key,
                    i.source,
                    i.priority,
                    i.sort_key,
                    i.status,
                    i.run_after,
                    i.created_at,
                    i.updated_at,
                ],
                rows,
            )
            .on_conflict_do_nothing(index_elements=[i.user_id, i.provider, i.activity_key])
            .returning(i.activity_key)
        )
        return len((await self._session.execute(statement)).all())

    async def enqueue_webhook(
        self,
        user_id: str,
        provider: str,
        activity_key: str,
        *,
        sent_data: dict | None = None,
        now: datetime,
    ) -> None:
        i = import_items.c
        stmt = insert(import_items).values(
            user_id=user_id,
            provider=provider,
            activity_key=activity_key,
            source=ImportSource.WEBHOOK,
            priority=ImportPriority.WEBHOOK,
            sort_key=now,
            status=ImportStatus.QUEUED,
            run_after=now,
            sent_data=sent_data,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[i.user_id, i.provider, i.activity_key],
            set_={
                "generation": i.generation + 1,
                "source": ImportSource.WEBHOOK,
                "priority": func.least(i.priority, ImportPriority.WEBHOOK),
                "sort_key": func.least(i.sort_key, now),
                "status": case(
                    (i.status == ImportStatus.RUNNING, i.status),
                    else_=literal(ImportStatus.QUEUED, Text),
                ),
                "attempts": case(
                    (i.status.in_([ImportStatus.DEAD, ImportStatus.BLOCKED]), 0),
                    else_=i.attempts,
                ),
                "run_after": case(
                    (i.status.in_([ImportStatus.DEAD, ImportStatus.BLOCKED]), now),
                    else_=i.run_after,
                ),
                "raw_payload": None,
                "sent_data": stmt.excluded.sent_data,
                "updated_at": now,
            },
        )
        await self._session.execute(stmt)

    async def lock_next(
        self, provider: str, *, now: datetime, saved_payload_only: bool = False
    ) -> QueuedItem | None:
        i = import_items.c
        query = select(
            i.user_id,
            i.provider,
            i.activity_key,
            i.source,
            i.priority,
            i.generation,
            i.raw_payload,
            i.sent_data,
        ).where(
            i.provider == provider,
            i.status == ImportStatus.QUEUED,
            i.run_after <= now,
        )
        if saved_payload_only:
            query = query.where(i.raw_payload.is_not(None))
        row = (
            await self._session.execute(
                query.order_by(i.priority, i.sort_key).limit(1).with_for_update(skip_locked=True)
            )
        ).first()
        if row is None:
            return None
        return QueuedItem(
            user_id=str(row.user_id),
            provider=row.provider,
            activity_key=row.activity_key,
            source=ImportSource(row.source),
            priority=ImportPriority(row.priority),
            generation=row.generation,
            raw_payload=row.raw_payload,
            sent_data=row.sent_data,
        )

    async def claim(self, item: QueuedItem, *, lease: timedelta, now: datetime) -> Claim:
        i = import_items.c
        lease_token = uuid.uuid4()
        attempts = (
            await self._session.execute(
                update(import_items)
                .where(
                    i.user_id == item.user_id,
                    i.provider == item.provider,
                    i.activity_key == item.activity_key,
                    i.status == ImportStatus.QUEUED,
                    i.generation == item.generation,
                )
                .values(
                    status=ImportStatus.RUNNING,
                    attempts=i.attempts + 1,
                    lease_until=now + lease,
                    lease_token=lease_token,
                    updated_at=now,
                )
                .returning(i.attempts)
            )
        ).scalar_one()
        return Claim(
            user_id=item.user_id,
            provider=item.provider,
            activity_key=item.activity_key,
            generation=item.generation,
            attempts=attempts,
            lease_token=lease_token,
            sent_data=item.sent_data,
        )

    async def save_payload(self, claim: Claim, raw_payload: dict, *, now: datetime) -> bool:
        i = import_items.c
        result = await self._session.execute(
            update(import_items)
            .where(_claimed(claim))
            .values(
                # kept (NULL) when a webhook queued the item again during the run
                raw_payload=case(
                    (i.generation == claim.generation, literal(raw_payload, JSONB)),
                    else_=i.raw_payload,
                ),
                updated_at=now,
            )
        )
        return result.rowcount > 0

    async def finish(self, claim: Claim, *, now: datetime) -> FinishOutcome:
        i = import_items.c
        deleted = await self._session.execute(
            delete(import_items).where(_claimed(claim), i.generation == claim.generation)
        )
        if deleted.rowcount:
            return FinishOutcome.DONE
        requeued = await self._session.execute(
            update(import_items)
            .where(_claimed(claim))
            .values(
                status=ImportStatus.QUEUED,
                attempts=0,
                lease_token=None,
                lease_until=None,
                run_after=now,
                updated_at=now,
            )
        )
        return FinishOutcome.REQUEUED if requeued.rowcount else FinishOutcome.LOST

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
        return await self._fail(
            claim,
            status=ImportStatus.QUEUED,
            error_code=error_code,
            last_error=last_error,
            raw_payload=raw_payload,
            now=now,
            run_after=run_after,
        )

    async def mark_dead(
        self,
        claim: Claim,
        *,
        error_code: ImportErrorCode,
        last_error: str,
        raw_payload: dict | None = None,
        now: datetime,
    ) -> bool:
        return await self._fail(
            claim,
            status=ImportStatus.DEAD,
            error_code=error_code,
            last_error=last_error,
            raw_payload=raw_payload,
            now=now,
        )

    async def release(self, claim: Claim, *, run_after: datetime, now: datetime) -> bool:
        i = import_items.c
        result = await self._session.execute(
            update(import_items)
            .where(_claimed(claim))
            .values(
                status=ImportStatus.QUEUED,
                attempts=i.attempts - 1,
                lease_token=None,
                lease_until=None,
                run_after=run_after,
                updated_at=now,
            )
        )
        return result.rowcount > 0

    async def block(self, claim: Claim, *, last_error: str, now: datetime) -> int:
        i = import_items.c
        claimed = and_(i.activity_key == claim.activity_key, i.lease_token == claim.lease_token)
        result = await self._session.execute(
            update(import_items)
            .where(
                _user_items(claim.user_id, claim.provider),
                or_(i.status == ImportStatus.QUEUED, claimed),
            )
            .values(
                status=ImportStatus.BLOCKED,
                error_code=ImportErrorCode.AUTHORIZATION_REVOKED,
                last_error=case((claimed, last_error), else_=i.last_error),
                lease_token=None,
                lease_until=None,
                updated_at=now,
            )
        )
        return result.rowcount

    async def unblock(self, user_id: str, provider: str, *, now: datetime) -> int:
        return await self._requeue(user_id, provider, ImportStatus.BLOCKED, None, now)

    async def retry_failures(
        self,
        user_id: str,
        provider: str,
        *,
        activity_keys: Sequence[str] | None = None,
        now: datetime,
    ) -> int:
        return await self._requeue(user_id, provider, ImportStatus.DEAD, activity_keys, now)

    async def dismiss_failures(
        self, user_id: str, provider: str, *, activity_keys: Sequence[str] | None = None
    ) -> int:
        i = import_items.c
        result = await self._session.execute(
            delete(import_items).where(
                _user_items(user_id, provider),
                i.status == ImportStatus.DEAD,
                _selected(activity_keys),
            )
        )
        return result.rowcount

    async def delete(self, user_id: str, provider: str, activity_key: str) -> bool:
        result = await self._session.execute(
            delete(import_items).where(
                _user_items(user_id, provider), import_items.c.activity_key == activity_key
            )
        )
        return result.rowcount > 0

    async def delete_user_items(self, user_id: str, provider: str) -> int:
        result = await self._session.execute(
            delete(import_items).where(_user_items(user_id, provider))
        )
        return result.rowcount

    async def count_by_status(self, user_id: str, provider: str) -> dict[ImportStatus, int]:
        i = import_items.c
        rows = await self._session.execute(
            select(i.status, func.count()).where(_user_items(user_id, provider)).group_by(i.status)
        )
        counts = dict.fromkeys(ImportStatus, 0)
        counts.update({ImportStatus(status): count for status, count in rows})
        return counts

    async def count_by_status_per_provider(
        self, user_id: str
    ) -> dict[str, dict[ImportStatus, int]]:
        i = import_items.c
        rows = await self._session.execute(
            select(i.provider, i.status, func.count())
            .where(i.user_id == user_id)
            .group_by(i.provider, i.status)
        )
        counts: dict[str, dict[ImportStatus, int]] = {}
        for provider, status, count in rows:
            counts.setdefault(provider, dict.fromkeys(ImportStatus, 0))[ImportStatus(status)] = (
                count
            )
        return counts

    async def recent_failures(
        self, user_id: str, provider: str, *, limit: int = 20
    ) -> list[ImportFailure]:
        i = import_items.c
        rows = await self._session.execute(
            select(i.activity_key, i.error_code, i.attempts, i.updated_at)
            .where(_user_items(user_id, provider), i.status == ImportStatus.DEAD)
            .order_by(i.updated_at.desc(), i.activity_key)
            .limit(limit)
        )
        return [
            ImportFailure(
                activity_key=row.activity_key,
                error_code=ImportErrorCode(row.error_code) if row.error_code else None,
                attempts=row.attempts,
                failed_at=row.updated_at,
            )
            for row in rows
        ]

    async def earliest_run_after(
        self, user_id: str, provider: str
    ) -> dict[ImportPriority, datetime]:
        i = import_items.c
        rows = await self._session.execute(
            select(i.priority, func.min(i.run_after))
            .where(_user_items(user_id, provider), i.status == ImportStatus.QUEUED)
            .group_by(i.priority)
        )
        return {ImportPriority(priority): run_after for priority, run_after in rows}

    async def expire_leases(self, provider: str, *, max_attempts: int, now: datetime) -> int:
        i = import_items.c
        out_of_attempts = i.attempts >= max_attempts
        result = await self._session.execute(
            update(import_items)
            .where(
                i.provider == provider,
                i.status == ImportStatus.RUNNING,
                i.lease_until < now,
            )
            .values(
                status=case(
                    (out_of_attempts, literal(ImportStatus.DEAD, Text)),
                    else_=literal(ImportStatus.QUEUED, Text),
                ),
                error_code=case(
                    (out_of_attempts, literal(ImportErrorCode.WORKER_LOST, Text)),
                    else_=i.error_code,
                ),
                lease_token=None,
                lease_until=None,
                run_after=now,
                updated_at=now,
            )
        )
        return result.rowcount

    async def purge_failures(self, provider: str, *, max_age: timedelta, now: datetime) -> int:
        i = import_items.c
        result = await self._session.execute(
            delete(import_items).where(
                i.provider == provider,
                i.status.in_([ImportStatus.DEAD, ImportStatus.BLOCKED]),
                i.updated_at < now - max_age,
            )
        )
        return result.rowcount

    async def _fail(
        self,
        claim: Claim,
        *,
        status: ImportStatus,
        error_code: ImportErrorCode,
        last_error: str,
        raw_payload: dict | None,
        now: datetime,
        run_after: datetime | None = None,
    ) -> bool:
        """Move the claimed item to ``status`` with the error, while the lease is held."""
        i = import_items.c
        values = {
            "status": status,
            "error_code": error_code,
            "last_error": last_error,
            "lease_token": None,
            "lease_until": None,
            "updated_at": now,
        }
        if run_after is not None:
            values["run_after"] = run_after
        if raw_payload is not None:
            # NULL when a webhook queued the item again during the run
            values["raw_payload"] = case(
                (i.generation == claim.generation, literal(raw_payload, JSONB))
            )
        result = await self._session.execute(
            update(import_items).where(_claimed(claim)).values(values)
        )
        return result.rowcount > 0

    async def _requeue(
        self,
        user_id: str,
        provider: str,
        status: ImportStatus,
        activity_keys: Sequence[str] | None,
        now: datetime,
    ) -> int:
        """Queue the user's ``status`` items again, claimable from ``now`` with 0 attempts."""
        i = import_items.c
        result = await self._session.execute(
            update(import_items)
            .where(_user_items(user_id, provider), i.status == status, _selected(activity_keys))
            .values(status=ImportStatus.QUEUED, attempts=0, run_after=now, updated_at=now)
        )
        return result.rowcount
