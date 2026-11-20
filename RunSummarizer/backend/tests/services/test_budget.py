"""The generic budget service: recording the usage a provider's responses report, and
pausing its calls.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.domain.enums import Provider, WindowKind
from app.domain.models import BudgetPolicy, BudgetWindow, RateLimitUsage, WindowUsage
from app.services import budget

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 8, 12, 7, tzinfo=UTC)
SENT_AT = NOW - timedelta(seconds=1)
UNTIL = datetime(2026, 10, 8, 12, 15, tzinfo=UTC)
WINDOW = BudgetWindow("1m", timedelta(minutes=1), WindowKind.ROLLING, timedelta(seconds=1), 50)
REPORTED = RateLimitUsage({"1m": WindowUsage(used=7, limit=60)})


def observe(response: httpx.Response) -> RateLimitUsage | None:
    """The usage of a response with a ``X-Used`` header."""
    return REPORTED if "X-Used" in response.headers else None


POLICY = BudgetPolicy(windows=(WINDOW,), ceilings={}, observe=observe)


async def test_the_usage_a_response_reports_is_recorded_in_the_providers_budget(db):
    on_response = budget.usage_recorder(
        Provider.GARMIN, POLICY, transaction=db.transaction, clock=lambda: NOW
    )

    await on_response(httpx.Response(200, headers={"X-Used": "7"}), SENT_AT)

    assert db.budget("garmin").usage_reports == [REPORTED]
    assert db.budget("strava").usage_reports == []


async def test_a_response_without_usage_records_nothing(db):
    on_response = budget.usage_recorder(Provider.STRAVA, POLICY, transaction=db.transaction)
    blocks = db.blocks_opened

    await on_response(httpx.Response(200), SENT_AT)

    assert db.budget("strava").usage_reports == []
    assert db.blocks_opened == blocks


async def test_a_policy_that_observes_nothing_records_nothing(db):
    policy = BudgetPolicy(windows=(WINDOW,), ceilings={})
    on_response = budget.usage_recorder(Provider.STRAVA, policy, transaction=db.transaction)

    await on_response(httpx.Response(200, headers={"X-Used": "7"}), SENT_AT)

    assert db.budget("strava").usage_reports == []


async def test_pausing_a_providers_calls_is_committed(db):
    await budget.pause_provider_calls(Provider.STRAVA, UNTIL, transaction=db.transaction)

    assert db.budget("strava").paused_until == UNTIL
    assert db.budget("garmin").paused_until is None


async def test_pausing_a_providers_calls_logs_a_warning(db, caplog):
    caplog.set_level("WARNING", logger="app.services.budget")

    await budget.pause_provider_calls(Provider.STRAVA, UNTIL, transaction=db.transaction)

    assert "strava" in caplog.text
    assert str(UNTIL) in caplog.text or UNTIL.isoformat() in caplog.text


async def test_a_shorter_pause_keeps_the_longer_one(db):
    await budget.pause_provider_calls(Provider.STRAVA, UNTIL, transaction=db.transaction)
    await budget.pause_provider_calls(Provider.STRAVA, NOW, transaction=db.transaction)

    assert db.budget("strava").paused_until == UNTIL
