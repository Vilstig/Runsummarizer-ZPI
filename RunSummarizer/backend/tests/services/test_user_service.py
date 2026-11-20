"""UserService: profile reads create the user row, then return what is stored."""

from datetime import UTC, datetime

import pytest

from app.domain.errors import HeartRateZonesConflictError
from app.domain.models import HeartRateZones, HeartRateZonesRecord, UserProfile
from app.services.user_service import UserService

pytestmark = pytest.mark.anyio

STORED = UserProfile(age=32, max_hr=190)
ZONES = HeartRateZones(zone1_bpm=100, zone2_bpm=120, zone3_bpm=140, zone4_bpm=160, zone5_bpm=175)


class RecordingUserRepository:
    def __init__(self, calls: list[str] | None = None):
        self.calls = [] if calls is None else calls
        self.profiles: dict[str, UserProfile] = {}

    async def ensure_user_exists(self, user_id: str) -> None:
        self.calls.append(f"ensure_user_exists:{user_id}")
        self.profiles.setdefault(user_id, UserProfile())

    async def get_profile(self, user_id: str) -> UserProfile | None:
        self.calls.append(f"get_profile:{user_id}")
        return self.profiles.get(user_id)

    async def upsert_profile(self, user_id: str, profile: UserProfile) -> None:
        self.calls.append(f"upsert_profile:{user_id}")
        self.profiles[user_id] = profile

    async def lock_user(self, user_id: str) -> None:
        self.calls.append(f"lock_user:{user_id}")
        self.profiles.setdefault(user_id, UserProfile())

    async def delete_user(self, user_id: str) -> None:
        self.calls.append(f"delete_user:{user_id}")
        self.profiles.pop(user_id, None)


class RecordingHeartRateZonesRepository:
    """Keeps every saved record, newest first."""

    def __init__(self, calls: list[str] | None = None):
        self.calls = [] if calls is None else calls
        self.records: dict[str, list[HeartRateZonesRecord]] = {}

    async def save(
        self, user_id: str, zones: HeartRateZones, *, now: datetime
    ) -> HeartRateZonesRecord:
        self.calls.append(f"save:{user_id}")
        record = HeartRateZonesRecord(valid_from=now, zones=zones)
        self.records.setdefault(user_id, []).insert(0, record)
        return record

    async def get_current(self, user_id: str) -> HeartRateZonesRecord | None:
        self.calls.append(f"get_current:{user_id}")
        return next(iter(self.records.get(user_id, [])), None)


def _service() -> tuple[UserService, RecordingUserRepository, RecordingHeartRateZonesRepository]:
    calls: list[str] = []
    users = RecordingUserRepository(calls)
    hr_zones = RecordingHeartRateZonesRepository(calls)
    return UserService(users, hr_zones), users, hr_zones


async def test_get_profile_ensures_the_user_before_reading():
    service, users, _ = _service()

    await service.get_profile("user-1")

    assert users.calls == ["ensure_user_exists:user-1", "get_profile:user-1"]


async def test_get_profile_without_a_stored_profile_is_empty():
    service, _, _ = _service()

    assert await service.get_profile("user-1") == UserProfile()


async def test_get_profile_returns_the_stored_profile():
    service, users, _ = _service()
    users.profiles["user-1"] = STORED

    assert await service.get_profile("user-1") == STORED


async def test_replace_profile_is_passed_to_the_repository():
    service, users, _ = _service()

    await service.replace_profile("user-1", STORED)

    assert users.calls == ["lock_user:user-1", "get_current:user-1", "upsert_profile:user-1"]
    assert users.profiles["user-1"] == STORED


async def test_replace_profile_rejects_max_hr_not_above_current_zone5():
    service, users, _ = _service()
    await service.replace_hr_zones("user-1", ZONES)

    with pytest.raises(HeartRateZonesConflictError):
        await service.replace_profile("user-1", UserProfile(max_hr=175))

    assert users.profiles["user-1"] == UserProfile()


async def test_replace_profile_without_max_hr_ignores_the_zones():
    service, users, _ = _service()
    await service.replace_hr_zones("user-1", ZONES)

    await service.replace_profile("user-1", UserProfile(age=40))

    assert users.profiles["user-1"] == UserProfile(age=40)


async def test_replace_hr_zones_locks_the_user_then_saves():
    service, users, hr_zones = _service()
    before = datetime.now(UTC)

    await service.replace_hr_zones("user-1", ZONES)

    assert users.calls == ["lock_user:user-1", "get_profile:user-1", "save:user-1"]
    [record] = hr_zones.records["user-1"]
    assert record.zones == ZONES
    assert record.valid_from >= before


async def test_replace_hr_zones_rejects_zone5_not_below_max_hr():
    service, users, hr_zones = _service()
    users.profiles["user-1"] = UserProfile(max_hr=175)

    with pytest.raises(HeartRateZonesConflictError):
        await service.replace_hr_zones("user-1", ZONES)

    assert hr_zones.records == {}


async def test_get_hr_zones_returns_the_current_zones():
    service, _, _ = _service()
    await service.replace_hr_zones("user-1", ZONES)

    assert await service.get_hr_zones("user-1") == ZONES


async def test_get_hr_zones_without_zones_is_none():
    service, _, _ = _service()

    assert await service.get_hr_zones("user-1") is None


async def test_ensure_user_exists_is_passed_to_the_repository():
    service, users, _ = _service()

    await service.ensure_user_exists("user-1")

    assert users.calls == ["ensure_user_exists:user-1"]
    assert "user-1" in users.profiles
