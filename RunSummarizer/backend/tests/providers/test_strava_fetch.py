"""fetch_strava_payload: the calls a Strava activity's payload takes, and their errors."""

import json

import httpx
import pytest

from app.domain.models import ProviderCredentials
from app.providers.strava.client import StravaClient
from app.providers.strava.errors import (
    StravaNotFoundError,
    StravaRateLimitedError,
    StravaUnauthorizedError,
)
from app.providers.strava.fetch import fetch_strava_payload
from tests.services.fakes import STRAVA_TOKEN, FakeStrava, run_payload, strava_run

pytestmark = pytest.mark.anyio

DETAIL = "/api/v3/activities/7"
STREAMS = "/api/v3/activities/7/streams"

# HTTP status -> the error StravaClient raises for it
STRAVA_ERRORS = {
    401: StravaUnauthorizedError,
    403: StravaUnauthorizedError,
    404: StravaNotFoundError,
    429: StravaRateLimitedError,
    500: httpx.HTTPStatusError,
}


@pytest.fixture
def strava() -> FakeStrava:
    return FakeStrava()


async def fetch(strava, activity_id: int = 7) -> dict | None:
    """``fetch_strava_payload`` through a client whose access token is still valid."""
    client = StravaClient(
        ProviderCredentials("access-1", "refresh-1", STRAVA_TOKEN["expires_at"]),
        transport=strava.transport,
    )
    async with client:
        return await fetch_strava_payload(client, activity_id)


def api_paths(strava) -> list[str]:
    """The paths of the Strava API calls made, token requests left out."""
    return [r.url.path for r in strava.requests if r.url.path.startswith("/api/v3/")]


async def test_fetch_returns_the_detail_and_the_streams_of_a_run(strava):
    strava.add(strava_run(7))

    payload = await fetch(strava)

    assert payload == run_payload(7)
    assert api_paths(strava) == [DETAIL, STREAMS]


async def test_fetch_stops_after_the_detail_of_an_activity_that_is_not_a_run(strava):
    strava.add(strava_run(7, activity_type="Ride"))

    assert await fetch(strava) is None
    assert api_paths(strava) == [DETAIL]


async def test_the_payload_is_plain_json(strava):
    strava.add(strava_run(7))

    payload = await fetch(strava)

    assert json.loads(json.dumps(payload)) == payload


async def assert_fetch_raises(strava, path: str, status: int) -> None:
    """Fetching activity 7, with ``path`` answering ``status``, raises the error
    ``StravaClient`` raises for that status.
    """
    error = STRAVA_ERRORS[status]
    strava.add(strava_run(7))
    strava.fail(path, status)

    with pytest.raises(error) as raised:
        await fetch(strava)

    assert type(raised.value) is error
    assert raised.value.response.status_code == status


@pytest.mark.parametrize("status", list(STRAVA_ERRORS))
async def test_fetch_lets_detail_errors_propagate_unchanged(strava, status):
    await assert_fetch_raises(strava, DETAIL, status)


@pytest.mark.parametrize("status", [status for status in STRAVA_ERRORS if status != 404])
async def test_fetch_lets_stream_errors_other_than_404_propagate_unchanged(strava, status):
    await assert_fetch_raises(strava, STREAMS, status)


async def test_fetch_gives_empty_streams_for_an_activity_without_stream_data(strava):
    strava.add(strava_run(7))
    strava.fail(STREAMS, 404)

    payload = await fetch(strava)

    assert payload == {"format": "strava_v1", "detail": strava_run(7), "streams": {}}


@pytest.mark.parametrize("path", [DETAIL, STREAMS], ids=["detail", "streams"])
async def test_fetch_lets_a_timeout_propagate(strava, path):
    strava.add(strava_run(7))
    strava.fail(path, httpx.ReadTimeout("timed out"))

    with pytest.raises(httpx.ReadTimeout):
        await fetch(strava)
