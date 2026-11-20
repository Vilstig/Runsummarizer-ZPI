"""Garmin's rate-limit budget: its activity file download window, the share of it each
import priority may use, and how long a 429 pauses its calls.

Every function takes a timezone-aware ``now``.
"""

from datetime import datetime, timedelta

from app.domain.enums import ImportPriority, WindowKind
from app.domain.models import BudgetPolicy, BudgetWindow

# Garmin's activity file download limit per client ID, counted over the last minute.
WINDOW_1M = BudgetWindow(
    name="1m",
    length=timedelta(minutes=1),
    kind=WindowKind.ROLLING,
    bucket=timedelta(seconds=10),
    default_limit=50,
)

CEILINGS = {
    ImportPriority.WEBHOOK: {WINDOW_1M.name: 80},
    ImportPriority.SYNC: {WINDOW_1M.name: 80},
}

# Garmin's responses report no rate-limit usage, so ``observe`` is None.
GARMIN_BUDGET_POLICY = BudgetPolicy(windows=(WINDOW_1M,), ceilings=CEILINGS)

DEFAULT_PAUSE = timedelta(seconds=60)  # after a 429 without Retry-After


def rate_limited_until(now: datetime, retry_after: int | None) -> datetime:
    """When Garmin calls may resume after a 429 at ``now``: ``retry_after`` seconds later
    (the response's ``Retry-After``), or ``DEFAULT_PAUSE`` later without one.
    """
    if retry_after is None:
        return now + DEFAULT_PAUSE
    return now + timedelta(seconds=retry_after)
