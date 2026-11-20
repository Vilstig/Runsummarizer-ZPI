"""raise_for_api_status and raise_for_token_status: Garmin error statuses to typed errors."""

import httpx
import pytest

from app.providers.garmin.personal_api.errors import (
    GarminNotFoundError,
    GarminRateLimitedError,
    GarminUnauthorizedError,
    raise_for_api_status,
    raise_for_token_status,
)


def response(status: int, headers: dict | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://personal.connectapi.garmin.com/activity-service/1")
    return httpx.Response(status, headers=headers, request=request)


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, GarminUnauthorizedError), (403, GarminUnauthorizedError), (404, GarminNotFoundError)],
)
def test_handled_statuses_raise_typed_errors(status, error):
    with pytest.raises(error):
        raise_for_api_status(response(status))


def test_429_carries_retry_after_seconds():
    with pytest.raises(GarminRateLimitedError) as raised:
        raise_for_api_status(response(429, {"Retry-After": "120"}))
    assert raised.value.retry_after == 120


@pytest.mark.parametrize("header", [{}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}])
def test_429_without_seconds_has_no_retry_after(header):
    with pytest.raises(GarminRateLimitedError) as raised:
        raise_for_api_status(response(429, header))
    assert raised.value.retry_after is None


def test_other_error_statuses_raise_plain_http_errors():
    with pytest.raises(httpx.HTTPStatusError) as raised:
        raise_for_api_status(response(500))
    assert type(raised.value) is httpx.HTTPStatusError


def test_success_doesnt_raise():
    raise_for_api_status(response(200))


def test_a_rejected_token_request_is_unauthorized():
    with pytest.raises(GarminUnauthorizedError):
        raise_for_token_status(response(400))
