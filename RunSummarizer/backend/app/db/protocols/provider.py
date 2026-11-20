from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.enums import Provider
from app.domain.models import ProviderCredentials


@dataclass(frozen=True)
class LinkedAccount:
    """A user's account with one provider."""

    provider: Provider
    connected: bool
    sync_requested_at: datetime | None  # when a pending sync request was made; None if none


class AsyncProviderRepository(Protocol):
    """Provider account persistence contract."""

    @abstractmethod
    async def get_by_provider_user_id(
        self, provider: Provider, provider_user_id: str
    ) -> str | None:
        """The Clerk user id, or None when no account matches."""

    @abstractmethod
    async def get_connected_user_id(self, provider: Provider, provider_user_id: str) -> str | None:
        """The Clerk user id of a connected account, or None when no connected account
        matches."""

    @abstractmethod
    async def get_connected_provider(self, user_id: str) -> Provider | None:
        """The provider the user is connected to, or None."""

    @abstractmethod
    async def list_accounts(self, user_id: str) -> list[LinkedAccount]:
        """The user's provider accounts, connected or not, in one read; empty for an
        unknown user. Carries no credentials.
        """

    @abstractmethod
    async def link_provider(
        self,
        *,
        provider: Provider,
        user_id: str,
        provider_user_id: str,
        credentials: ProviderCredentials,
    ) -> None:
        """Attach or refresh ``provider`` credentials for ``user_id``, and mark the user
        connected to ``provider``.

        ``user_id`` must already exist. If it does not, the implementation
        raises ``UserNotFoundError``. A provider account already linked to another
        user raises ``ProviderAccountTakenError``, and a user connected to another
        provider ``AnotherProviderConnectedError``.
        """

    @abstractmethod
    async def update_provider_tokens(
        self,
        *,
        provider: Provider,
        user_id: str,
        credentials: ProviderCredentials,
    ) -> bool:
        """Replace the stored tokens. Returns whether the user has a ``provider`` account."""

    @abstractmethod
    async def get_provider_credentials(
        self, *, provider: Provider, user_id: str
    ) -> ProviderCredentials | None:
        """The user's decrypted OAuth credentials for ``provider``, or None when the user
        is unknown or holds no access token for ``provider``. With
        ``get_and_lock_provider_credentials``, the only reads that decrypt stored
        provider tokens.
        """

    @abstractmethod
    async def get_and_lock_provider_credentials(
        self, *, provider: Provider, user_id: str
    ) -> ProviderCredentials | None:
        """``get_provider_credentials``, locking the credentials until the transaction ends.

        Another transaction's ``get_and_lock_provider_credentials``, token update or
        ``clear_provider_credentials`` for the same user and provider waits for the lock.
        Plain reads don't.
        """

    @abstractmethod
    async def list_users_with_expired_tokens(
        self, provider: Provider, *, expired_before: datetime, limit: int
    ) -> list[str]:
        """The ids of at most ``limit`` users connected to ``provider`` whose access token
        expired before ``expired_before``, the longest expired first. Credentials without
        an expiry never expire. Carries no credentials.
        """

    @abstractmethod
    async def clear_provider_credentials(self, *, provider: Provider, user_id: str) -> bool:
        """Delete the user's stored OAuth credentials for ``provider``, and mark the user
        not connected to it.

        The user stays linked to their provider account, so ``get_by_provider_user_id``
        still finds them. A pending sync request is cleared too. Returns whether the
        user has a ``provider`` account.
        """

    @abstractmethod
    async def request_sync(self, *, provider: Provider, user_id: str, now: datetime) -> bool:
        """Record that ``provider`` was asked at ``now`` to send the user's activities by
        webhook. Returns whether the user has a ``provider`` account.
        """

    @abstractmethod
    async def get_sync_requested_at(self, *, provider: Provider, user_id: str) -> datetime | None:
        """When ``provider`` was last asked to send the user's activities, or None when
        no request is pending or the user has no ``provider`` account.
        """

    @abstractmethod
    async def clear_sync_request(self, *, provider: Provider, user_id: str) -> None:
        """Clear the user's pending sync request for ``provider``, if any."""
