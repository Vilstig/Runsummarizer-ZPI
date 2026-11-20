"""Strava's rate-limit budget: its read-limit windows, the share of them each import
priority may use, the usage its responses report, and how long a 429 pauses its calls.

Every function takes a timezone-aware ``now`` and works in UTC.
"""

from datetime import datetime, timedelta

import httpx

from app.domain.enums import ImportPriority, WindowKind
from app.domain.models import BudgetPolicy, BudgetWindow, RateLimitUsage, WindowUsage

# Strava's read limits: per 15-minute window starting at :00, :15, :30 and :45 UTC, and
# per UTC day. The default limits are Strava's defaults for an app.
WINDOW_15M = BudgetWindow(
    name="15m",
    length=timedelta(minutes=15),
    kind=WindowKind.FIXED,
    bucket=timedelta(minutes=15),
    default_limit=100,
)
WINDOW_DAY = BudgetWindow(
    name="day",
    length=timedelta(days=1),
    kind=WindowKind.FIXED,
    bucket=timedelta(days=1),
    default_limit=1000,
)

CEILINGS = {
    ImportPriority.WEBHOOK: {WINDOW_15M.name: 95, WINDOW_DAY.name: 95},
    ImportPriority.SYNC: {WINDOW_15M.name: 85, WINDOW_DAY.name: 85},
}


def rate_limit_usage(headers: httpx.Headers) -> RateLimitUsage | None:
    """The read usage Strava reports in ``headers``, or ``None`` when a header is missing
    or malformed.
    """
    try:
        used_15m, used_day = headers["X-ReadRateLimit-Usage"].split(",")
        limit_15m, limit_day = headers["X-ReadRateLimit-Limit"].split(",")
        return RateLimitUsage(
            {
                WINDOW_15M.name: WindowUsage(used=int(used_15m), limit=int(limit_15m)),
                WINDOW_DAY.name: WindowUsage(used=int(used_day), limit=int(limit_day)),
            }
        )
    except (KeyError, ValueError):
        return None


def observe_usage(response: httpx.Response) -> RateLimitUsage | None:
    """The read usage Strava reports with ``response``."""
    return rate_limit_usage(response.headers)


STRAVA_BUDGET_POLICY = BudgetPolicy(
    windows=(WINDOW_15M, WINDOW_DAY),
    ceilings=CEILINGS,
    observe=observe_usage,
)


def next_window_start(now: datetime) -> datetime:
    """The start of the 15-minute window after the one containing ``now``, in UTC."""
    return WINDOW_15M.bucket_start(now) + WINDOW_15M.length


def next_utc_midnight(now: datetime) -> datetime:
    """The first UTC midnight after ``now``, when Strava's daily limit resets."""
    return WINDOW_DAY.bucket_start(now) + WINDOW_DAY.length


def rate_limited_until(usage: RateLimitUsage | None, now: datetime) -> datetime:
    """When Strava calls may resume after a 429 at ``now``.

    That is the next UTC midnight when ``usage``, the usage reported with the 429,
    shows the daily limit used up, and the next 15-minute window otherwise.
    """
    day = usage.windows.get(WINDOW_DAY.name) if usage is not None else None
    if day is not None and day.used >= day.limit:
        return next_utc_midnight(now)
    return next_window_start(now)
