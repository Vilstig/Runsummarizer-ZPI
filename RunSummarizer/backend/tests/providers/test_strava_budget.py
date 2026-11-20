from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from app.domain.enums import ImportPriority, WindowKind
from app.domain.models import RateLimitUsage, WindowUsage
from app.providers.strava.budget import (
    STRAVA_BUDGET_POLICY,
    WINDOW_15M,
    WINDOW_DAY,
    next_utc_midnight,
    next_window_start,
    observe_usage,
    rate_limit_usage,
    rate_limited_until,
)

PLUS_TWO = timezone(timedelta(hours=2))


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def usage(used_15m: int, used_day: int, limit_15m: int = 100, limit_day: int = 1000):
    return RateLimitUsage(
        {
            "15m": WindowUsage(used=used_15m, limit=limit_15m),
            "day": WindowUsage(used=used_day, limit=limit_day),
        }
    )


# ---------- policy ----------


def test_strava_has_fixed_15_minute_and_daily_windows_with_its_default_limits():
    assert STRAVA_BUDGET_POLICY.windows == (WINDOW_15M, WINDOW_DAY)
    assert (WINDOW_15M.name, WINDOW_15M.length, WINDOW_15M.kind, WINDOW_15M.default_limit) == (
        "15m",
        timedelta(minutes=15),
        WindowKind.FIXED,
        100,
    )
    assert (WINDOW_DAY.name, WINDOW_DAY.length, WINDOW_DAY.kind, WINDOW_DAY.default_limit) == (
        "day",
        timedelta(days=1),
        WindowKind.FIXED,
        1000,
    )


@pytest.mark.parametrize(
    ("priority", "percent"), [(ImportPriority.WEBHOOK, 95), (ImportPriority.SYNC, 85)]
)
def test_each_priority_may_fill_its_share_of_both_windows(priority, percent):
    for window in STRAVA_BUDGET_POLICY.windows:
        assert STRAVA_BUDGET_POLICY.ceiling(priority, window) == percent


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 6, 10, 0), utc(2026, 10, 6, 10, 0)),
        (utc(2026, 10, 6, 10, 14, 59, 999_999), utc(2026, 10, 6, 10, 0)),
        (utc(2026, 10, 6, 10, 15), utc(2026, 10, 6, 10, 15)),
        (utc(2026, 10, 6, 23, 59, 59), utc(2026, 10, 6, 23, 45)),
        (datetime(2026, 10, 6, 12, 7, tzinfo=PLUS_TWO), utc(2026, 10, 6, 10, 0)),
    ],
    ids=["on-a-boundary", "just-before-the-next", "next-boundary", "last-window", "not-utc"],
)
def test_the_15_minute_window_starts_at_a_quarter_hour_utc(now, expected):
    start = WINDOW_15M.bucket_start(now)

    assert start == expected
    assert start.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 6, 23, 59), utc(2026, 10, 6)),
        (datetime(2026, 10, 7, 1, 0, tzinfo=PLUS_TWO), utc(2026, 10, 6)),
    ],
    ids=["utc", "not-utc"],
)
def test_the_daily_window_starts_at_utc_midnight(now, expected):
    assert WINDOW_DAY.bucket_start(now) == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 6, 10, 7), utc(2026, 10, 6, 10, 15)),
        (utc(2026, 10, 6, 10, 15), utc(2026, 10, 6, 10, 30)),
        (utc(2026, 10, 6, 23, 50), utc(2026, 10, 7, 0, 0)),
        (datetime(2026, 10, 6, 12, 7, tzinfo=PLUS_TWO), utc(2026, 10, 6, 10, 15)),
    ],
    ids=["inside-a-window", "on-a-boundary", "across-midnight", "not-utc"],
)
def test_next_window_start(now, expected):
    assert next_window_start(now) == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 6, 10, 7), utc(2026, 10, 7)),
        (utc(2026, 10, 6), utc(2026, 10, 7)),
        (datetime(2026, 10, 7, 1, 0, tzinfo=PLUS_TWO), utc(2026, 10, 7)),
    ],
    ids=["during-the-day", "on-midnight", "not-utc"],
)
def test_next_utc_midnight(now, expected):
    assert next_utc_midnight(now) == expected


# ---------- usage ----------


def test_the_read_rate_limit_headers_give_the_usage_of_both_windows():
    headers = httpx.Headers(
        {"X-ReadRateLimit-Limit": "100,1000", "X-ReadRateLimit-Usage": "37,512"}
    )

    assert rate_limit_usage(headers) == usage(37, 512)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-ReadRateLimit-Limit": "100,1000"},
        {"X-ReadRateLimit-Limit": "100", "X-ReadRateLimit-Usage": "37,512"},
        {"X-ReadRateLimit-Limit": "100,1000", "X-ReadRateLimit-Usage": "lots,512"},
    ],
    ids=["missing", "no-usage", "one-value", "not-a-number"],
)
def test_missing_or_malformed_rate_limit_headers_give_no_usage(headers):
    assert rate_limit_usage(httpx.Headers(headers)) is None


def test_the_policy_observes_the_usage_of_a_response():
    response = httpx.Response(
        200, headers={"X-ReadRateLimit-Limit": "200,2000", "X-ReadRateLimit-Usage": "5,50"}
    )

    assert STRAVA_BUDGET_POLICY.observe is observe_usage
    assert observe_usage(response) == usage(5, 50, 200, 2000)


# ---------- rate_limited_until ----------


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        (usage(100, 400), utc(2026, 10, 6, 10, 15)),
        (usage(100, 1000), utc(2026, 10, 7)),
        (usage(100, 1003), utc(2026, 10, 7)),
        (None, utc(2026, 10, 6, 10, 15)),
    ],
    ids=["15-minute-limit", "daily-limit", "past-the-daily-limit", "no-usage"],
)
def test_rate_limited_until(reported, expected):
    assert rate_limited_until(reported, utc(2026, 10, 6, 10, 7)) == expected
