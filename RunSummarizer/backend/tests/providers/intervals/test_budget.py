from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.domain.enums import ImportPriority, WindowKind
from app.domain.models import RateLimitUsage, WindowUsage
from app.providers.intervals.budget import (
    DEFAULT_RATE_LIMITED_PAUSE_SECONDS,
    INTERVALS_BUDGET_POLICY,
    WINDOW_15M,
    WINDOW_DAY,
    observe_usage,
    rate_limit_usage,
    rate_limited_until,
)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def usage(used_15m: int, used_day: int, limit_15m: int = 2500, limit_day: int = 5000):
    return RateLimitUsage(
        {
            "15m": WindowUsage(used=used_15m, limit=limit_15m),
            "day": WindowUsage(used=used_day, limit=limit_day),
        }
    )


# ---------- policy ----------


def test_the_15_minute_window_is_rolling_and_the_day_is_fixed():
    assert INTERVALS_BUDGET_POLICY.windows == (WINDOW_15M, WINDOW_DAY)
    assert (WINDOW_15M.name, WINDOW_15M.kind, WINDOW_15M.bucket, WINDOW_15M.default_limit) == (
        "15m",
        WindowKind.ROLLING,
        timedelta(minutes=1),
        2500,
    )
    assert (WINDOW_DAY.name, WINDOW_DAY.kind, WINDOW_DAY.bucket, WINDOW_DAY.default_limit) == (
        "day",
        WindowKind.FIXED,
        timedelta(days=1),
        5000,
    )


@pytest.mark.parametrize(
    ("priority", "percent"), [(ImportPriority.WEBHOOK, 95), (ImportPriority.SYNC, 85)]
)
def test_each_priority_may_fill_its_share_of_both_windows(priority, percent):
    for window in INTERVALS_BUDGET_POLICY.windows:
        assert INTERVALS_BUDGET_POLICY.ceiling(priority, window) == percent


# ---------- usage ----------


def test_the_rate_limit_headers_give_the_usage_of_both_windows():
    headers = httpx.Headers(
        {"X-RateLimit-Limit": "2500,5000", "X-RateLimit-Remaining": "2463,4488"}
    )

    assert rate_limit_usage(headers) == usage(37, 512)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-RateLimit-Limit": "2500,5000"},
        {"X-RateLimit-Limit": "2500", "X-RateLimit-Remaining": "2463,4488"},
        {"X-RateLimit-Limit": "2500,5000", "X-RateLimit-Remaining": "lots,4488"},
    ],
    ids=["missing", "no-remaining", "one-value", "not-a-number"],
)
def test_missing_or_malformed_rate_limit_headers_give_no_usage(headers):
    assert rate_limit_usage(httpx.Headers(headers)) is None


def test_the_policy_observes_the_usage_of_a_response():
    response = httpx.Response(
        200, headers={"X-RateLimit-Limit": "2500,5000", "X-RateLimit-Remaining": "2400,4900"}
    )

    assert INTERVALS_BUDGET_POLICY.observe is observe_usage
    assert observe_usage(response) == usage(100, 100)


# ---------- rate_limited_until ----------


def test_rate_limited_until_waits_the_retry_after_seconds():
    response = httpx.Response(429, headers={"Retry-After": "90"})

    assert rate_limited_until(response, utc(2026, 10, 6, 10, 7)) == utc(
        2026, 10, 6, 10, 7
    ) + timedelta(seconds=90)


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "soon"}], ids=["missing", "not-a-number"])
def test_rate_limited_until_falls_back_to_the_default_pause_without_a_usable_header(headers):
    response = httpx.Response(429, headers=headers)

    assert rate_limited_until(response, utc(2026, 10, 6, 10, 7)) == utc(
        2026, 10, 6, 10, 7
    ) + timedelta(seconds=DEFAULT_RATE_LIMITED_PAUSE_SECONDS)
