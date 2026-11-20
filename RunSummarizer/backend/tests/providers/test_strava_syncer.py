"""StravaSyncer on its own: listing a user's Strava runs with the given credentials, and
the errors it raises.
"""

from datetime import UTC, datetime

import httpx
import pytest

from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import Listed, ListedActivity, SyncWindow
from app.providers.strava.syncer import StravaSyncer
from tests.services.fakes import FakeStrava, strava_run, strava_usage

pytestmark = pytest.mark.anyio

LISTING = "/api/v3/athlete/activities"

NOW = datetime(2026, 10, 11, 12, 7, tzinfo=UTC)
NEXT_WINDOW = datetime(2026, 10, 11, 12, 15, tzinfo=UTC)
NEXT_MIDNIGHT = datetime(2026, 10, 12, tzinfo=UTC)
WINDOW = SyncWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
CREDENTIALS = ProviderCredentials("access-1", "refresh-1", expires_at=None)


class Responses:
    """A ``ResponseObserver`` that records what it is passed."""

    def __init__(self):
        self.seen: list[tuple[str, int, datetime]] = []  # (path, status, sent_at)

    async def __call__(self, response: httpx.Response, sent_at: datetime) -> None:
        self.seen.append((response.request.url.path, response.status_code, sent_at))


@pytest.fixture
def strava() -> FakeStrava:
    return FakeStrava()


async def start(
    strava: FakeStrava,
    window: SyncWindow | None = WINDOW,
    limit: int | None = None,
    responses: Responses | None = None,
) -> Listed:
    syncer = StravaSyncer(transport=strava.transport, clock=lambda: NOW)
    return await syncer.start(CREDENTIALS, window, limit, responses or Responses())


def listing(strava) -> httpx.Request:
    [request] = [r for r in strava.requests if r.url.path == LISTING]
    return request


async def test_the_runs_are_listed_with_their_keys_and_start_times(strava):
    strava.add(strava_run(1, start_date="2026-09-05T06:00:00Z"))
    strava.add(strava_run(2, start_date="2026-09-09T07:30:00Z"))

    listed = await start(strava)

    assert listed == Listed(
        [
            ListedActivity("strava_1", datetime(2026, 9, 5, 6, tzinfo=UTC)),
            ListedActivity("strava_2", datetime(2026, 9, 9, 7, 30, tzinfo=UTC)),
        ]
    )


async def test_strava_is_called_with_the_given_access_token(strava):
    await start(strava)

    assert listing(strava).headers["Authorization"] == "Bearer access-1"
    assert [r.url.path for r in strava.requests] == [LISTING]


async def test_activities_that_are_not_runs_are_left_out(strava):
    strava.add(strava_run(1))
    strava.add(strava_run(2, activity_type="Ride"))

    listed = await start(strava)

    assert [activity.activity_key for activity in listed.activities] == ["strava_1"]


async def test_the_listing_covers_the_window(strava):
    await start(strava)

    assert listing(strava).url.params["after"] == str(int(WINDOW.start.timestamp()))
    assert listing(strava).url.params["before"] == str(int(WINDOW.end.timestamp()))


async def test_without_a_window_the_newest_runs_up_to_the_limit_are_listed(strava):
    for activity_id in (1, 2, 3):
        strava.add(strava_run(activity_id))

    listed = await start(strava, window=None, limit=2)

    assert len(listed.activities) == 2
    assert "after" not in listing(strava).url.params
    assert "before" not in listing(strava).url.params


async def test_every_response_of_the_listing_is_passed_to_the_observer(strava):
    responses = Responses()

    await start(strava, responses=responses)

    assert responses.seen == [(LISTING, 200, NOW)]


@pytest.mark.parametrize(
    ("usage", "until"),
    [
        (strava_usage(200, 400, 200, 2000), NEXT_WINDOW),
        (strava_usage(200, 2000, 200, 2000), NEXT_MIDNIGHT),
        (None, NEXT_WINDOW),
    ],
    ids=["15-minute-limit", "daily-limit", "no-usage"],
)
async def test_a_429_on_the_listing_is_rate_limited_until_strava_calls_may_resume(
    strava, usage, until
):
    strava.usage = usage
    strava.fail(LISTING, 429)
    responses = Responses()

    with pytest.raises(RateLimitedError) as raised:
        await start(strava, responses=responses)

    assert raised.value.until == until
    assert responses.seen == [(LISTING, 429, NOW)]


@pytest.mark.parametrize("status", [401, 403])
async def test_a_revoked_authorization_raises_an_authorization_error(strava, status):
    strava.fail(LISTING, status)

    with pytest.raises(ProviderAuthorizationError):
        await start(strava)


@pytest.mark.parametrize(
    "outcome",
    [500, httpx.ReadTimeout("timed out"), httpx.ConnectError("connection refused")],
    ids=["500", "timeout", "connection-error"],
)
async def test_a_failing_strava_is_unavailable(strava, outcome):
    strava.fail(LISTING, outcome)

    with pytest.raises(ProviderUnavailableError):
        await start(strava)
