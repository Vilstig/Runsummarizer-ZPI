"""fresh_credentials: the stored credentials, refreshed under a lock when they expire soon;
refresh_idle_credentials: unused tokens refreshed before they run out."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import anyio
import pytest

from app.domain.enums import Provider
from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    ProviderResponseError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.services.credentials import (
    MAX_CLEARED_PER_PASS,
    REFRESH_MARGIN_S,
    IdleRefresh,
    expires_soon,
    fresh_credentials,
    refresh_idle_credentials,
)
from tests.services.fakes import TokenUpdate

pytestmark = pytest.mark.anyio

USER_ID = "user-1"
NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)
REFRESHED = ProviderCredentials("access-2", "refresh-2", int(NOW.timestamp()) + 21_600)


class FakeRefresher:
    """Counts refreshes; raises ``error`` when it is set."""

    def __init__(self):
        self.refreshed: list[ProviderCredentials] = []
        self.error: Exception | None = None

    async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
        self.refreshed.append(credentials)
        if self.error is not None:
            raise self.error
        return REFRESHED


@pytest.fixture
def refresher() -> FakeRefresher:
    return FakeRefresher()


def store(db, *, expires_at: int | None) -> ProviderCredentials:
    """Store the user's Strava credentials, the access token expiring at ``expires_at``."""
    db.add_strava_user(USER_ID, 101, "refresh-1")
    db.credentials[USER_ID] = ProviderCredentials("access-1", "refresh-1", expires_at)
    return db.credentials[USER_ID]


async def fresh(db, refresher) -> ProviderCredentials:
    return await fresh_credentials(
        Provider.STRAVA, USER_ID, refresher, transaction=db.transaction, clock=lambda: NOW
    )


@pytest.mark.parametrize(
    ("expires_at", "soon"),
    [
        (None, False),
        (int(NOW.timestamp()) + REFRESH_MARGIN_S + 1, False),
        (int(NOW.timestamp()) + REFRESH_MARGIN_S - 1, True),
        (0, True),
    ],
)
def test_expires_soon_leaves_the_margin(expires_at, soon):
    credentials = ProviderCredentials("access", None, expires_at)

    assert expires_soon(credentials, now=NOW) is soon


async def test_a_token_valid_beyond_the_margin_is_used_as_stored(db, refresher):
    stored = store(db, expires_at=int(NOW.timestamp()) + REFRESH_MARGIN_S + 60)

    assert await fresh(db, refresher) == stored
    assert refresher.refreshed == []
    assert db.token_updates == []


async def test_a_token_that_does_not_expire_is_never_refreshed(db, refresher):
    stored = store(db, expires_at=None)

    assert await fresh(db, refresher) == stored
    assert refresher.refreshed == []


async def test_a_token_within_the_margin_is_refreshed_while_locked_and_saved(db, refresher):
    stored = store(db, expires_at=int(NOW.timestamp()) + REFRESH_MARGIN_S - 60)

    assert await fresh(db, refresher) == REFRESHED
    assert refresher.refreshed == [stored]
    assert db.locks == [[USER_ID]]
    assert db.token_updates == [TokenUpdate(Provider.STRAVA, USER_ID, REFRESHED)]


async def test_a_refresh_logs_the_user_it_was_for(db, refresher, caplog):
    caplog.set_level("INFO", logger="app.services.credentials")
    store(db, expires_at=int(NOW.timestamp()) + REFRESH_MARGIN_S - 60)

    await fresh(db, refresher)

    assert "strava" in caplog.text
    assert USER_ID in caplog.text


async def test_a_caller_after_a_refresh_uses_the_saved_tokens(db, refresher):
    store(db, expires_at=0)

    first = await fresh(db, refresher)
    second = await fresh(db, refresher)

    assert first == second == REFRESHED
    assert len(refresher.refreshed) == 1


async def test_a_rejected_refresh_raises_and_saves_nothing(db, refresher):
    stored = store(db, expires_at=0)
    refresher.error = ProviderAuthorizationError("rejected")

    with pytest.raises(ProviderAuthorizationError):
        await fresh(db, refresher)

    assert db.token_updates == []
    assert db.credentials[USER_ID] == stored


async def test_without_a_refresher_the_stored_credentials_are_returned_as_they_are(db):
    stored = store(db, expires_at=0)

    assert await fresh(db, None) == stored
    assert db.locks == [[]]


async def test_a_user_without_credentials_is_not_connected(db, refresher):
    with pytest.raises(ProviderNotConnectedError, match="no strava credentials"):
        await fresh(db, refresher)

    assert refresher.refreshed == []


# ---------- refresh_idle_credentials ----------

IDLE = timedelta(days=30)
GARMIN = Provider.GARMIN


