"""Users' provider credentials, refreshed under a lock before they expire, and refreshed
while nothing uses them so they don't run out."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import anyio

from app.core.clock import utc_now
from app.db.factory import RepositoriesFactory, transaction
from app.domain.enums import Provider
from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import TokenRefresher
from app.services.budget import pause_provider_calls

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

REFRESH_MARGIN_S = 300  # seconds of validity an access token handed out has left, at least
# users one refresh_idle_credentials pass clears the credentials of, at most
MAX_CLEARED_PER_PASS = 3


def not_connected(provider: Provider, user_id: str) -> ProviderNotConnectedError:
    """The error for a user who holds no ``provider`` credentials."""
    return ProviderNotConnectedError(f"User {user_id} has no {provider} credentials")


def expires_soon(credentials: ProviderCredentials, *, now: datetime) -> bool:
    """Whether the access token has less than ``REFRESH_MARGIN_S`` of validity left at ``now``."""
    if credentials.expires_at is None:
        return False
    return credentials.expires_at - now.timestamp() < REFRESH_MARGIN_S


async def fresh_credentials(
    provider: Provider,
    user_id: str,
    refresher: TokenRefresher | None,
    *,
    transaction: RepositoriesFactory = transaction,
    clock: Callable[[], datetime] = utc_now,
) -> ProviderCredentials:
    """The user's ``provider`` credentials, with an access token that doesn't
    ``expires_soon``.

    The stored credentials are locked; one that ``expires_soon`` is refreshed through
    ``refresher`` and the new tokens are saved in that transaction, so a caller that
    waited for the lock reads them and doesn't refresh again. Without a refresher the
    stored credentials are returned as they are. Raises ``ProviderNotConnectedError``
    when the user holds no ``provider`` credentials; an error from ``refresher``
    propagates and nothing is saved.
    """
    async with transaction() as repos:
        if refresher is None:
            credentials = await repos.providers.get_provider_credentials(
                provider=provider, user_id=user_id
            )
        else:
            credentials = await repos.providers.get_and_lock_provider_credentials(
                provider=provider, user_id=user_id
            )
        if credentials is None:
            raise not_connected(provider, user_id)
        if refresher is None or not expires_soon(credentials, now=clock()):
            return credentials
        refreshed = await refresher.refresh(credentials)
        await repos.providers.update_provider_tokens(
            provider=provider, user_id=user_id, credentials=refreshed
        )
    logger.info("%s token refreshed for user %s", provider, user_id)
    return refreshed


@dataclass(frozen=True)
class IdleRefresh:
    """What one ``refresh_idle_credentials`` pass did, counted in users."""

    refreshed: int = 0
    cleared: int = 0  # whose refresh the provider rejected; their credentials were cleared
    failed: int = 0  # whose refresh failed otherwise, or wasn't cleared; tried at the next pass


class RefreshTimeoutError(Exception):
    """A token refresh was cut off once it took its timeout."""


class _TimedRefresher(TokenRefresher):
    """``refresher``, whose refresh is cut off with ``RefreshTimeoutError`` once it takes
    ``timeout``."""

    def __init__(self, refresher: TokenRefresher, timeout: timedelta):
        self._refresher = refresher
        self._timeout = timeout

    async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
        with anyio.move_on_after(self._timeout.total_seconds()):
            return await self._refresher.refresh(credentials)
        raise RefreshTimeoutError(f"the token refresh took longer than {self._timeout}")


async def refresh_idle_credentials(
    provider: Provider,
    refresher: TokenRefresher,
    idle: timedelta,
    limit: int,
    *,
    refresh_timeout: timedelta | None = None,
    max_cleared: int = MAX_CLEARED_PER_PASS,
    transaction: RepositoriesFactory = transaction,
    clock: Callable[[], datetime] = utc_now,
) -> IdleRefresh:
    """Refresh, through ``fresh_credentials``, the tokens of at most ``limit`` users
    connected to ``provider`` whose access token expired more than ``idle`` ago.

    - A refresh the provider rejects (``ProviderAuthorizationError``) clears the user's
      credentials and their connection, unless new tokens were stored meanwhile. After
      ``max_cleared`` users the pass clears no more: the rest count as failed, and an
      error is logged.
    - A ``RateLimitedError`` pauses the provider's calls until it ends, and ends the pass.
    - A refresh that takes ``refresh_timeout``, or fails otherwise, is logged; the user is
      tried again at the next pass.

    Nothing is refreshed while the provider's calls are paused. A user disconnected
    since the read is skipped.
    """
    if refresh_timeout is not None:
        refresher = _TimedRefresher(refresher, refresh_timeout)
    expired_before = clock() - idle
    async with transaction() as repos:
        paused_until = await repos.budgets.paused_until(provider, now=clock())
        if paused_until is not None:
            return IdleRefresh()
        user_ids = await repos.providers.list_users_with_expired_tokens(
            provider, expired_before=expired_before, limit=limit
        )
    refreshed = cleared = failed = 0
    for user_id in user_ids:
        try:
            await fresh_credentials(
                provider, user_id, refresher, transaction=transaction, clock=clock
            )
        except ProviderNotConnectedError:
            continue
        except ProviderAuthorizationError:
            if cleared >= max_cleared:
                failed += 1
                logger.error(
                    "%s: the refresh of user %s's unused tokens was rejected; credentials "
                    "kept, since this pass already cleared %d users",
                    provider,
                    user_id,
                    cleared,
                )
            elif await _clear_if_still_expired(
                provider, user_id, expired_before, transaction=transaction
            ):
                cleared += 1
                logger.warning(
                    "%s: the refresh of user %s's unused tokens was rejected; credentials cleared",
                    provider,
                    user_id,
                )
        except RateLimitedError as exc:
            failed += 1
            await pause_provider_calls(provider, exc.until, transaction=transaction)
            logger.warning(
                "%s: rate limited while refreshing unused tokens; calls paused until %s",
                provider,
                exc.until,
            )
            break
        except RefreshTimeoutError:
            failed += 1
            logger.warning(
                "%s: refreshing user %s's unused tokens took longer than %s",
                provider,
                user_id,
                refresh_timeout,
            )
        except ProviderUnavailableError:
            failed += 1
            logger.warning(
                "%s: refreshing user %s's unused tokens failed: the provider is unavailable",
                provider,
                user_id,
            )
        except Exception:
            failed += 1
            logger.exception("%s: refreshing user %s's unused tokens failed", provider, user_id)
        else:
            refreshed += 1
    return IdleRefresh(refreshed=refreshed, cleared=cleared, failed=failed)


async def _clear_if_still_expired(
    provider: Provider,
    user_id: str,
    expired_before: datetime,
    *,
    transaction: RepositoriesFactory,
) -> bool:
    """Clear the user's ``provider`` credentials while their access token still expired
    before ``expired_before``. Returns whether they were cleared."""
    async with transaction() as repos:
        credentials = await repos.providers.get_and_lock_provider_credentials(
            provider=provider, user_id=user_id
        )
        if (
            credentials is None
            or credentials.expires_at is None
            or credentials.expires_at >= expired_before.timestamp()
        ):
            return False
        return await repos.providers.clear_provider_credentials(provider=provider, user_id=user_id)
