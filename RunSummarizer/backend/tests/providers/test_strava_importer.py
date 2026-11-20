"""StravaImporter on its own: the cost of an item, fetching a payload with the given
credentials, the errors it raises, and normalizing a payload.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.db.protocols.import_queue import Claim, QueuedItem
from app.domain.enums import ImportPriority, ImportSource
from app.domain.errors import (
    ProviderActivityNotFoundError,
    ProviderAuthorizationError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials, ZoneTimes
from app.providers.strava.importer import ITEM_COST, StravaImporter
from tests.services.fakes import FakeStrava, run_payload, strava_run, strava_usage

pytestmark = pytest.mark.anyio

KEY = "strava_7"
DETAIL = "/api/v3/activities/7"
STREAMS = "/api/v3/activities/7/streams"

NOW = datetime(2026, 10, 8, 12, 7, tzinfo=UTC)
NEXT_WINDOW = datetime(2026, 10, 8, 12, 15, tzinfo=UTC)
NEXT_MIDNIGHT = datetime(2026, 10, 9, tzinfo=UTC)
CREDENTIALS = ProviderCredentials("access-1", "refresh-1", expires_at=None)
CLAIM = Claim("user-1", "strava", KEY, generation=0, attempts=1, lease_token=uuid.uuid4())


class Responses:
    """A ``ResponseObserver`` that records what it is passed."""

    def __init__(self):
        self.seen: list[tuple[str, int, datetime]] = []  # (path, status, sent_at)

    async def __call__(self, response: httpx.Response, sent_at: datetime) -> None:
        self.seen.append((response.request.url.path, response.status_code, sent_at))


@pytest.fixture
def strava() -> FakeStrava:
    return FakeStrava()


async def fetch(strava: FakeStrava, responses: Responses | None = None) -> dict | None:
    importer = StravaImporter(transport=strava.transport, clock=lambda: NOW)
    return await importer.fetch(CLAIM, CREDENTIALS, responses or Responses())


# ---------- cost ----------


@pytest.mark.parametrize("priority", list(ImportPriority), ids=lambda p: p.name.lower())
def test_every_item_costs_the_same(priority):
    item = QueuedItem("user-1", "strava", KEY, ImportSource.SYNC, priority, 0, None)

    assert StravaImporter().cost(item) == ITEM_COST


# ---------- fetch ----------


async def test_a_run_is_fetched_with_its_detail_and_streams(strava):
    strava.add(strava_run(7))

    assert await fetch(strava) == run_payload(7)
    assert [r.url.path for r in strava.requests] == [DETAIL, STREAMS]
    assert {r.headers["Authorization"] for r in strava.requests} == {"Bearer access-1"}


async def test_an_activity_that_is_not_a_run_is_none(strava):
    strava.add(strava_run(7, activity_type="Ride"))

    assert await fetch(strava) is None
    assert [r.url.path for r in strava.requests] == [DETAIL]


async def test_every_response_is_passed_to_the_observer(strava):
    strava.add(strava_run(7))
    responses = Responses()

    await fetch(strava, responses)

    assert responses.seen == [(DETAIL, 200, NOW), (STREAMS, 200, NOW)]


async def test_an_error_response_is_passed_to_the_observer_before_it_raises(strava):
    strava.fail(DETAIL, 429)
    responses = Responses()

    with pytest.raises(RateLimitedError):
        await fetch(strava, responses)

    assert responses.seen == [(DETAIL, 429, NOW)]


@pytest.mark.parametrize(
    ("usage", "until"),
    [
        (strava_usage(100, 400, 100, 1000), NEXT_WINDOW),
        (strava_usage(100, 1000, 100, 1000), NEXT_MIDNIGHT),
        (None, NEXT_WINDOW),
    ],
    ids=["15-minute-limit", "daily-limit", "no-usage"],
)
async def test_a_429_is_rate_limited_until_strava_calls_may_resume(strava, usage, until):
    strava.usage = usage
    strava.add(strava_run(7))
    strava.fail(STREAMS, 429)

    with pytest.raises(RateLimitedError) as raised:
        await fetch(strava)

    assert raised.value.until == until


@pytest.mark.parametrize(
    ("path", "outcome", "error"),
    [
        (DETAIL, 401, ProviderAuthorizationError),
        (STREAMS, 403, ProviderAuthorizationError),
        (DETAIL, 404, ProviderActivityNotFoundError),
        (DETAIL, 500, ProviderUnavailableError),
        (STREAMS, httpx.ReadTimeout("timed out"), ProviderUnavailableError),
        (DETAIL, httpx.ConnectError("connection refused"), ProviderUnavailableError),
    ],
    ids=["401", "403", "404", "500", "timeout", "connection-error"],
)
async def test_strava_errors_raise_generic_fetch_errors(strava, path, outcome, error):
    strava.add(strava_run(7))
    strava.fail(path, outcome)

    with pytest.raises(error):
        await fetch(strava)


async def test_an_activity_without_streams_has_empty_streams(strava):
    strava.add(strava_run(7))
    strava.fail(STREAMS, 404)

    payload = await fetch(strava)

    assert payload["streams"] == {}


# ---------- normalize ----------


def test_normalize_keeps_the_detail_as_the_stored_payload():
    normalized = StravaImporter().normalize(run_payload(7))

    assert normalized.payload_kind == "strava_detail"
    assert normalized.stored_payload == strava_run(7)
    assert normalized.activity.key == KEY
    assert normalized.activity.zone_times == ZoneTimes()


def test_normalize_keys_the_streams_by_the_apps_names():
    normalized = StravaImporter().normalize(run_payload(7))

    assert normalized.streams == {
        "time": [0, 1, 2],
        "distance": [0.0, 3.0, 6.0],
        "heartrate": [140, 150, 160],
        "velocity": [3.0, 3.0, 3.0],
        "altitude": [100.0, 100.5, 101.0],
    }


def test_normalize_reads_an_untagged_payload_as_strava_v1():
    untagged = run_payload(7)
    del untagged["format"]

    assert StravaImporter().normalize(untagged) == StravaImporter().normalize(run_payload(7))


def test_normalize_raises_on_an_unknown_format():
    with pytest.raises(ValueError, match="strava_v9"):
        StravaImporter().normalize({**run_payload(7), "format": "strava_v9"})
