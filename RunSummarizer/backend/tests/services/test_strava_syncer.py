"""start_sync with StravaSyncer: the token refresh, queueing the listed runs, the
pause on Strava calls and recording their usage.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

import httpx
import pytest

from app.domain.enums import Provider
from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderNotConnectedError,
    ProviderPausedError,
    ProviderUnavailableError,
)
from app.providers.base import SyncWindow
from app.providers.registry import PROVIDERS
from app.providers.strava.oauth import StravaTokenRefresher
from app.providers.strava.syncer import StravaSyncer
from app.services import sync
from app.services.sync import SYNC_SPACING
from tests.services.fakes import REFRESHED, TokenUpdate, strava_run, strava_usage

pytestmark = pytest.mark.anyio

USER_ID = "user-1"

LISTING = "/api/v3/athlete/activities"

NOW = datetime(2026, 10, 11, 12, 7, tzinfo=UTC)
NEXT_WINDOW = datetime(2026, 10, 11, 12, 15, tzinfo=UTC)
WINDOW = SyncWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))


@pytest.fixture(autouse=True)
def connected(db):
    """The user's stored Strava tokens, with an access token that has expired."""
    db.add_strava_user(USER_ID, 101, "refresh-1")


def listing(strava) -> httpx.Request:
    [request] = [r for r in strava.requests if r.url.path == LISTING]
    return request


# ---------- start_sync with StravaSyncer ----------


async def start_sync(db, strava, **kwargs) -> sync.SyncStarted:
    definition = replace(
        PROVIDERS[Provider.STRAVA],
        syncer=lambda: StravaSyncer(transport=strava.transport, clock=lambda: NOW),
        token_refresher=StravaTokenRefresher(transport=strava.transport, clock=lambda: NOW),
    )
    return await sync.start_sync(
        Provider.STRAVA,
        USER_ID,
        definition=definition,
        transaction=db.transaction,
        clock=lambda: NOW,
        **kwargs,
    )


async def test_a_strava_sync_lists_with_the_refreshed_access_token(db, strava):
    await start_sync(db, strava)

    refresh, listed = strava.requests
    assert refresh.url.path == "/oauth/token"
    assert listed.headers["Authorization"] == f"Bearer {REFRESHED.access_token}"


async def test_a_user_without_strava_tokens_is_not_connected(db, strava):
    del db.credentials[USER_ID]

    with pytest.raises(ProviderNotConnectedError):
        await start_sync(db, strava)

    assert strava.requests == []


async def test_a_rejected_token_refresh_raises_an_authorization_error(db, strava):
    strava.fail("/oauth/token", 400)

    with pytest.raises(ProviderAuthorizationError):
        await start_sync(db, strava)

    assert [r.url.path for r in strava.requests] == ["/oauth/token"]


async def test_a_rotated_token_is_saved_even_when_the_listing_then_fails(db, strava):
    strava.fail(LISTING, 500)

    with pytest.raises(ProviderUnavailableError):
        await start_sync(db, strava)

    assert db.token_updates == [TokenUpdate(Provider.STRAVA, USER_ID, REFRESHED)]


async def test_a_strava_sync_queues_the_newest_run_first_spaced_apart(db, strava):
    strava.add(strava_run(1, start_date="2026-10-01T06:00:00Z"))
    strava.add(strava_run(2, start_date="2026-10-09T06:00:00Z"))
    strava.add(strava_run(3, start_date="2026-10-05T06:00:00Z"))

    started = await start_sync(db, strava)

    assert started == sync.SyncStarted(queued=3, requested=False)
    items = sorted(db.import_items.values(), key=lambda item: item.sort_key)
    assert [(item.activity_key, item.sort_key) for item in items] == [
        ("strava_2", NOW + SYNC_SPACING),
        ("strava_3", NOW + 2 * SYNC_SPACING),
        ("strava_1", NOW + 3 * SYNC_SPACING),
    ]


async def test_a_strava_sync_lists_the_requested_days(db, strava):
    await start_sync(db, strava, after=date(2026, 9, 1), before=date(2026, 10, 1))

    assert listing(strava).url.params["after"] == str(int(WINDOW.start.timestamp()))
    assert listing(strava).url.params["before"] == str(int(WINDOW.end.timestamp()))


async def test_a_429_on_a_strava_sync_pauses_strava_and_queues_nothing(db, strava):
    strava.add(strava_run(1))
    strava.fail(LISTING, 429)

    with pytest.raises(ProviderPausedError) as raised:
        await start_sync(db, strava)

    assert (raised.value.provider, raised.value.until) == (Provider.STRAVA, NEXT_WINDOW)
    assert db.budget("strava").paused_until == NEXT_WINDOW
    assert db.import_items == {}


async def test_a_revoked_strava_authorization_queues_nothing(db, strava):
    strava.add(strava_run(1))
    strava.fail(LISTING, 401)

    with pytest.raises(ProviderAuthorizationError):
        await start_sync(db, strava)

    assert db.import_items == {}


async def test_the_rate_limit_usage_of_the_listing_is_recorded(db, strava):
    strava.usage = strava_usage(10, 200, 200, 2000)

    await start_sync(db, strava)

    assert db.budget("strava").usage_reports == [strava.usage]


async def test_paused_strava_calls_hold_a_strava_sync_back_without_calling_strava(db, strava):
    db.budget("strava").paused_until = NEXT_WINDOW

    with pytest.raises(ProviderPausedError) as raised:
        await start_sync(db, strava)

    assert raised.value.until == NEXT_WINDOW
    assert strava.requests == []


async def test_a_pause_that_has_ended_does_not_hold_a_strava_sync_back(db, strava):
    db.budget("strava").paused_until = NOW
    strava.add(strava_run(1))

    started = await start_sync(db, strava)

    assert started.queued == 1


async def test_a_429_on_the_token_refresh_pauses_strava(db, strava):
    strava.fail("/oauth/token", 429)

    with pytest.raises(ProviderPausedError) as raised:
        await start_sync(db, strava)

    assert raised.value.until == NEXT_WINDOW
    assert db.budget("strava").paused_until == NEXT_WINDOW
    assert [r.url.path for r in strava.requests] == ["/oauth/token"]
