from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderAccount
from app.db.models.provider_account import CONNECTED_USER_INDEX
from app.db.protocols import AsyncProviderRepository
from app.db.protocols.provider import LinkedAccount
from app.domain.enums import Provider
from app.domain.errors import (
    AnotherProviderConnectedError,
    ProviderAccountTakenError,
    UserNotFoundError,
)
from app.domain.models import ProviderCredentials

provider_accounts = ProviderAccount.__table__

FOREIGN_KEY_VIOLATION = "23503"  # Postgres SQLSTATE
UNIQUE_VIOLATION = "23505"  # Postgres SQLSTATE


def _credential_columns(credentials: ProviderCredentials) -> dict:
    expires_at = credentials.expires_at
    return {
        "access_token": credentials.access_token,
        "refresh_token": credentials.refresh_token,
        "expires_at": None if expires_at is None else datetime.fromtimestamp(expires_at, UTC),
    }


def _constraint_name(exc: IntegrityError) -> str | None:
    """The name of the constraint or index ``exc`` violated, as asyncpg reports it."""
    return getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)


class PostgresProviderRepository(AsyncProviderRepository):
    """Postgres store for ``AsyncProviderRepository``.

    Stored provider tokens are decrypted only by ``get_provider_credentials`` and
    ``get_and_lock_provider_credentials``.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_provider_user_id(
        self, provider: Provider, provider_user_id: str
    ) -> str | None:
        return (
            await self._session.execute(
                select(provider_accounts.c.user_id).where(
                    provider_accounts.c.provider == provider.value,
                    provider_accounts.c.provider_user_id == provider_user_id,
                )
            )
        ).scalar_one_or_none()

    async def get_connected_user_id(self, provider: Provider, provider_user_id: str) -> str | None:
        return (
            await self._session.execute(
                select(provider_accounts.c.user_id).where(
                    provider_accounts.c.provider == provider.value,
                    provider_accounts.c.provider_user_id == provider_user_id,
                    provider_accounts.c.connected_at.is_not(None),
                )
            )
        ).scalar_one_or_none()

    async def get_connected_provider(self, user_id: str) -> Provider | None:
        provider = (
            await self._session.execute(
                select(provider_accounts.c.provider).where(
                    provider_accounts.c.user_id == user_id,
                    provider_accounts.c.connected_at.is_not(None),
                )
            )
        ).scalar_one_or_none()
        return None if provider is None else Provider(provider)

    async def list_accounts(self, user_id: str) -> list[LinkedAccount]:
        a = provider_accounts.c
        rows = await self._session.execute(
            select(a.provider, a.connected_at, a.sync_requested_at)
            .where(a.user_id == user_id)
            .order_by(a.provider)
        )
        return [
            LinkedAccount(
                provider=Provider(row.provider),
                connected=row.connected_at is not None,
                sync_requested_at=row.sync_requested_at,
            )
            for row in rows
        ]

    async def link_provider(
        self,
        *,
        provider: Provider,
        user_id: str,
        provider_user_id: str,
        credentials: ProviderCredentials,
    ) -> None:
        insert_account = insert(provider_accounts).values(
            user_id=user_id,
            provider=provider.value,
            provider_user_id=provider_user_id,
            connected_at=func.now(),
            **_credential_columns(credentials),
        )
        upsert = insert_account.on_conflict_do_update(
            index_elements=[provider_accounts.c.user_id, provider_accounts.c.provider],
            set_={
                "provider_user_id": insert_account.excluded.provider_user_id,
                "access_token": insert_account.excluded.access_token,
                "refresh_token": insert_account.excluded.refresh_token,
                "expires_at": insert_account.excluded.expires_at,
                "connected_at": insert_account.excluded.connected_at,
                "updated_at": func.now(),
            },
        )

        try:
            async with self._session.begin_nested():
                await self._session.execute(upsert)
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate == FOREIGN_KEY_VIOLATION:
                raise UserNotFoundError("User does not exist") from exc
            if sqlstate == UNIQUE_VIOLATION:
                if _constraint_name(exc) == CONNECTED_USER_INDEX:
                    raise AnotherProviderConnectedError(
                        "User is connected to another provider"
                    ) from exc
                raise ProviderAccountTakenError(
                    "Provider account is already linked to another user"
                ) from exc
            raise

    async def update_provider_tokens(
        self,
        *,
        provider: Provider,
        user_id: str,
        credentials: ProviderCredentials,
    ) -> bool:
        result = await self._session.execute(
            update(provider_accounts)
            .where(
                provider_accounts.c.user_id == user_id,
                provider_accounts.c.provider == provider.value,
            )
            .values(
                **_credential_columns(credentials),
                updated_at=func.now(),
            )
        )
        return result.rowcount > 0

    async def get_provider_credentials(
        self, *, provider: Provider, user_id: str
    ) -> ProviderCredentials | None:
        return await self._read_credentials(provider, user_id, lock=False)

    async def get_and_lock_provider_credentials(
        self, *, provider: Provider, user_id: str
    ) -> ProviderCredentials | None:
        return await self._read_credentials(provider, user_id, lock=True)

    async def list_users_with_expired_tokens(
        self, provider: Provider, *, expired_before: datetime, limit: int
    ) -> list[str]:
        a = provider_accounts.c
        rows = await self._session.execute(
            select(a.user_id)
            .where(
                a.provider == provider.value,
                a.connected_at.is_not(None),
                a.access_token.is_not(None),
                a.expires_at < expired_before,
            )
            .order_by(a.expires_at, a.user_id)
            .limit(limit)
        )
        return list(rows.scalars())

    async def clear_provider_credentials(self, *, provider: Provider, user_id: str) -> bool:
        result = await self._session.execute(
            update(provider_accounts)
            .where(
                provider_accounts.c.user_id == user_id,
                provider_accounts.c.provider == provider.value,
            )
            .values(
                access_token=None,
                refresh_token=None,
                expires_at=None,
                scopes=None,
                sync_requested_at=None,
                connected_at=None,
                updated_at=func.now(),
            )
        )
        return result.rowcount > 0

    async def request_sync(self, *, provider: Provider, user_id: str, now: datetime) -> bool:
        result = await self._session.execute(
            update(provider_accounts)
            .where(
                provider_accounts.c.user_id == user_id,
                provider_accounts.c.provider == provider.value,
            )
            .values(sync_requested_at=now)
        )
        return result.rowcount > 0

    async def get_sync_requested_at(self, *, provider: Provider, user_id: str) -> datetime | None:
        return (
            await self._session.execute(
                select(provider_accounts.c.sync_requested_at).where(
                    provider_accounts.c.user_id == user_id,
                    provider_accounts.c.provider == provider.value,
                )
            )
        ).scalar_one_or_none()

    async def clear_sync_request(self, *, provider: Provider, user_id: str) -> None:
        await self._session.execute(
            update(provider_accounts)
            .where(
                provider_accounts.c.user_id == user_id,
                provider_accounts.c.provider == provider.value,
                provider_accounts.c.sync_requested_at.is_not(None),
            )
            .values(sync_requested_at=None)
        )

    async def _read_credentials(
        self, provider: Provider, user_id: str, *, lock: bool
    ) -> ProviderCredentials | None:
        query = select(
            provider_accounts.c.access_token,
            provider_accounts.c.refresh_token,
            provider_accounts.c.expires_at,
        ).where(
            provider_accounts.c.user_id == user_id,
            provider_accounts.c.provider == provider.value,
        )
        if lock:
            query = query.with_for_update()
        row = (await self._session.execute(query)).first()

        if row is None or row.access_token is None:
            return None

        return ProviderCredentials(
            access_token=row.access_token,
            refresh_token=row.refresh_token,
            expires_at=None if row.expires_at is None else int(row.expires_at.timestamp()),
        )
