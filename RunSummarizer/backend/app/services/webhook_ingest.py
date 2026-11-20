"""Applying the commands a provider's webhook parser read from a pushed event."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from app.core.clock import utc_now
from app.db.factory import Repositories, RepositoriesFactory, transaction
from app.domain.enums import Provider
from app.providers.base import AccountRevoked, ActivityChanged, WebhookCommand

logger = logging.getLogger(__name__)


async def ingest_webhook(
    provider: Provider,
    commands: Sequence[WebhookCommand],
    *,
    transaction: RepositoriesFactory = transaction,
    clock: Callable[[], datetime] = utc_now,
) -> None:
    """Apply ``commands`` from ``provider``'s webhook, in one transaction.

    - ``ActivityChanged`` queues the activity at webhook priority with the event's
      ``sent_data``, unless the user has it stored, and a queued activity clears the
      user's pending sync request for ``provider``.
    - ``AccountRevoked`` clears the user's stored credentials for ``provider`` and their
      connection to it.

    A command for a provider account without a user, or whose user isn't connected to
    ``provider``, is ignored. Without commands no
    transaction is opened. A database error propagates.
    """
    if not commands:
        return
    now = clock()
    applied: list[str] = []  # log lines, written once the transaction commits
    async with transaction() as repos:
        users: dict[str, str | None] = {}  # provider user id -> user id
        requests_cleared: set[str] = set()  # user ids
        for command in commands:
            account = command.provider_user_id
            if account not in users:
                users[account] = await _user_id(repos, provider, account)
            user_id = users[account]
            if user_id is None:
                continue
            match command:
                case ActivityChanged(activity_key=activity_key, sent_data=sent_data):
                    if await repos.activities.is_stored(user_id, activity_key):
                        logger.info(
                            "%s webhook: %s of user %s is already stored",
                            provider,
                            activity_key,
                            user_id,
                        )
                        continue
                    await repos.import_queue.enqueue_webhook(
                        user_id, provider, activity_key, sent_data=sent_data, now=now
                    )
                    if user_id not in requests_cleared:
                        await repos.providers.clear_sync_request(provider=provider, user_id=user_id)
                        requests_cleared.add(user_id)
                    applied.append(f"{activity_key} queued for user {user_id}")
                case AccountRevoked():
                    await repos.providers.clear_provider_credentials(
                        provider=provider, user_id=user_id
                    )
                    applied.append(
                        f"account {account} revoked; credentials of user {user_id} cleared"
                    )
    for line in applied:
        logger.info("%s webhook: %s", provider, line)


async def _user_id(repos: Repositories, provider: Provider, provider_user_id: str) -> str | None:
    """The id of the provider account's user, or None if the account has no user or the
    user isn't connected to ``provider``."""
    user_id = await repos.providers.get_connected_user_id(provider, provider_user_id)
    if user_id is None:
        logger.info(
            "%s webhook: ignoring an event for unknown or disconnected account %s",
            provider,
            provider_user_id,
        )
    return user_id
