from abc import abstractmethod
from typing import Protocol

from app.domain.models import UserProfile


class AsyncUserRepository(Protocol):
    """User persistence contract."""

    @abstractmethod
    async def ensure_user_exists(self, user_id: str) -> None: ...

    @abstractmethod
    async def lock_user(self, user_id: str) -> None:
        """Create the user if missing and lock the row until the transaction ends.

        Other transactions locking the same user wait for this one to finish.
        """

    @abstractmethod
    async def delete_user(self, user_id: str) -> None: ...

    @abstractmethod
    async def upsert_profile(self, user_id: str, profile: UserProfile) -> None: ...

    @abstractmethod
    async def get_profile(self, user_id: str) -> UserProfile | None: ...
