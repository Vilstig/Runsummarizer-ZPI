"""Contract tests for ``AsyncProviderRepository``.

Assertions target the protocol -- the values a repository returns and the state
it leaves behind -- never the storage layout. Lookups do not carry provider
credentials; ``get_provider_credentials`` is the read that returns them, decrypted.

``expires_at`` on provider credentials is a Unix timestamp.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.db.protocols.provider import LinkedAccount
from app.domain.enums import Provider
from app.domain.errors import (
    AnotherProviderConnectedError,
    ProviderAccountTakenError,
    UserNotFoundError,
)
from app.domain.models import ProviderCredentials
from tests.db.conftest import until_a_query_waits_for_a_lock

pytestmark = pytest.mark.anyio

STRAVA_EXPIRES_AT = 4_102_444_800  # Unix timestamp


# ---------- link_provider ----------


async def test_link_provider_refuses_an_unknown_user(provider_repo):
    with pytest.raises(UserNotFoundError, match="does not exist"):
        await provider_repo.link_provider(
            provider=Provider.STRAVA,
            user_id="user-1",
            provider_user_id="101",
            credentials=ProviderCredentials("access", "refresh", STRAVA_EXPIRES_AT),
        )

    assert (
        await provider_repo.get_provider_credentials(provider=Provider.STRAVA, user_id="user-1")
        is None
    )


async def test_link_provider_for_an_unknown_user_does_not_create_the_user(user_repo, provider_repo):
    with pytest.raises(UserNotFoundError, match="does not exist"):
        await provider_repo.link_provider(
            provider=Provider.STRAVA,
            user_id="user-1",
            provider_user_id="101",
            credentials=ProviderCredentials("access", "refresh", STRAVA_EXPIRES_AT),
        )

    await user_repo.ensure_user_exists("user-1")
    await provider_repo.link_provider(
        provider=Provider.STRAVA,
        user_id="user-1",
        provider_user_id="101",
        credentials=ProviderCredentials("access", "refresh", STRAVA_EXPIRES_AT),
    )
    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") == "user-1"


async def test_link_provider_stores_credentials_for_an_existing_user(provider_repo, link_user):
    await link_user("user-1", 101, access_token="access", refresh_token="refresh")

    assert await provider_repo.get_provider_credentials(
        provider=Provider.STRAVA, user_id="user-1"
    ) == ProviderCredentials("access", "refresh", STRAVA_EXPIRES_AT)


async def test_link_provider_refreshes_tokens_for_the_same_user(provider_repo, link_user):
    await link_user("user-1", 101)
    await link_user(
        "user-1",
        101,
        access_token="access-2",
        refresh_token="refresh-2",
        expires_at=STRAVA_EXPIRES_AT + 3600,
    )

    assert await provider_repo.get_provider_credentials(
        provider=Provider.STRAVA, user_id="user-1"
    ) == ProviderCredentials("access-2", "refresh-2", STRAVA_EXPIRES_AT + 3600)


async def test_link_provider_can_move_the_provider_user_id(provider_repo, link_user):
    await link_user("user-1", 101)
    await link_user("user-1", 202)

    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") is None
    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "202") == "user-1"


async def test_link_provider_distinguishes_users(provider_repo, link_user):
    await link_user("user-1", 101)
    await link_user("user-2", 102)

    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") == "user-1"
    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "102") == "user-2"


async def test_link_provider_refuses_an_id_owned_by_another_user(provider_repo, link_user):
    await link_user("user-1", 101)

    with pytest.raises(ProviderAccountTakenError, match="already linked"):
        await link_user("user-2", 101)

    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") == "user-1"


# ---------- get_by_provider_user_id ----------


async def test_get_by_provider_user_id_returns_none_when_missing(provider_repo):
    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "404") is None


async def test_get_by_provider_user_id_is_scoped_to_the_provider(provider_repo, link_user):
    await link_user("user-1", 101)

    assert await provider_repo.get_by_provider_user_id(Provider.GARMIN, "101") is None


# ---------- update_provider_tokens ----------


async def test_update_provider_tokens_reports_success_and_moves_the_expiry(
    provider_repo, make_user
):
    user_id = await make_user(101)

    updated = await provider_repo.update_provider_tokens(
        provider=Provider.STRAVA,
        user_id=user_id,
        credentials=ProviderCredentials(
            "rotated-access", "rotated-refresh", STRAVA_EXPIRES_AT + 7200
        ),
    )

    assert updated is True
    assert await provider_repo.get_provider_credentials(
        provider=Provider.STRAVA, user_id=user_id
    ) == ProviderCredentials("rotated-access", "rotated-refresh", STRAVA_EXPIRES_AT + 7200)


async def test_update_provider_tokens_returns_false_when_the_user_is_missing(provider_repo):
    updated = await provider_repo.update_provider_tokens(
        provider=Provider.STRAVA,
        user_id="no-such-user",
        credentials=ProviderCredentials("access", "refresh", STRAVA_EXPIRES_AT),
    )

    assert updated is False


async def test_update_provider_tokens_returns_false_for_another_provider(provider_repo, make_user):
    user_id = await make_user(101)

    updated = await provider_repo.update_provider_tokens(
        provider=Provider.GARMIN,
        user_id=user_id,
        credentials=ProviderCredentials("access", "refresh", STRAVA_EXPIRES_AT),
    )

    assert updated is False
    assert (
        await provider_repo.get_provider_credentials(provider=Provider.STRAVA, user_id=user_id)
    ).refresh_token == "refresh-101"


# ---------- get_provider_credentials ----------


async def test_get_provider_credentials_is_scoped_to_the_user(provider_repo, make_user):
    mine = await make_user(101)
    theirs = await make_user(102)

    my_credentials = await provider_repo.get_provider_credentials(
        provider=Provider.STRAVA, user_id=mine
    )
    their_credentials = await provider_repo.get_provider_credentials(
        provider=Provider.STRAVA, user_id=theirs
    )

    assert my_credentials.refresh_token == "refresh-101"
    assert their_credentials.refresh_token == "refresh-102"


async def test_get_provider_credentials_returns_none_for_an_unknown_user(provider_repo):
    assert (
        await provider_repo.get_provider_credentials(
            provider=Provider.STRAVA, user_id="no-such-user"
        )
        is None
    )


async def test_get_provider_credentials_returns_none_for_another_provider(provider_repo, make_user):
    user_id = await make_user(101)

    assert (
        await provider_repo.get_provider_credentials(provider=Provider.GARMIN, user_id=user_id)
        is None
    )


# ---------- lock_provider_credentials ----------


async def test_lock_provider_credentials_returns_the_strava_tokens(provider_repo, make_user):
    user_id = await make_user(101)

    assert await provider_repo.get_and_lock_provider_credentials(
        provider=Provider.STRAVA, user_id=user_id
    ) == ProviderCredentials("access-101", "refresh-101", STRAVA_EXPIRES_AT)


async def test_lock_provider_credentials_returns_none_for_an_unknown_user(provider_repo):
    assert (
        await provider_repo.get_and_lock_provider_credentials(
            provider=Provider.STRAVA, user_id="no-such-user"
        )
        is None
    )


async def test_lock_provider_credentials_returns_none_for_another_provider(
    provider_repo, make_user
):
    user_id = await make_user(101)

    assert (
        await provider_repo.get_and_lock_provider_credentials(
            provider=Provider.GARMIN, user_id=user_id
        )
        is None
    )


async def test_a_second_lock_waits_for_the_first_transaction_and_reads_its_tokens(
    committed_engine, committed_transaction, committed_user_id
):
    async def lock_in_another_transaction() -> ProviderCredentials | None:
        async with committed_transaction() as repos:
            return await repos.providers.get_and_lock_provider_credentials(
                provider=Provider.STRAVA, user_id=committed_user_id
            )

    async with committed_transaction() as first:
        await first.providers.get_and_lock_provider_credentials(
            provider=Provider.STRAVA, user_id=committed_user_id
        )
        second = asyncio.create_task(lock_in_another_transaction())
        await until_a_query_waits_for_a_lock(committed_engine)
        assert not second.done()
        await first.providers.update_provider_tokens(
            provider=Provider.STRAVA,
            user_id=committed_user_id,
            credentials=ProviderCredentials(
                "rotated-access", "rotated-refresh", STRAVA_EXPIRES_AT + 7200
            ),
        )

    assert await asyncio.wait_for(second, timeout=5) == ProviderCredentials(
        "rotated-access", "rotated-refresh", STRAVA_EXPIRES_AT + 7200
    )


async def test_a_plain_read_does_not_wait_for_the_lock(committed_transaction, committed_user_id):
    async def read_in_another_transaction() -> ProviderCredentials | None:
        async with committed_transaction() as repos:
            return await repos.providers.get_provider_credentials(
                provider=Provider.STRAVA, user_id=committed_user_id
            )

    async with committed_transaction() as first:
        await first.providers.get_and_lock_provider_credentials(
            provider=Provider.STRAVA, user_id=committed_user_id
        )
        credentials = await asyncio.wait_for(read_in_another_transaction(), timeout=5)

    assert credentials.refresh_token == "refresh-9101"


# ---------- clear_provider_credentials ----------


async def test_clear_provider_credentials_leaves_the_user_without_credentials(
    provider_repo, make_user
):
    user_id = await make_user(101)

    assert (
        await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id=user_id)
        is True
    )

    assert (
        await provider_repo.get_provider_credentials(provider=Provider.STRAVA, user_id=user_id)
        is None
    )
    assert (
        await provider_repo.get_and_lock_provider_credentials(
            provider=Provider.STRAVA, user_id=user_id
        )
        is None
    )


async def test_clear_provider_credentials_keeps_the_user_and_their_athlete_id(
    provider_repo, make_user
):
    user_id = await make_user(101)

    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id=user_id)

    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") == user_id


async def test_clear_provider_credentials_is_scoped_to_the_user(provider_repo, make_user):
    mine = await make_user(101)
    theirs = await make_user(102)

    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id=mine)

    their_credentials = await provider_repo.get_provider_credentials(
        provider=Provider.STRAVA, user_id=theirs
    )
    assert their_credentials.refresh_token == "refresh-102"


async def test_clear_provider_credentials_returns_false_for_an_unknown_user(provider_repo):
    assert (
        await provider_repo.clear_provider_credentials(
            provider=Provider.STRAVA, user_id="no-such-user"
        )
        is False
    )


async def test_clear_provider_credentials_for_another_provider_keeps_the_strava_tokens(
    provider_repo, make_user
):
    user_id = await make_user(101)

    assert (
        await provider_repo.clear_provider_credentials(provider=Provider.GARMIN, user_id=user_id)
        is False
    )

    assert (
        await provider_repo.get_provider_credentials(provider=Provider.STRAVA, user_id=user_id)
        is not None
    )


async def test_connecting_strava_again_after_a_clear_stores_new_credentials(
    provider_repo, make_user, link_user
):
    user_id = await make_user(101)
    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id=user_id)

    await link_user(
        user_id,
        101,
        access_token="access-again",
        refresh_token="refresh-again",
    )

    assert await provider_repo.get_provider_credentials(
        provider=Provider.STRAVA, user_id=user_id
    ) == ProviderCredentials("access-again", "refresh-again", STRAVA_EXPIRES_AT)


async def test_a_clear_waits_for_the_lock_and_is_not_undone_by_its_token_update(
    committed_engine, committed_transaction, committed_user_id
):
    async def clear_in_another_transaction() -> bool:
        async with committed_transaction() as repos:
            return await repos.providers.clear_provider_credentials(
                provider=Provider.STRAVA, user_id=committed_user_id
            )

    async with committed_transaction() as first:
        await first.providers.get_and_lock_provider_credentials(
            provider=Provider.STRAVA, user_id=committed_user_id
        )
        second = asyncio.create_task(clear_in_another_transaction())
        await until_a_query_waits_for_a_lock(committed_engine)
        assert not second.done()
        await first.providers.update_provider_tokens(
            provider=Provider.STRAVA,
            user_id=committed_user_id,
            credentials=ProviderCredentials(
                "rotated-access", "rotated-refresh", STRAVA_EXPIRES_AT + 7200
            ),
        )

    assert await asyncio.wait_for(second, timeout=5) is True
    async with committed_transaction() as repos:
        assert (
            await repos.providers.get_provider_credentials(
                provider=Provider.STRAVA, user_id=committed_user_id
            )
            is None
        )


# ---------- connections ----------


async def test_credentials_without_a_refresh_token_or_expiry_read_as_connected(
    provider_repo, link_user
):
    await link_user("user-1", 101, access_token="access", refresh_token=None, expires_at=None)
    await provider_repo.update_provider_tokens(
        provider=Provider.STRAVA,
        user_id="user-1",
        credentials=ProviderCredentials("access-2", None, None),
    )

    assert await provider_repo.get_provider_credentials(
        provider=Provider.STRAVA, user_id="user-1"
    ) == ProviderCredentials("access-2", None, None)


async def test_a_linked_user_is_connected_to_the_provider(provider_repo, make_user):
    user_id = await make_user(101)

    assert await provider_repo.get_connected_provider(user_id) is Provider.STRAVA
    assert await provider_repo.get_connected_user_id(Provider.STRAVA, "101") == user_id


async def test_a_user_without_an_account_is_connected_to_nothing(provider_repo, user_repo):
    await user_repo.ensure_user_exists("user-1")

    assert await provider_repo.get_connected_provider("user-1") is None
    assert await provider_repo.get_connected_user_id(Provider.STRAVA, "101") is None


async def test_get_connected_user_id_is_scoped_to_the_provider(provider_repo, make_user):
    await make_user(101)

    assert await provider_repo.get_connected_user_id(Provider.GARMIN, "101") is None


async def test_clearing_the_credentials_disconnects_the_user(provider_repo, make_user):
    user_id = await make_user(101)

    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id=user_id)

    assert await provider_repo.get_connected_provider(user_id) is None
    assert await provider_repo.get_connected_user_id(Provider.STRAVA, "101") is None
    assert await provider_repo.get_by_provider_user_id(Provider.STRAVA, "101") == user_id


async def test_linking_the_connected_provider_again_keeps_the_user_connected(
    provider_repo, link_user
):
    await link_user("user-1", 101)
    await link_user("user-1", 101, access_token="access-2")

    assert await provider_repo.get_connected_provider("user-1") is Provider.STRAVA


async def test_linking_a_second_provider_while_connected_is_refused(provider_repo, link_user):
    await link_user("user-1", 101)

    with pytest.raises(AnotherProviderConnectedError):
        await link_user("user-1", 555, provider=Provider.GARMIN)

    assert await provider_repo.get_connected_provider("user-1") is Provider.STRAVA
    assert (
        await provider_repo.get_provider_credentials(provider=Provider.GARMIN, user_id="user-1")
        is None
    )


async def test_another_provider_can_be_linked_once_the_first_is_disconnected(
    provider_repo, link_user
):
    await link_user("user-1", 101)
    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id="user-1")

    await link_user("user-1", 555, provider=Provider.GARMIN)

    assert await provider_repo.get_connected_provider("user-1") is Provider.GARMIN


async def test_of_two_concurrent_links_of_different_providers_the_second_is_refused(
    committed_engine, committed_transaction, committed_user_id
):
    async with committed_transaction() as repos:
        await repos.providers.clear_provider_credentials(
            provider=Provider.STRAVA, user_id=committed_user_id
        )

    async def link_garmin_in_another_transaction() -> None:
        async with committed_transaction() as repos:
            await repos.providers.link_provider(
                provider=Provider.GARMIN,
                user_id=committed_user_id,
                provider_user_id="555",
                credentials=ProviderCredentials("garmin-access", None, None),
            )

    async with committed_transaction() as first:
        await first.providers.link_provider(
            provider=Provider.STRAVA,
            user_id=committed_user_id,
            provider_user_id="9101",
            credentials=ProviderCredentials("access", "refresh", STRAVA_EXPIRES_AT),
        )
        second = asyncio.create_task(link_garmin_in_another_transaction())
        await until_a_query_waits_for_a_lock(committed_engine)
        assert not second.done()

    with pytest.raises(AnotherProviderConnectedError):
        await asyncio.wait_for(second, timeout=5)
    async with committed_transaction() as repos:
        assert await repos.providers.get_connected_provider(committed_user_id) is Provider.STRAVA


# ---------- list_accounts ----------


async def test_list_accounts_lists_each_account_with_its_connection_and_request(
    provider_repo, link_user
):
    await link_user("user-1", 101)
    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id="user-1")
    await link_user("user-1", 555, provider=Provider.GARMIN)
    await provider_repo.request_sync(provider=Provider.GARMIN, user_id="user-1", now=REQUESTED_AT)

    assert await provider_repo.list_accounts("user-1") == [
        LinkedAccount(Provider.GARMIN, connected=True, sync_requested_at=REQUESTED_AT),
        LinkedAccount(Provider.STRAVA, connected=False, sync_requested_at=None),
    ]


async def test_list_accounts_is_scoped_to_the_user(provider_repo, make_user):
    await make_user(101)
    theirs = await make_user(102)

    assert await provider_repo.list_accounts(theirs) == [
        LinkedAccount(Provider.STRAVA, connected=True, sync_requested_at=None)
    ]


async def test_list_accounts_of_an_unknown_user_is_empty(provider_repo):
    assert await provider_repo.list_accounts("no-such-user") == []


# ---------- sync requests ----------

REQUESTED_AT = datetime(2026, 10, 11, 12, 7, tzinfo=UTC)


async def test_a_user_without_a_request_has_none_pending(provider_repo, make_user):
    user_id = await make_user(101)

    assert (
        await provider_repo.get_sync_requested_at(provider=Provider.STRAVA, user_id=user_id) is None
    )


async def test_request_sync_records_when_the_sync_was_requested(provider_repo, make_user):
    user_id = await make_user(101)

    assert (
        await provider_repo.request_sync(
            provider=Provider.STRAVA, user_id=user_id, now=REQUESTED_AT
        )
        is True
    )

    assert (
        await provider_repo.get_sync_requested_at(provider=Provider.STRAVA, user_id=user_id)
        == REQUESTED_AT
    )


async def test_request_sync_is_scoped_to_the_user_and_the_provider(provider_repo, make_user):
    mine = await make_user(101)
    theirs = await make_user(102)

    await provider_repo.request_sync(provider=Provider.STRAVA, user_id=mine, now=REQUESTED_AT)

    assert (
        await provider_repo.get_sync_requested_at(provider=Provider.STRAVA, user_id=theirs) is None
    )
    assert await provider_repo.get_sync_requested_at(provider=Provider.GARMIN, user_id=mine) is None


async def test_request_sync_returns_false_without_a_provider_account(provider_repo, make_user):
    user_id = await make_user(101)

    assert (
        await provider_repo.request_sync(
            provider=Provider.GARMIN, user_id=user_id, now=REQUESTED_AT
        )
        is False
    )
    assert (
        await provider_repo.request_sync(
            provider=Provider.STRAVA, user_id="nobody", now=REQUESTED_AT
        )
        is False
    )


async def test_clear_sync_request_clears_only_that_users_request(provider_repo, make_user):
    mine = await make_user(101)
    theirs = await make_user(102)
    for user_id in (mine, theirs):
        await provider_repo.request_sync(
            provider=Provider.STRAVA, user_id=user_id, now=REQUESTED_AT
        )

    await provider_repo.clear_sync_request(provider=Provider.STRAVA, user_id=mine)

    assert await provider_repo.get_sync_requested_at(provider=Provider.STRAVA, user_id=mine) is None
    assert (
        await provider_repo.get_sync_requested_at(provider=Provider.STRAVA, user_id=theirs)
        == REQUESTED_AT
    )


async def test_clear_sync_request_without_a_request_changes_nothing(provider_repo, make_user):
    user_id = await make_user(101)

    await provider_repo.clear_sync_request(provider=Provider.STRAVA, user_id=user_id)

    assert (
        await provider_repo.get_sync_requested_at(provider=Provider.STRAVA, user_id=user_id) is None
    )


async def test_clear_provider_credentials_clears_a_pending_sync_request(provider_repo, make_user):
    user_id = await make_user(101)
    await provider_repo.request_sync(provider=Provider.STRAVA, user_id=user_id, now=REQUESTED_AT)

    await provider_repo.clear_provider_credentials(provider=Provider.STRAVA, user_id=user_id)

    assert (
        await provider_repo.get_sync_requested_at(provider=Provider.STRAVA, user_id=user_id) is None
    )


# ---------- list_users_with_expired_tokens ----------

EXPIRED_BEFORE = datetime(2026, 11, 1, tzinfo=UTC)


def _expiring(days: float) -> int:
    """A Unix timestamp ``days`` after ``EXPIRED_BEFORE``; negative is before it."""
    return int((EXPIRED_BEFORE + timedelta(days=days)).timestamp())


async def _expired(provider_repo, *, limit: int = 20) -> list[str]:
    return await provider_repo.list_users_with_expired_tokens(
        Provider.GARMIN, expired_before=EXPIRED_BEFORE, limit=limit
    )


async def test_list_users_with_expired_tokens_lists_the_longest_expired_first(
    provider_repo, link_user
):
    await link_user("user-a", 1, provider=Provider.GARMIN, expires_at=_expiring(-1))
    await link_user("user-b", 2, provider=Provider.GARMIN, expires_at=_expiring(-30))
    await link_user("user-c", 3, provider=Provider.GARMIN, expires_at=_expiring(-5))

    assert await _expired(provider_repo) == ["user-b", "user-c", "user-a"]


async def test_list_users_with_expired_tokens_leaves_tokens_expiring_later(
    provider_repo, link_user
):
    await link_user("user-a", 1, provider=Provider.GARMIN, expires_at=_expiring(0))
    await link_user("user-b", 2, provider=Provider.GARMIN, expires_at=_expiring(1))
    await link_user("user-c", 3, provider=Provider.GARMIN, expires_at=None)

    assert await _expired(provider_repo) == []


async def test_list_users_with_expired_tokens_takes_at_most_limit(provider_repo, link_user):
    for n in range(1, 5):
        await link_user(f"user-{n}", n, provider=Provider.GARMIN, expires_at=_expiring(-n))

    assert await _expired(provider_repo, limit=2) == ["user-4", "user-3"]


async def test_list_users_with_expired_tokens_leaves_disconnected_users(provider_repo, link_user):
    await link_user("user-a", 1, provider=Provider.GARMIN, expires_at=_expiring(-5))
    await link_user("user-b", 2, provider=Provider.GARMIN, expires_at=_expiring(-5))
    await provider_repo.clear_provider_credentials(provider=Provider.GARMIN, user_id="user-a")

    assert await _expired(provider_repo) == ["user-b"]


async def test_list_users_with_expired_tokens_is_scoped_to_the_provider(provider_repo, link_user):
    await link_user("user-a", 1, provider=Provider.STRAVA, expires_at=_expiring(-5))
    await link_user("user-b", 2, provider=Provider.GARMIN, expires_at=_expiring(-5))

    assert await _expired(provider_repo) == ["user-b"]
    assert await provider_repo.list_users_with_expired_tokens(
        Provider.STRAVA, expired_before=EXPIRED_BEFORE, limit=20
    ) == ["user-a"]
