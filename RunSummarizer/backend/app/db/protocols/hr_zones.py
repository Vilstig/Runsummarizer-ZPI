from abc import abstractmethod
from datetime import datetime
from typing import Protocol

from app.domain.models import HeartRateZones, HeartRateZonesRecord


class AsyncHeartRateZonesRepository(Protocol):
    """Heart rate zone history persistence contract."""

    @abstractmethod
    async def save(
        self, user_id: str, zones: HeartRateZones, *, now: datetime
    ) -> HeartRateZonesRecord:
        """Store ``zones`` as the user's current zones, valid from ``now``.

        The latest record is overwritten when no activity of the user was added at or
        after its ``valid_from``; otherwise a new record is added. Concurrent saves for
        the same user wait for each other. ``user_id`` must already exist. If it does
        not, the implementation raises ``UserNotFoundError("User does not exist")``.
        """

    @abstractmethod
    async def list_history(self, user_id: str) -> list[HeartRateZonesRecord]:
        """The user's records, oldest ``valid_from`` first; empty when the user has none."""

    @abstractmethod
    async def get_current(self, user_id: str) -> HeartRateZonesRecord | None:
        """The record with the latest ``valid_from``, or None when the user has none."""
