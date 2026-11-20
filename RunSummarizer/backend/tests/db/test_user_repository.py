"""Contract tests for ``AsyncUserRepository``."""

import asyncio

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import Provider, Sex
from app.domain.errors import UserNotFoundError
from app.domain.models import ProviderCredentials, UserProfile
from tests.db.conftest import until_a_query_waits_for_a_lock

pytestmark = pytest.mark.anyio

STRAVA_EXPIRES_AT = 4_102_444_800  # Unix timestamp


# ---------- lock_user ----------


async def test_lock_user_creates_a_missing_user(user_repo, provider_repo, link_user):
    await user_repo.lock_user("user-1")

    await link_user("user-1", 101)
    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") == "user-1"


async def test_lock_user_waits_for_the_transaction_holding_the_lock(
    committed_engine, committed_transaction, committed_user_id
):
    async def lock_in_another_transaction() -> None:
        async with committed_transaction() as repos:
            await repos.users.lock_user(committed_user_id)

    async with committed_transaction() as first:
        await first.users.lock_user(committed_user_id)
        second = asyncio.create_task(lock_in_another_transaction())
        await until_a_query_waits_for_a_lock(committed_engine)
        assert not second.done()

    await asyncio.wait_for(second, timeout=5)


# ---------- ensure_user_exists ----------


async def test_ensure_user_exists_makes_the_user_linkable(user_repo, provider_repo, link_user):
    await user_repo.ensure_user_exists("user-1")

    await link_user("user-1", 101)
    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") == "user-1"


async def test_ensure_user_exists_is_idempotent(user_repo, provider_repo, link_user):
    await link_user("user-1", 101)

    await user_repo.ensure_user_exists("user-1")

    assert (
        await provider_repo.get_provider_credentials(provider=Provider.STRAVA, user_id="user-1")
        is not None
    )


async def test_ensure_user_exists_refuses_an_empty_id(user_repo):
    with pytest.raises(ValueError, match="empty"):
        await user_repo.ensure_user_exists("")


# ---------- delete_user ----------


async def test_delete_user_removes_the_user_and_their_provider_credentials(
    user_repo, provider_repo, link_user
):
    await link_user("user-1", 101)

    await user_repo.delete_user("user-1")

    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") is None
    assert (
        await provider_repo.get_provider_credentials(provider=Provider.STRAVA, user_id="user-1")
        is None
    )
    with pytest.raises(UserNotFoundError, match="does not exist"):
        await provider_repo.link_provider(
            provider=Provider.STRAVA,
            user_id="user-1",
            provider_user_id="101",
            credentials=ProviderCredentials("access", "refresh", STRAVA_EXPIRES_AT),
        )


async def test_delete_user_of_an_unknown_id_does_not_raise(user_repo):
    await user_repo.delete_user("no-such-user")


# ---------- profile ----------

PROFILE = UserProfile(
    age=32,
    sex=Sex.MALE,
    height_cm=180.5,
    max_hr=190,
)


async def test_upsert_profile_round_trips(user_repo):
    await user_repo.upsert_profile("user-1", PROFILE)

    assert await user_repo.get_profile("user-1") == PROFILE


async def test_upsert_profile_replaces_earlier_values_including_nulls(user_repo):
    await user_repo.upsert_profile("user-1", PROFILE)

    replaced = UserProfile(age=40)
    await user_repo.upsert_profile("user-1", replaced)

    assert await user_repo.get_profile("user-1") == replaced


async def test_upsert_profile_creates_a_missing_user(user_repo, provider_repo, link_user):
    await user_repo.upsert_profile("user-1", PROFILE)

    await link_user("user-1", 101)
    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") == "user-1"
    assert await user_repo.get_profile("user-1") == PROFILE


async def test_get_profile_of_an_unknown_id_returns_none(user_repo):
    assert await user_repo.get_profile("no-such-user") is None


async def test_upsert_profile_rejects_age_above_99(user_repo):
    with pytest.raises(IntegrityError):
        await user_repo.upsert_profile("user-1", UserProfile(age=100))


async def test_upsert_profile_rejects_height_above_240(user_repo):
    with pytest.raises(IntegrityError):
        await user_repo.upsert_profile("user-1", UserProfile(height_cm=241))


async def test_upsert_profile_rejects_age_below_5(user_repo):
    with pytest.raises(IntegrityError):
        await user_repo.upsert_profile("user-1", UserProfile(age=4))


async def test_upsert_profile_rejects_height_below_50(user_repo):
    with pytest.raises(IntegrityError):
        await user_repo.upsert_profile("user-1", UserProfile(height_cm=49.9))


async def test_upsert_profile_rejects_negative_max_hr(user_repo):
    with pytest.raises(IntegrityError):
        await user_repo.upsert_profile("user-1", UserProfile(max_hr=-1))


async def test_upsert_profile_rejects_max_hr_above_256(user_repo):
    with pytest.raises(IntegrityError):
        await user_repo.upsert_profile("user-1", UserProfile(max_hr=300))
