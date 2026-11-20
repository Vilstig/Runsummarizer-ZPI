from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.enums import ImportPriority, WindowKind
from app.domain.models import BudgetPolicy, BudgetWindow

MINUTE = BudgetWindow("1m", timedelta(minutes=1), WindowKind.ROLLING, timedelta(seconds=5), 50)
HOUR = BudgetWindow("1h", timedelta(hours=1), WindowKind.FIXED, timedelta(hours=1), 600)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    ("window", "at", "expected"),
    [
        (MINUTE, utc(2026, 10, 6, 10, 7, 12, 500), utc(2026, 10, 6, 10, 7, 10)),
        (MINUTE, utc(2026, 10, 6, 10, 7, 15), utc(2026, 10, 6, 10, 7, 15)),
        (HOUR, utc(2026, 10, 6, 10, 59, 59), utc(2026, 10, 6, 10)),
        (
            HOUR,
            datetime(2026, 10, 6, 12, 30, tzinfo=timezone(timedelta(hours=2))),
            utc(2026, 10, 6, 10),
        ),
    ],
    ids=["inside-a-bucket", "on-a-boundary", "end-of-an-hour", "not-utc"],
)
def test_buckets_are_aligned_to_the_unix_epoch_in_utc(window, at, expected):
    start = window.bucket_start(at)

    assert start == expected
    assert start.utcoffset() == timedelta(0)


def test_a_fixed_window_is_a_single_bucket():
    with pytest.raises(ValueError, match="bucket must equal length"):
        BudgetWindow("1h", timedelta(hours=1), WindowKind.FIXED, timedelta(minutes=1), 600)


def test_a_window_without_a_ceiling_may_be_filled_to_its_limit():
    policy = BudgetPolicy(windows=(MINUTE, HOUR), ceilings={ImportPriority.SYNC: {"1m": 80}})

    assert policy.ceiling(ImportPriority.SYNC, MINUTE) == 80
    assert policy.ceiling(ImportPriority.SYNC, HOUR) == 100
    assert policy.ceiling(ImportPriority.WEBHOOK, MINUTE) == 100


def test_the_longest_reach_covers_every_bucket_a_window_still_counts():
    policy = BudgetPolicy(windows=(MINUTE, HOUR), ceilings={})

    assert policy.longest_reach == timedelta(hours=2)