class IdleRefresher:
    """Refreshes each user's tokens; raises ``errors[access token]`` for the ones in it,
    after running ``before_error``, when it is set."""

    def __init__(self):
        self.refreshed: list[str] = []  # access tokens, in order
        self.errors: dict[str, Exception] = {}
        self.before_error: Callable[[], None] | None = None

    async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
        self.refreshed.append(credentials.access_token)
        error = self.errors.get(credentials.access_token)
        if error is not None:
            if self.before_error is not None:
                self.before_error()
            raise error
        return replace(REFRESHED, access_token=f"{credentials.access_token}-new")


def connect_garmin(db, user_id: str, *, expired_days_ago: float) -> ProviderCredentials:
    """Connect the user to Garmin, their access token expired ``expired_days_ago``."""
    expires_at = int((NOW - timedelta(days=expired_days_ago)).timestamp())
    credentials = ProviderCredentials(f"access-{user_id}", f"refresh-{user_id}", expires_at)
    db.provider_credentials[GARMIN, user_id] = credentials
    return credentials


async def refresh_idle(db, refresher, *, limit: int = 20) -> IdleRefresh:
    return await refresh_idle_credentials(
        GARMIN, refresher, IDLE, limit, transaction=db.transaction, clock=lambda: NOW
    )


async def test_tokens_expired_longer_than_idle_ago_are_refreshed_oldest_first(db):
    refresher = IdleRefresher()
    connect_garmin(db, "user-a", expired_days_ago=31)
    recent = connect_garmin(db, "user-b", expired_days_ago=29)
    connect_garmin(db, "user-c", expired_days_ago=45)

    result = await refresh_idle(db, refresher)

    assert result == IdleRefresh(refreshed=2)
    assert refresher.refreshed == ["access-user-c", "access-user-a"]
    assert db.provider_credentials[GARMIN, "user-a"].access_token == "access-user-a-new"
    assert db.provider_credentials[GARMIN, "user-c"].access_token == "access-user-c-new"
    assert db.provider_credentials[GARMIN, "user-b"] == recent


async def test_only_the_providers_tokens_are_refreshed(db):
    refresher = IdleRefresher()
    store(db, expires_at=0)

    assert await refresh_idle(db, refresher) == IdleRefresh()
    assert refresher.refreshed == []


async def test_at_most_limit_users_are_refreshed_in_a_pass(db):
    refresher = IdleRefresher()
    for days, user_id in [(40, "user-a"), (50, "user-b"), (60, "user-c")]:
        connect_garmin(db, user_id, expired_days_ago=days)

    result = await refresh_idle(db, refresher, limit=2)

    assert result == IdleRefresh(refreshed=2)
    assert refresher.refreshed == ["access-user-c", "access-user-b"]
    assert db.provider_credentials[GARMIN, "user-a"].access_token == "access-user-a"


async def test_a_rejected_refresh_clears_the_users_credentials(db):
    refresher = IdleRefresher()
    connect_garmin(db, "user-a", expired_days_ago=40)
    connect_garmin(db, "user-b", expired_days_ago=35)
    refresher.errors["access-user-a"] = ProviderAuthorizationError("invalid_grant")

    result = await refresh_idle(db, refresher)

    assert result == IdleRefresh(refreshed=1, cleared=1)
    assert (GARMIN, "user-a") not in db.provider_credentials
    assert db.provider_credentials[GARMIN, "user-b"].access_token == "access-user-b-new"


async def test_a_rejected_refresh_keeps_tokens_stored_meanwhile(db):
    refresher = IdleRefresher()
    connect_garmin(db, "user-a", expired_days_ago=40)
    reconnected = ProviderCredentials("access-reconnected", "refresh-2", int(NOW.timestamp()) + 600)
    refresher.errors["access-user-a"] = ProviderAuthorizationError("invalid_grant")

    def reconnect() -> None:
        db.provider_credentials[GARMIN, "user-a"] = reconnected

    refresher.before_error = reconnect

    result = await refresh_idle(db, refresher)

    assert result == IdleRefresh()
    assert db.provider_credentials[GARMIN, "user-a"] == reconnected


@pytest.mark.parametrize(
    "error", [ProviderUnavailableError("503"), ProviderResponseError("no token"), KeyError("x")]
)
async def test_another_error_is_logged_and_leaves_the_credentials(db, caplog, error):
    refresher = IdleRefresher()
    stored = connect_garmin(db, "user-a", expired_days_ago=40)
    connect_garmin(db, "user-b", expired_days_ago=35)
    refresher.errors["access-user-a"] = error

    result = await refresh_idle(db, refresher)

    assert result == IdleRefresh(refreshed=1, failed=1)
    assert db.provider_credentials[GARMIN, "user-a"] == stored
    assert "refreshing user user-a's unused tokens failed" in caplog.text


