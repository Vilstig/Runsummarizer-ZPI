"""Connecting, linking and disconnecting a user's provider account, for any provider."""

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from app.db.protocols.provider import AsyncProviderRepository
from app.db.protocols.user import AsyncUserRepository
from app.domain.enums import Provider
from app.domain.errors import (
    AnotherProviderConnectedError,
    ProviderAuthorizationError,
    ProviderNotConnectedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import ProviderDefinition, TokenRefresher
from app.services.accounts.oauth_state import (
    create_oauth_state,
    open_oauth_secrets,
    seal_oauth_secrets,
    verify_oauth_state,
)
from app.services.credentials import fresh_credentials

FreshCredentials = Callable[[Provider, str, TokenRefresher | None], Awaitable[ProviderCredentials]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConnectStart:
    """What the browser needs to start a provider's authorization."""

    authorize_url: str
    state: str  # the oauth_state cookie value
    redirect_uri: str
    sealed_secrets: str | None  # the oauth_secrets cookie value; None when there are none


class ProviderAccountService:
    """Connects, links and disconnects users' accounts with ``definition``'s provider.

    The provider's ``oauth`` makes the provider calls; this service keeps the CSRF
    state, the stored link and one connected provider per user. ``fresh_credentials``
    replaces ``app.services.credentials.fresh_credentials``.
    """

    def __init__(
        self,
        definition: ProviderDefinition,
        user_repo: AsyncUserRepository,
        provider_repo: AsyncProviderRepository,
        *,
        fresh_credentials: FreshCredentials = fresh_credentials,
    ):
        self.provider = definition.provider
        self._oauth = definition.oauth
        self._token_refresher = definition.token_refresher
        self.user_repo = user_repo
        self.provider_repo = provider_repo
        self._fresh_credentials = fresh_credentials

    async def build_connect_url(
        self, user_id: str, redirect_uri: str | None = None
    ) -> ConnectStart:
        """Start the user's authorization with the provider.

        A user connected to another provider raises ``AnotherProviderConnectedError``.
        A provider call that fails raises the provider's error.
        """
        await self.user_repo.ensure_user_exists(user_id)
        await self._refuse_another_provider(user_id)
        resolved = redirect_uri or self._oauth.default_redirect_uri()
        state = create_oauth_state(user_id, provider=self.provider)
        start = await self._oauth.start_authorization(state, resolved)
        logger.debug("%s connect started for user %s", self.provider, user_id)
        return ConnectStart(
            authorize_url=start.url,
            state=state,
            redirect_uri=resolved,
            sealed_secrets=seal_oauth_secrets(start.secrets, state=state)
            if start.secrets
            else None,
        )

    async def handle_callback(
        self, params: Mapping[str, str], cookie_state: str | None, cookie_secrets: str | None
    ) -> str:
        """Link the provider account the callback's query ``params`` report to the user
        bound into their ``state``; return the user id.

        A state or secrets cookie that doesn't match raises ``OAuthStateMismatchError``;
        a user connected to another provider, or a provider account linked to another
        user, ``AnotherProviderConnectedError`` or ``ProviderAccountTakenError``; an
        unknown user ``UserNotFoundError``. A provider error from the exchange
        propagates. Nothing is stored unless the account is linked.
        """
        state = params.get("state", "")
        user_id = verify_oauth_state(state, cookie_state=cookie_state, provider=self.provider)
        secrets = open_oauth_secrets(cookie_secrets, state=state)
        await self._refuse_another_provider(user_id)
        link = await self._oauth.exchange(params, secrets)
        await self.provider_repo.link_provider(
            provider=self.provider,
            user_id=user_id,
            provider_user_id=link.provider_user_id,
            credentials=link.credentials,
        )
        logger.info(
            "%s account linked for user %s: provider user %s",
            self.provider,
            user_id,
            link.provider_user_id,
        )
        return user_id

    async def disconnect(self, user_id: str) -> None:
        """Revoke the user's authorization with the provider, then clear their stored
        credentials and connection.

        The credentials are refreshed first, when they expire soon, and the refresh is
        saved on its own. A user without credentials, or whose refresh the provider
        rejects, has nothing to revoke. Any other provider error propagates before
        anything is cleared.
        """
        try:
            credentials = await self._fresh_credentials(
                self.provider, user_id, self._token_refresher
            )
        except (ProviderNotConnectedError, ProviderAuthorizationError):
            credentials = None
        if credentials is not None:
            await self._oauth.revoke(credentials)
        await self.provider_repo.clear_provider_credentials(provider=self.provider, user_id=user_id)
        logger.info(
            "%s disconnected for user %s: %s",
            self.provider,
            user_id,
            "authorization revoked" if credentials is not None else "nothing to revoke",
        )

    async def _refuse_another_provider(self, user_id: str) -> None:
        connected = await self.provider_repo.get_connected_provider(user_id)
        if connected is not None and connected != self.provider:
            raise AnotherProviderConnectedError()
