"""Contract tests for ``AsyncProviderBudgetRepository``.

Each test starts from a provider whose budget holds nothing: no usage, its policy's
default limits, and no pause. Usage is set up through ``record_usage``, ``reserve`` and
``pause``, and checked through ``get_usage``, ``paused_until`` and ``resumes_at``,
never by reading the tables.

Most tests use Strava's windows, 100 calls per 15 minutes and 1,000 per day by default,
with a ceiling of 85% and 70% for sync items and 95% for webhook items. The rolling-window
tests use a provider allowing 50 calls in any minute, counted in 1-second buckets.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.db.models import ProviderBudget
from app.domain.enums import ImportPriority, Provider, WindowKind
from app.domain.models import BudgetPolicy, BudgetWindow, RateLimitUsage, WindowUsage
from app.providers.strava.budget import STRAVA_BUDGET_POLICY

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def empty_budgets(db_session):
    """No committed budget, e.g. the Strava budget the migration copied, in the test's
    transaction; it is rolled back afterwards."""
    await db_session.execute(delete(ProviderBudget))


STRAVA = Provider.STRAVA
OTHER = Provider.GARMIN

NOW = datetime(2026, 10, 6, 10, 7, tzinfo=UTC)  # in the 10:00-10:15 window
NEXT_WINDOW = datetime(2026, 10, 6, 10, 15, tzinfo=UTC)
NEXT_MIDNIGHT = datetime(2026, 10, 7, tzinfo=UTC)

SYNC = ImportPriority.SYNC
WEBHOOK = ImportPriority.WEBHOOK
POLICY = replace(
    STRAVA_BUDGET_POLICY,
    ceilings={SYNC: {"15m": 85, "day": 70}, WEBHOOK: {"15m": 95, "day": 95}},
)


def usage(
    used_15m: int, used_day: int, *, limit_15m: int = 100, limit_day: int = 1000
) -> RateLimitUsage:
    return RateLimitUsage(
        {
            "15m": WindowUsage(used=used_15m, limit=limit_15m),
            "day": WindowUsage(used=used_day, limit=limit_day),
        }
    )


# ---------- get_usage ----------


async def test_an_empty_budget_has_no_usage_and_the_default_limits(budget):
    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(0, 0)


async def test_usage_from_an_earlier_window_counts_as_zero(budget):
    await budget.record_usage(
        STRAVA, usage(80, 600), policy=POLICY, now=NOW - timedelta(minutes=15)
    )

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(0, 600)


async def test_usage_from_an_earlier_day_counts_as_zero(budget):
    await budget.record_usage(STRAVA, usage(80, 600), policy=POLICY, now=NOW - timedelta(days=1))

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(0, 0)


# ---------- record_usage ----------


async def test_record_usage_raises_the_counters(budget):
    await budget.record_usage(STRAVA, usage(37, 512), policy=POLICY, now=NOW)

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(37, 512)


async def test_record_usage_never_lowers_the_counters(budget):
    await budget.record_usage(STRAVA, usage(50, 500), policy=POLICY, now=NOW)
    await budget.record_usage(STRAVA, usage(37, 600), policy=POLICY, now=NOW)

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(50, 600)


async def test_record_usage_stores_the_limits(budget):
    await budget.record_usage(
        STRAVA, usage(10, 10, limit_15m=200, limit_day=2000), policy=POLICY, now=NOW
    )

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(
        10, 10, limit_15m=200, limit_day=2000
    )


async def test_record_usage_in_a_new_window_replaces_the_old_counter(budget):
    await budget.record_usage(
        STRAVA, usage(80, 600), policy=POLICY, now=NOW - timedelta(minutes=15)
    )
    await budget.record_usage(STRAVA, usage(3, 603), policy=POLICY, now=NOW)

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(3, 603)


async def test_record_usage_of_a_request_sent_in_an_earlier_window_leaves_the_15_minute_counter(
    budget,
):
    await budget.record_usage(
        STRAVA,
        usage(90, 600),
        policy=POLICY,
        sent_at=NEXT_WINDOW - timedelta(seconds=1),
        now=NEXT_WINDOW,
    )

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NEXT_WINDOW) == usage(0, 600)


async def test_record_usage_of_a_request_sent_on_an_earlier_day_leaves_both_counters(budget):
    sent_at = NEXT_MIDNIGHT - timedelta(seconds=1)
    await budget.record_usage(
        STRAVA, usage(5, 900), policy=POLICY, sent_at=sent_at, now=NEXT_MIDNIGHT
    )

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NEXT_MIDNIGHT) == usage(0, 0)


async def test_record_usage_of_a_request_sent_in_the_current_window_raises_the_counters(budget):
    await budget.record_usage(
        STRAVA, usage(37, 512), policy=POLICY, sent_at=NOW - timedelta(seconds=2), now=NOW
    )

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(37, 512)


# ---------- reserve ----------


async def test_reserve_counts_the_calls(budget):
    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is True

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(2, 2)


async def test_reserve_adds_to_the_counters(budget):
    await budget.record_usage(STRAVA, usage(10, 300), policy=POLICY, now=NOW)

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is True

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(12, 302)


async def test_reserve_starts_a_new_window_from_zero(budget):
    await budget.record_usage(
        STRAVA, usage(84, 600), policy=POLICY, now=NOW - timedelta(minutes=15)
    )

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is True

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(2, 602)


async def test_reserve_starts_a_new_day_from_zero(budget):
    await budget.record_usage(STRAVA, usage(84, 699), policy=POLICY, now=NOW - timedelta(days=1))

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is True

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(2, 2)


async def test_reserve_may_fill_the_15_minute_ceiling_exactly(budget):
    await budget.record_usage(STRAVA, usage(83, 83), policy=POLICY, now=NOW)

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is True

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(85, 85)


async def test_reserve_refuses_past_the_15_minute_ceiling_and_counts_nothing(budget):
    await budget.record_usage(STRAVA, usage(84, 84), policy=POLICY, now=NOW)

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is False

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(84, 84)


async def test_reserve_refuses_past_the_daily_ceiling(budget):
    await budget.record_usage(STRAVA, usage(10, 699), policy=POLICY, now=NOW)

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is False

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(10, 699)


async def test_a_higher_ceiling_allows_more(budget):
    await budget.record_usage(STRAVA, usage(84, 84), policy=POLICY, now=NOW)

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=WEBHOOK, now=NOW) is True


async def test_reserve_refuses_while_paused(budget):
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is False

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(0, 0)


async def test_reserve_succeeds_once_the_pause_ends(budget):
    await budget.pause(STRAVA, NOW)

    assert await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is True


async def test_a_zero_cost_reservation_always_succeeds(budget):
    await budget.record_usage(STRAVA, usage(99, 999), policy=POLICY, now=NOW)
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))

    assert await budget.reserve(STRAVA, 0, policy=POLICY, priority=SYNC, now=NOW) is True

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(99, 999)


# ---------- pause ----------


async def test_a_shorter_pause_keeps_the_longer_one(budget):
    await budget.pause(STRAVA, NOW + timedelta(hours=1))
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))

    assert await budget.resumes_at(
        STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW
    ) == NOW + timedelta(hours=1)


async def test_a_longer_pause_replaces_a_shorter_one(budget):
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))
    await budget.pause(STRAVA, NOW + timedelta(hours=1))

    assert await budget.resumes_at(
        STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW
    ) == NOW + timedelta(hours=1)


# ---------- paused_until ----------


async def test_an_empty_budget_is_not_paused(budget):
    assert await budget.paused_until(STRAVA, now=NOW) is None


async def test_paused_until_is_the_end_of_the_pause(budget):
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))

    assert await budget.paused_until(STRAVA, now=NOW) == NOW + timedelta(minutes=5)


async def test_a_pause_that_has_ended_is_no_pause(budget):
    await budget.pause(STRAVA, NOW)

    assert await budget.paused_until(STRAVA, now=NOW) is None


# ---------- resumes_at ----------


async def test_resumes_at_is_none_when_a_reservation_fits(budget):
    await budget.record_usage(STRAVA, usage(83, 83), policy=POLICY, now=NOW)

    assert await budget.resumes_at(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is None


async def test_resumes_at_the_next_window_past_the_15_minute_ceiling(budget):
    await budget.record_usage(STRAVA, usage(84, 84), policy=POLICY, now=NOW)

    assert await budget.resumes_at(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) == NEXT_WINDOW


async def test_resumes_at_the_next_utc_midnight_past_the_daily_ceiling(budget):
    await budget.record_usage(STRAVA, usage(10, 699), policy=POLICY, now=NOW)

    assert (
        await budget.resumes_at(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) == NEXT_MIDNIGHT
    )


async def test_resumes_when_the_pause_ends(budget):
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))

    assert await budget.resumes_at(
        STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW
    ) == NOW + timedelta(minutes=5)


async def test_resumes_at_the_later_of_the_pause_and_the_counters(budget):
    await budget.record_usage(STRAVA, usage(10, 699), policy=POLICY, now=NOW)
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))

    assert (
        await budget.resumes_at(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) == NEXT_MIDNIGHT
    )


async def test_a_pause_that_has_ended_does_not_hold_back(budget):
    await budget.pause(STRAVA, NOW)

    assert await budget.resumes_at(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is None


async def test_usage_from_an_earlier_window_does_not_hold_back(budget):
    await budget.record_usage(
        STRAVA, usage(99, 600), policy=POLICY, now=NOW - timedelta(minutes=15)
    )

    assert await budget.resumes_at(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW) is None


async def test_a_zero_cost_reservation_never_waits(budget):
    await budget.record_usage(STRAVA, usage(99, 999), policy=POLICY, now=NOW)
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))

    assert await budget.resumes_at(STRAVA, 0, policy=POLICY, priority=SYNC, now=NOW) is None


# ---------- providers ----------


async def test_each_provider_has_a_budget_of_its_own(budget):
    await budget.record_usage(STRAVA, usage(84, 84), policy=POLICY, now=NOW)
    await budget.pause(STRAVA, NOW + timedelta(minutes=5))

    assert await budget.reserve(OTHER, 2, policy=POLICY, priority=SYNC, now=NOW) is True
    assert await budget.get_usage(OTHER, policy=POLICY, now=NOW) == usage(2, 2)
    assert await budget.paused_until(OTHER, now=NOW) is None
    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(84, 84)


async def test_a_pause_holds_back_only_its_provider(budget):
    await budget.pause(OTHER, NOW + timedelta(minutes=5))

    assert await budget.paused_until(OTHER, now=NOW) == NOW + timedelta(minutes=5)
    assert await budget.paused_until(STRAVA, now=NOW) is None


async def test_the_default_limits_hold_until_a_response_reports_the_limits(budget):
    assert await budget.reserve(STRAVA, 85, policy=POLICY, priority=SYNC, now=NOW) is True
    assert await budget.reserve(STRAVA, 1, policy=POLICY, priority=SYNC, now=NOW) is False

    await budget.record_usage(STRAVA, usage(85, 85, limit_15m=200), policy=POLICY, now=NOW)

    assert await budget.reserve(STRAVA, 1, policy=POLICY, priority=SYNC, now=NOW) is True


async def test_record_usage_ignores_windows_the_policy_does_not_have(budget):
    reported = RateLimitUsage(
        {"15m": WindowUsage(used=5, limit=100), "hour": WindowUsage(used=99, limit=99)}
    )

    await budget.record_usage(STRAVA, reported, policy=POLICY, now=NOW)

    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(5, 0)


async def test_a_window_reported_alone_keeps_the_other_windows_limit(budget):
    await budget.record_usage(STRAVA, usage(1, 1, limit_day=2000), policy=POLICY, now=NOW)
    reported = RateLimitUsage({"15m": WindowUsage(used=1, limit=300)})

    await budget.record_usage(STRAVA, reported, policy=POLICY, now=NOW)

    usage_now = await budget.get_usage(STRAVA, policy=POLICY, now=NOW)
    assert usage_now == usage(1, 1, limit_15m=300, limit_day=2000)


# ---------- a fixed 1-minute window ----------

PER_MINUTE = BudgetWindow(
    "1m", timedelta(minutes=1), WindowKind.FIXED, timedelta(minutes=1), default_limit=50
)
FIXED_MINUTE = BudgetPolicy(windows=(PER_MINUTE,), ceilings={})


def calls(used: int, limit: int = 50) -> RateLimitUsage:
    return RateLimitUsage({"1m": WindowUsage(used=used, limit=limit)})


async def test_a_fixed_window_takes_calls_up_to_its_limit(budget):
    assert await budget.reserve(OTHER, 50, policy=FIXED_MINUTE, priority=SYNC, now=NOW) is True
    assert await budget.reserve(OTHER, 1, policy=FIXED_MINUTE, priority=SYNC, now=NOW) is False


async def test_a_fixed_window_resets_at_the_next_calendar_minute(budget):
    await budget.reserve(
        OTHER, 50, policy=FIXED_MINUTE, priority=SYNC, now=NOW + timedelta(seconds=59)
    )
    next_minute = NOW + timedelta(minutes=1)

    assert (
        await budget.resumes_at(
            OTHER, 1, policy=FIXED_MINUTE, priority=SYNC, now=NOW + timedelta(seconds=59)
        )
        == next_minute
    )
    assert await budget.reserve(OTHER, 1, policy=FIXED_MINUTE, priority=SYNC, now=next_minute)
    assert await budget.get_usage(OTHER, policy=FIXED_MINUTE, now=next_minute) == calls(1)


# ---------- a rolling 1-minute window ----------

ANY_MINUTE = BudgetWindow(
    "1m", timedelta(minutes=1), WindowKind.ROLLING, timedelta(seconds=1), default_limit=50
)
ROLLING_MINUTE = BudgetPolicy(windows=(ANY_MINUTE,), ceilings={SYNC: {"1m": 80}})


async def reserve_rolling(budget, cost: int, at: datetime, priority=WEBHOOK) -> bool:
    return await budget.reserve(OTHER, cost, policy=ROLLING_MINUTE, priority=priority, now=at)


async def test_a_rolling_window_counts_the_calls_of_the_last_minute(budget):
    assert await reserve_rolling(budget, 20, NOW)
    assert await reserve_rolling(budget, 30, NOW + timedelta(seconds=30))

    assert not await reserve_rolling(budget, 1, NOW + timedelta(seconds=59))
    assert await budget.get_usage(
        OTHER, policy=ROLLING_MINUTE, now=NOW + timedelta(seconds=59)
    ) == calls(50)


async def test_a_bucket_leaving_the_rolling_window_frees_its_calls(budget):
    await reserve_rolling(budget, 20, NOW)
    await reserve_rolling(budget, 30, NOW + timedelta(seconds=30))
    left = NOW + timedelta(minutes=1, seconds=1)  # the bucket at NOW ends at NOW + 1 s

    assert await budget.get_usage(OTHER, policy=ROLLING_MINUTE, now=left) == calls(30)
    assert await reserve_rolling(budget, 20, left)
    assert not await reserve_rolling(budget, 1, left)


async def test_a_bucket_partly_in_the_rolling_window_counts_in_full(budget):
    await reserve_rolling(budget, 50, NOW)

    assert not await reserve_rolling(budget, 1, NOW + timedelta(minutes=1, milliseconds=500))


async def test_a_rolling_window_applies_the_ceiling_of_the_priority(budget):
    await reserve_rolling(budget, 40, NOW)

    assert not await reserve_rolling(budget, 1, NOW, priority=SYNC)
    assert await reserve_rolling(budget, 10, NOW, priority=WEBHOOK)


async def test_a_full_rolling_window_resumes_when_enough_buckets_have_left(budget):
    await reserve_rolling(budget, 20, NOW)
    await reserve_rolling(budget, 10, NOW + timedelta(seconds=10))
    await reserve_rolling(budget, 20, NOW + timedelta(seconds=30))
    later = NOW + timedelta(seconds=40)

    resumes = await budget.resumes_at(OTHER, 25, policy=ROLLING_MINUTE, priority=WEBHOOK, now=later)

    # 25 more fit once the buckets of NOW and NOW + 10 s have left: 20 used, 30 free
    assert resumes == NOW + timedelta(seconds=10) + timedelta(seconds=1) + timedelta(minutes=1)
    assert not await reserve_rolling(budget, 25, resumes - timedelta(seconds=1))
    assert await reserve_rolling(budget, 25, resumes)


async def test_a_rolling_window_with_room_does_not_hold_back(budget):
    await reserve_rolling(budget, 49, NOW)

    assert (
        await budget.resumes_at(OTHER, 1, policy=ROLLING_MINUTE, priority=WEBHOOK, now=NOW) is None
    )


async def test_reported_usage_of_a_rolling_window_stores_only_its_limit(budget):
    await budget.record_usage(OTHER, calls(45, limit=60), policy=ROLLING_MINUTE, now=NOW)

    assert await budget.get_usage(OTHER, policy=ROLLING_MINUTE, now=NOW) == calls(0, limit=60)
    assert await reserve_rolling(budget, 60, NOW)


# ---------- delete_old_buckets ----------


async def test_buckets_no_window_counts_any_more_are_deleted(budget):
    await budget.reserve(STRAVA, 2, policy=POLICY, priority=SYNC, now=NOW - timedelta(days=3))
    await budget.reserve(STRAVA, 3, policy=POLICY, priority=SYNC, now=NOW - timedelta(hours=1))
    await budget.reserve(STRAVA, 4, policy=POLICY, priority=SYNC, now=NOW)

    # the 15m and day buckets of three days ago, of all buckets reserved
    assert await budget.delete_old_buckets(STRAVA, policy=POLICY, now=NOW) == 2
    assert await budget.get_usage(STRAVA, policy=POLICY, now=NOW) == usage(4, 7)


async def test_deleting_old_buckets_leaves_other_providers_alone(budget):
    await budget.reserve(OTHER, 2, policy=POLICY, priority=SYNC, now=NOW - timedelta(days=3))

    assert await budget.delete_old_buckets(STRAVA, policy=POLICY, now=NOW) == 0
    assert await budget.delete_old_buckets(OTHER, policy=POLICY, now=NOW) == 2
