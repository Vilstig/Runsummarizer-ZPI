from dataclasses import asdict, fields

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.protocols import AsyncUserRepository
from app.domain.enums import Sex
from app.domain.models import UserProfile

users = User.__table__

# columns named after the UserProfile fields
_PROFILE_COLUMNS = [users.c[field.name] for field in fields(UserProfile)]


class PostgresUserRepository(AsyncUserRepository):
    """Postgres store for ``AsyncUserRepository``."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def ensure_user_exists(self, user_id: str) -> None:
        if not user_id:
            raise ValueError("user_id can not be empty")

        await self._session.execute(
            insert(users).values(id=user_id).on_conflict_do_nothing(index_elements=[users.c.id])
        )

    async def lock_user(self, user_id: str) -> None:
        await self.ensure_user_exists(user_id)
        await self._session.execute(
            select(users.c.id).where(users.c.id == user_id).with_for_update()
        )

    async def delete_user(self, user_id: str) -> None:
        await self._session.execute(delete(users).where(users.c.id == user_id))

    async def upsert_profile(self, user_id: str, profile: UserProfile) -> None:
        if not user_id:
            raise ValueError("user_id can not be empty")

        stmt = insert(users).values(id=user_id, **asdict(profile))
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[users.c.id],
                set_={column.name: stmt.excluded[column.name] for column in _PROFILE_COLUMNS},
            )
        )

    async def get_profile(self, user_id: str) -> UserProfile | None:
        row = (
            await self._session.execute(select(*_PROFILE_COLUMNS).where(users.c.id == user_id))
        ).one_or_none()
        if row is None:
            return None
        data = dict(row._mapping)
        if data["sex"] is not None:
            data["sex"] = Sex(data["sex"])
        return UserProfile(**data)
