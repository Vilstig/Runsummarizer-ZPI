"""Intervals.icu's rate-limit budget: its rolling 15-minute and daily windows, the share of
them each import priority may use, the usage its responses report, and how long a 429
pauses its calls.

Every function takes a timezone-aware ``now`` and works in UTC.
"""

from datetime import datetime, timedelta

import httpx

from app.domain.enums import ImportPriority, WindowKind
from app.domain.models import BudgetPolicy, BudgetWindow, RateLimitUsage, WindowUsage

DEFAULT_RATE_LIMITED_PAUSE_SECONDS = 60  # when a 429 carries no usable Retry-After

# Intervals.icu's documented minimums: a rolling 15-minute window, bucketed by the minute,
# and a fixed UTC day. The default limits are the lowest Intervals.icu guarantees an app.
WINDOW_15M = BudgetWindow(
    name="15m",
    length=timedelta(minutes=15),
    kind=WindowKind.ROLLING,
    bucket=timedelta(minutes=1),
    default_limit=2500,
)
WINDOW_DAY = BudgetWindow(
    name="day",
    length=timedelta(days=1),
    kind=WindowKind.FIXED,
    bucket=timedelta(days=1),
    default_limit=5000,
)

CEILINGS = {
    ImportPriority.WEBHOOK: {WINDOW_15M.name: 95, WINDOW_DAY.name: 95},
    ImportPriority.SYNC: {WINDOW_15M.name: 85, WINDOW_DAY.name: 85},
}


def rate_limit_usage(headers: httpx.Headers) -> RateLimitUsage | None:
    """The usage Intervals.icu reports in ``headers``
    (``X-RateLimit-Limit``/``X-RateLimit-Remaining``: ``"<15m>,<day>"``), or None when a
    header is missing or malformed.
    """
    try:
        limit_15m, limit_day = (int(v) for v in headers["X-RateLimit-Limit"].split(","))
        remaining_15m, remaining_day = (int(v) for v in headers["X-RateLimit-Remaining"].split(","))
        return RateLimitUsage(
            {
                WINDOW_15M.name: WindowUsage(used=limit_15m - remaining_15m, limit=limit_15m),
                WINDOW_DAY.name: WindowUsage(used=limit_day - remaining_day, limit=limit_day),
            }
        )
    except (KeyError, ValueError):
        return None


def observe_usage(response: httpx.Response) -> RateLimitUsage | None:
    """The usage Intervals.icu reports with ``response``."""
    return rate_limit_usage(response.headers)


INTERVALS_BUDGET_POLICY = BudgetPolicy(
    windows=(WINDOW_15M, WINDOW_DAY),
    ceilings=CEILINGS,
    observe=observe_usage,
)


def rate_limited_until(response: httpx.Response, now: datetime) -> datetime:
    """When Intervals.icu calls may resume after a 429 at ``now``: ``now`` plus the
    response's ``Retry-After`` seconds, or ``DEFAULT_RATE_LIMITED_PAUSE_SECONDS`` when it is
    missing or isn't a number.
    """
    try:
        seconds = int(response.headers["Retry-After"])
    except (KeyError, ValueError):
        seconds = DEFAULT_RATE_LIMITED_PAUSE_SECONDS
    return now + timedelta(seconds=seconds)
