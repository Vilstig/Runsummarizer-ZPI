from dataclasses import asdict, fields
from datetime import datetime

from sqlalchemy import exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Activity, HrZones, User
from app.db.protocols import AsyncHeartRateZonesRepository
from app.domain.errors import UserNotFoundError
from app.domain.models import HeartRateZones, HeartRateZonesRecord

hr_zones = HrZones.__table__
activities = Activity.__table__
users = User.__table__

# columns named after the HeartRateZones fields
_ZONE_COLUMNS = [hr_zones.c[field.name] for field in fields(HeartRateZones)]


def _record(row) -> HeartRateZonesRecord:
    return HeartRateZonesRecord(
        valid_from=row.valid_from,
        zones=HeartRateZones(
            **{column.name: row._mapping[column.name] for column in _ZONE_COLUMNS}
        ),
    )


class PostgresHeartRateZonesRepository(AsyncHeartRateZonesRepository):
    """Postgres store for ``AsyncHeartRateZonesRepository``."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(
        self, user_id: str, zones: HeartRateZones, *, now: datetime
    ) -> HeartRateZonesRecord:
        locked = (
            await self._session.execute(
                select(users.c.id).where(users.c.id == user_id).with_for_update()
            )
        ).first()
        if locked is None:
            raise UserNotFoundError("User does not exist")

        latest = (
            await self._session.execute(
                select(hr_zones.c.id, hr_zones.c.valid_from)
                .where(hr_zones.c.user_id == user_id)
                .order_by(hr_zones.c.valid_from.desc())
                .limit(1)
            )
        ).first()

        values = {**asdict(zones), "valid_from": now}
        if latest is not None and not await self._has_activity_since(user_id, latest.valid_from):
            stmt = update(hr_zones).where(hr_zones.c.id == latest.id).values(values)
        else:
            stmt = insert(hr_zones).values(user_id=user_id, **values)

        async with self._session.begin_nested():
            row = (
                await self._session.execute(stmt.returning(hr_zones.c.valid_from, *_ZONE_COLUMNS))
            ).one()
        return _record(row)

    async def list_history(self, user_id: str) -> list[HeartRateZonesRecord]:
        rows = await self._session.execute(
            select(hr_zones.c.valid_from, *_ZONE_COLUMNS)
            .where(hr_zones.c.user_id == user_id)
            .order_by(hr_zones.c.valid_from)
        )
        return [_record(row) for row in rows]

    async def get_current(self, user_id: str) -> HeartRateZonesRecord | None:
        row = (
            await self._session.execute(
                select(hr_zones.c.valid_from, *_ZONE_COLUMNS)
                .where(hr_zones.c.user_id == user_id)
                .order_by(hr_zones.c.valid_from.desc())
                .limit(1)
            )
        ).first()
        return None if row is None else _record(row)

    async def _has_activity_since(self, user_id: str, since: datetime) -> bool:
        """Whether an activity of the user was added at or after ``since``."""
        return (
            await self._session.execute(
                select(
                    exists().where(
                        activities.c.user_id == user_id, activities.c.created_at >= since
                    )
                )
            )
        ).scalar_one()
