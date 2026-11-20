from collections.abc import Callable, Mapping
from datetime import datetime

from app.core.clock import utc_now
from app.db.protocols.import_queue import AsyncImportQueueRepository
from app.services.accounts.provider_account_service import ProviderAccountService


class ProviderConnectionService:
    """Completes a provider connection: links the account through ``accounts``, then
    queues the user's blocked items for the provider again.
    """

    def __init__(
        self,
        accounts: ProviderAccountService,
        import_queue: AsyncImportQueueRepository,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.accounts = accounts
        self.import_queue = import_queue
        self.clock = clock

    async def complete(
        self, params: Mapping[str, str], cookie_state: str | None, cookie_secrets: str | None
    ) -> None:
        """Handle the provider's OAuth callback with its query ``params``. A failed link
        raises before anything is queued again.
        """
        user_id = await self.accounts.handle_callback(params, cookie_state, cookie_secrets)
        await self.import_queue.unblock(user_id, self.accounts.provider, now=self.clock())

    async def disconnect(self, user_id: str) -> None:
        """Revoke the user's provider authorization through ``accounts``, then delete
        their queued items for the provider. A failed revocation deletes nothing.
        """
        await self.accounts.disconnect(user_id)
        await self.import_queue.delete_user_items(user_id, self.accounts.provider)
