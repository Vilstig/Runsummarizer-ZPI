"""Garmin's budget policy and rate_limited_until."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import ImportPriority, WindowKind
from app.providers.garmin.budget import GARMIN_BUDGET_POLICY, WINDOW_1M, rate_limited_until

NOW = datetime(2026, 11, 15, 12, 0, 7, tzinfo=UTC)


def test_downloads_are_budgeted_over_a_rolling_minute():
    assert GARMIN_BUDGET_POLICY.windows == (WINDOW_1M,)
    assert WINDOW_1M.name == "1m"
    assert WINDOW_1M.kind is WindowKind.ROLLING
    assert WINDOW_1M.length == timedelta(minutes=1)
    assert WINDOW_1M.bucket == timedelta(seconds=10)
    assert WINDOW_1M.default_limit == 50


@pytest.mark.parametrize("priority", list(ImportPriority))
def test_each_priority_may_fill_80_percent(priority):
    assert GARMIN_BUDGET_POLICY.ceiling(priority, WINDOW_1M) == 80


def test_garmin_reports_no_usage():
    assert GARMIN_BUDGET_POLICY.observe is None


def test_a_429_pauses_for_retry_after():
    assert rate_limited_until(NOW, 120) == NOW + timedelta(seconds=120)
    assert rate_limited_until(NOW, 0) == NOW


def test_a_429_without_retry_after_pauses_for_a_minute():
    assert rate_limited_until(NOW, None) == NOW + timedelta(seconds=60)