@pytest.mark.parametrize(
    ("error", "level", "traceback"),
    [(ProviderUnavailableError("503"), "WARNING", False), (KeyError("x"), "ERROR", True)],
)
async def test_an_unavailable_provider_is_a_warning_and_a_bug_an_error(
    db, caplog, error, level, traceback
):
    refresher = IdleRefresher()
    connect_garmin(db, "user-a", expired_days_ago=40)
    refresher.errors["access-user-a"] = error

    await refresh_idle(db, refresher)

    [record] = [r for r in caplog.records if "user-a's unused tokens failed" in r.message]
    assert record.levelname == level
    assert (record.exc_info is not None) is traceback


async def test_a_rate_limit_pauses_the_provider_and_ends_the_pass(db):
    refresher = IdleRefresher()
    until = NOW + timedelta(minutes=1)
    connect_garmin(db, "user-a", expired_days_ago=40)
    connect_garmin(db, "user-b", expired_days_ago=35)
    refresher.errors["access-user-a"] = RateLimitedError("429", until=until)

    result = await refresh_idle(db, refresher)

    assert result == IdleRefresh(failed=1)
    assert refresher.refreshed == ["access-user-a"]
    assert db.budget(GARMIN).paused_until == until


async def test_nothing_is_refreshed_while_the_providers_calls_are_paused(db):
    refresher = IdleRefresher()
    connect_garmin(db, "user-a", expired_days_ago=40)
    db.budget(GARMIN).paused_until = NOW + timedelta(minutes=1)

    assert await refresh_idle(db, refresher) == IdleRefresh()
    assert refresher.refreshed == []


async def test_a_pass_clears_at_most_max_cleared_users_and_logs_an_error_for_the_rest(db, caplog):
    refresher = IdleRefresher()
    users = [f"user-{n}" for n in range(MAX_CLEARED_PER_PASS + 2)]
    for n, user_id in enumerate(users):
        connect_garmin(db, user_id, expired_days_ago=60 - n)
        refresher.errors[f"access-{user_id}"] = ProviderAuthorizationError("invalid_grant")

    result = await refresh_idle(db, refresher)

    assert result == IdleRefresh(cleared=MAX_CLEARED_PER_PASS, failed=2)
    assert len(refresher.refreshed) == len(users)
    for user_id in users[:MAX_CLEARED_PER_PASS]:
        assert (GARMIN, user_id) not in db.provider_credentials
    for user_id in users[MAX_CLEARED_PER_PASS:]:
        assert db.provider_credentials[GARMIN, user_id].access_token == f"access-{user_id}"
    kept = [r for r in caplog.records if r.levelname == "ERROR" and "credentials kept" in r.message]
    assert len(kept) == 2


async def test_a_pass_clearing_up_to_max_cleared_users_logs_no_error(db, caplog):
    refresher = IdleRefresher()
    for n in range(MAX_CLEARED_PER_PASS):
        connect_garmin(db, f"user-{n}", expired_days_ago=40)
        refresher.errors[f"access-user-{n}"] = ProviderAuthorizationError("invalid_grant")

    result = await refresh_idle(db, refresher)

    assert result == IdleRefresh(cleared=MAX_CLEARED_PER_PASS)
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_a_refresh_past_the_timeout_is_cut_off_and_the_pass_goes_on(db, caplog):
    class HangingRefresher(IdleRefresher):
        async def refresh(self, credentials):
            if credentials.access_token == "access-user-a":
                self.refreshed.append(credentials.access_token)
                await anyio.sleep_forever()
            return await super().refresh(credentials)

    refresher = HangingRefresher()
    stored = connect_garmin(db, "user-a", expired_days_ago=40)
    connect_garmin(db, "user-b", expired_days_ago=35)

    with anyio.fail_after(5):
        result = await refresh_idle_credentials(
            GARMIN,
            refresher,
            IDLE,
            20,
            refresh_timeout=timedelta(milliseconds=20),
            transaction=db.transaction,
            clock=lambda: NOW,
        )

    assert result == IdleRefresh(refreshed=1, failed=1)
    assert db.provider_credentials[GARMIN, "user-a"] == stored
    assert db.provider_credentials[GARMIN, "user-b"].access_token == "access-user-b-new"
    assert "refreshing user user-a's unused tokens took longer than" in caplog.text


async def test_a_timeout_error_from_the_refresher_itself_is_an_ordinary_failure(db, caplog):
    refresher = IdleRefresher()
    connect_garmin(db, "user-a", expired_days_ago=40)
    refresher.errors["access-user-a"] = TimeoutError("socket")

    result = await refresh_idle_credentials(
        GARMIN,
        refresher,
        IDLE,
        20,
        refresh_timeout=timedelta(seconds=30),
        transaction=db.transaction,
        clock=lambda: NOW,
    )

    assert result == IdleRefresh(failed=1)
    assert "refreshing user user-a's unused tokens failed" in caplog.text
    assert "took longer than" not in caplog.text
