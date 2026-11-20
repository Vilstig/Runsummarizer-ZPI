"""IntervalsImporter on its own: the cost of an item, fetching a payload with the given
credentials, the errors it raises, and normalizing a payload.
"""

import uuid
from datetime import UTC, datetime, timedelta

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
from app.providers.intervals.importer import ITEM_COST, IntervalsImporter
from app.providers.intervals.normalizer import build_payload
from tests.providers.fit.fit_builder import activity_mesg, build_fit, record_mesg, session_mesg
from tests.providers.intervals.fakes import FakeIntervals, intervals_activity

pytestmark = pytest.mark.anyio

KEY = "intervals_i7"
DETAIL = "/api/v1/activity/i7"
FILE = "/api/v1/activity/i7/file"

NOW = datetime(2026, 10, 8, 12, 7, tzinfo=UTC)
CREDENTIALS = ProviderCredentials("access-1", None, None)
CLAIM = Claim("user-1", "intervals", KEY, generation=0, attempts=1, lease_token=uuid.uuid4())


def running_fit() -> bytes:
    return build_fit(
        sessions=(
            session_mesg(total_distance=2000.0, total_timer_time=600.0, enhanced_avg_speed=3.333),
        ),
        records=(record_mesg(0, distance=0.0, enhanced_speed=3.2),),
        activity=activity_mesg(7200),
    )


class Responses:
    """A ``ResponseObserver`` that records what it is passed."""

    def __init__(self):
        self.seen: list[tuple[str, int, datetime]] = []  # (path, status, sent_at)

    async def __call__(self, response: httpx.Response, sent_at: datetime) -> None:
        self.seen.append((response.request.url.path, response.status_code, sent_at))


@pytest.fixture
def intervals() -> FakeIntervals:
    return FakeIntervals()


async def fetch(intervals: FakeIntervals, responses: Responses | None = None) -> dict | None:
    importer = IntervalsImporter(transport=intervals.transport, clock=lambda: NOW)
    return await importer.fetch(CLAIM, CREDENTIALS, responses or Responses())


# ---------- cost ----------


@pytest.mark.parametrize("priority", list(ImportPriority), ids=lambda p: p.name.lower())
def test_every_item_costs_the_same(priority):
    item = QueuedItem("user-1", "intervals", KEY, ImportSource.SYNC, priority, 0, None)

    assert IntervalsImporter().cost(item) == ITEM_COST


# ---------- fetch ----------


async def test_a_run_is_fetched_with_its_detail_and_file(intervals):
    intervals.add(intervals_activity("i7", file_type="fit"), file=b"FIT-BYTES")

    payload = await fetch(intervals)

    assert payload["file_source"] == "original"
    assert [r.url.path for r in intervals.requests] == [DETAIL, FILE]
    assert {r.headers["Authorization"] for r in intervals.requests} == {"Bearer access-1"}


async def test_an_activity_that_is_not_a_run_is_none(intervals):
    intervals.add(intervals_activity("i7", activity_type="Ride", file_type="fit"), file=b"x")

    assert await fetch(intervals) is None
    assert [r.url.path for r in intervals.requests] == [DETAIL]


async def test_every_response_is_passed_to_the_observer(intervals):
    intervals.add(intervals_activity("i7", file_type="fit"), file=b"x")
    responses = Responses()

    await fetch(intervals, responses)

    assert responses.seen == [(DETAIL, 200, NOW), (FILE, 200, NOW)]


async def test_an_error_response_is_passed_to_the_observer_before_it_raises(intervals):
    intervals.fail(DETAIL, 429)
    responses = Responses()

    with pytest.raises(RateLimitedError):
        await fetch(intervals, responses)

    assert responses.seen == [(DETAIL, 429, NOW)]


async def test_a_429_is_rate_limited_until_retry_after_elapses(intervals):
    intervals.fail(DETAIL, 429)
    intervals.retry_after = 45

    with pytest.raises(RateLimitedError) as raised:
        await fetch(intervals)

    assert raised.value.until == NOW + timedelta(seconds=45)


@pytest.mark.parametrize(
    ("path", "outcome", "error"),
    [
        (DETAIL, 401, ProviderAuthorizationError),
        (FILE, 403, ProviderAuthorizationError),
        (DETAIL, 404, ProviderActivityNotFoundError),
        (DETAIL, 500, ProviderUnavailableError),
        (FILE, httpx.ReadTimeout("timed out"), ProviderUnavailableError),
        (DETAIL, httpx.ConnectError("connection refused"), ProviderUnavailableError),
    ],
    ids=["401", "403", "404", "500", "timeout", "connection-error"],
)
async def test_intervals_errors_raise_generic_fetch_errors(intervals, path, outcome, error):
    intervals.add(intervals_activity("i7", file_type="fit"), file=b"x")
    intervals.fail(path, outcome)

    with pytest.raises(error):
        await fetch(intervals)


async def test_a_file_that_has_since_disappeared_gives_none(intervals):
    intervals.add(intervals_activity("i7", file_type="fit"))  # no file added -> 404 on download

    assert await fetch(intervals) is None


# ---------- normalize ----------


def test_normalize_keeps_the_activity_as_the_stored_payload():
    activity = intervals_activity("i7")
    payload = build_payload(activity, file_source="original", file=running_fit())

    normalized = IntervalsImporter().normalize(payload)

    assert normalized.payload_kind == "intervals_activity"
    assert normalized.stored_payload == activity
    assert normalized.activity.key == KEY
    assert normalized.activity.zone_times == ZoneTimes()


def test_normalize_reads_an_untagged_payload_as_intervals_v1():
    untagged = build_payload(intervals_activity("i7"), file_source="original", file=running_fit())
    del untagged["format"]

    tagged = build_payload(intervals_activity("i7"), file_source="original", file=running_fit())

    assert IntervalsImporter().normalize(untagged) == IntervalsImporter().normalize(tagged)


def test_normalize_raises_on_an_unknown_format():
    payload = build_payload(intervals_activity("i7"), file_source="original", file=running_fit())
    payload["format"] = "intervals_v9"

    with pytest.raises(ValueError, match="intervals_v9"):
        IntervalsImporter().normalize(payload)
