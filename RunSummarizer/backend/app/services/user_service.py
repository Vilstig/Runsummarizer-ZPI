from datetime import UTC, datetime

from app.db.protocols import AsyncHeartRateZonesRepository, AsyncUserRepository
from app.domain.errors import HeartRateZonesConflictError
from app.domain.models import HeartRateZones, UserProfile


class UserService:
    def __init__(self, repo: AsyncUserRepository, hr_zones: AsyncHeartRateZonesRepository):
        self._repo = repo
        self._hr_zones = hr_zones

    async def get_profile(self, user_id: str) -> UserProfile:
        await self._repo.ensure_user_exists(user_id)
        return await self._repo.get_profile(user_id) or UserProfile()

    async def replace_profile(self, user_id: str, profile: UserProfile) -> None:
        if profile.max_hr is not None:
            await self._repo.lock_user(user_id)
            current = await self._hr_zones.get_current(user_id)
            if current is not None:
                _check_max_hr_above_zone5(profile.max_hr, current.zones)
        await self._repo.upsert_profile(user_id, profile)

    async def get_hr_zones(self, user_id: str) -> HeartRateZones | None:
        current = await self._hr_zones.get_current(user_id)
        return None if current is None else current.zones

    async def replace_hr_zones(self, user_id: str, zones: HeartRateZones) -> None:
        await self._repo.lock_user(user_id)
        profile = await self._repo.get_profile(user_id)
        if profile is not None and profile.max_hr is not None:
            _check_max_hr_above_zone5(profile.max_hr, zones)
        await self._hr_zones.save(user_id, zones, now=datetime.now(UTC))

    async def ensure_user_exists(self, user_id: str) -> None:
        await self._repo.ensure_user_exists(user_id)


def _check_max_hr_above_zone5(max_hr: int, zones: HeartRateZones) -> None:
    if max_hr <= zones.zone5_bpm:
        raise HeartRateZonesConflictError(
            "max heart rate must be greater than the zone 5 lower bound"
        )
