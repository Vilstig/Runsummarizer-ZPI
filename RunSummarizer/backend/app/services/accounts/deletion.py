"""Deleting a user's account, after revoking their provider authorization."""

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from app.db.protocols.provider import AsyncProviderRepository
from app.db.protocols.user import AsyncUserRepository
from app.domain.enums import Provider
from app.domain.errors import RateLimitedError
from app.providers.base import ProviderDefinition
from app.providers.registry import PROVIDERS
from app.services.accounts.provider_account_service import (
    FreshCredentials,
    ProviderAccountService,
)
from app.services.budget import pause_provider_calls
from app.services.credentials import fresh_credentials

logger = logging.getLogger(__name__)


class AccountDeletionService:
    """Deletes users, first disconnecting the provider they are connected to.

    ``providers`` replaces the registry; ``fresh_credentials`` and ``pause_calls``
    replace ``app.services.credentials.fresh_credentials`` and
    ``app.services.budget.pause_provider_calls``.
    """

    def __init__(
        self,
        user_repo: AsyncUserRepository,
        provider_repo: AsyncProviderRepository,
        *,
        providers: Mapping[Provider, ProviderDefinition] = PROVIDERS,
        fresh_credentials: FreshCredentials = fresh_credentials,
        pause_calls: Callable[[Provider, datetime], Awaitable[None]] = pause_provider_calls,
    ):
        self.user_repo = user_repo
        self.provider_repo = provider_repo
        self._providers = providers
        self._fresh_credentials = fresh_credentials
        self._pause_calls = pause_calls

    async def delete(self, user_id: str) -> None:
        """Revoke the user's authorization with their connected provider, as a
        disconnect does, then delete the user and everything stored for them.

        An authorization the provider already revoked, or a user connected to no
        provider, is deleted all the same. A provider that isn't registered or
        configured can't be called: the user is deleted without a revocation, and a
        warning is logged. Any other provider error propagates before anything is
        deleted; a ``RateLimitedError`` first pauses the provider's calls until it ends.
        """
        provider = await self.provider_repo.get_connected_provider(user_id)
        if provider is not None:
            definition = self._providers.get(provider)
            if definition is None or not definition.is_configured():
                logger.warning(
                    "deleting user %s without revoking their %s authorization: the provider "
                    "isn't configured",
                    user_id,
                    provider,
                )
            else:
                accounts = ProviderAccountService(
                    definition,
                    self.user_repo,
                    self.provider_repo,
                    fresh_credentials=self._fresh_credentials,
                )
                try:
                    await accounts.disconnect(user_id)
                except RateLimitedError as exc:
                    await self._pause_calls(provider, exc.until)
                    raise
        await self.user_repo.delete_user(user_id)
