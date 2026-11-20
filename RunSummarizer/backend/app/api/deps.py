import logging
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clerk_auth import authenticate_clerk_request
from app.db.client import open_session
from app.db.factory import (
    create_async_activity_repository,
    create_async_hr_zones_repository,
    create_async_import_queue_repository,
    create_async_provider_repository,
    create_async_user_repository,
)
from app.db.protocols import (
    AsyncActivityRepository,
    AsyncHeartRateZonesRepository,
    AsyncImportQueueRepository,
    AsyncProviderRepository,
    AsyncUserRepository,
)
from app.domain.enums import Provider
from app.domain.errors import ProviderNotSupportedError
from app.providers.base import ProviderDefinition
from app.providers.registry import PROVIDERS
from app.services.accounts.connection import ProviderConnectionService
from app.services.accounts.deletion import AccountDeletionService
from app.services.accounts.provider_account_service import ProviderAccountService
from app.services.activity_service import ActivityService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)


async def get_session() -> AsyncIterator[AsyncSession]:
    """A Postgres session for the request, committed once the handler returns.

    An exception from the handler skips the commit, and closing the session rolls
    the transaction back.
    """
    async with open_session() as session:
        yield session


# ``scope="function"`` commits the session before the response is sent.
async def get_async_activity_repository(
    session: AsyncSession = Depends(get_session, scope="function"),
) -> AsyncActivityRepository:
    return create_async_activity_repository(session)


async def get_async_user_repository(
    session: AsyncSession = Depends(get_session, scope="function"),
) -> AsyncUserRepository:
    return create_async_user_repository(session)


async def get_async_hr_zones_repository(
    session: AsyncSession = Depends(get_session, scope="function"),
) -> AsyncHeartRateZonesRepository:
    return create_async_hr_zones_repository(session)


async def get_async_import_queue_repository(
    session: AsyncSession = Depends(get_session, scope="function"),
) -> AsyncImportQueueRepository:
    return create_async_import_queue_repository(session)


async def get_async_provider_repository(
    session: AsyncSession = Depends(get_session, scope="function"),
) -> AsyncProviderRepository:
    return create_async_provider_repository(session)


def get_activity_service(
    repo: AsyncActivityRepository = Depends(get_async_activity_repository),
) -> ActivityService:
    return ActivityService(repo)


def get_user_service(
    repo: AsyncUserRepository = Depends(get_async_user_repository),
    hr_zones_repo: AsyncHeartRateZonesRepository = Depends(get_async_hr_zones_repository),
) -> UserService:
    return UserService(repo, hr_zones_repo)


def get_account_deletion_service(
    user_repo: AsyncUserRepository = Depends(get_async_user_repository),
    provider_repo: AsyncProviderRepository = Depends(get_async_provider_repository),
) -> AccountDeletionService:
    return AccountDeletionService(user_repo, provider_repo)


def get_configured_provider(provider: Provider) -> ProviderDefinition:
    """The definition of ``provider``. A provider that isn't registered, or lacks its
    settings, raises ``ProviderNotSupportedError``.
    """
    definition = PROVIDERS.get(provider)
    if definition is not None and not definition.is_configured():
        logger.warning("%s is registered but not configured: its settings are missing", provider)
        definition = None
    if definition is None:
        raise ProviderNotSupportedError("Provider not supported")
    return definition


def get_provider_account_service(
    definition: ProviderDefinition = Depends(get_configured_provider),
    user_repo: AsyncUserRepository = Depends(get_async_user_repository),
    provider_repo: AsyncProviderRepository = Depends(get_async_provider_repository),
) -> ProviderAccountService:
    return ProviderAccountService(definition, user_repo, provider_repo)


def get_provider_connection_service(
    accounts: ProviderAccountService = Depends(get_provider_account_service),
    import_queue: AsyncImportQueueRepository = Depends(get_async_import_queue_repository),
) -> ProviderConnectionService:
    return ProviderConnectionService(accounts, import_queue)


_bearer = HTTPBearer()


def require_user(request: Request, _creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    state = authenticate_clerk_request(request)

    if not state.is_signed_in:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=state.message or "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return state.payload["sub"]
