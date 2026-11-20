"""Contract tests for ``AsyncImportQueueRepository``.

Each test starts from an empty queue. Items are added through ``enqueue_sync`` and
``enqueue_webhook``, moved through claims and their outcomes, and checked through what
the protocol returns: queued items, claims, counts, failures and run times, never by
reading the table.

Every test of ``enqueue_webhook`` has ``webhook`` in its name, and no other test calls it.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.protocols.import_queue import Claim, FinishOutcome, ImportFailure, QueuedItem
from app.domain.enums import (
    ImportErrorCode,
    ImportPriority,
    ImportSource,
    ImportStatus,
)
from tests.db.builders import make_activity

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 6, 10, 7, tzinfo=UTC)
LATER = NOW + timedelta(hours=6)  # after every sync item's sort key in these tests

STRAVA = "strava"
GARMIN = "garmin"

SPACING = timedelta(seconds=20)
LEASE = timedelta(minutes=5)
EXPIRED = NOW + LEASE + timedelta(seconds=1)  # a lease taken at NOW has ended
MAX_ATTEMPTS = 5
PURGE_AGE = timedelta(days=30)

RAW = {"detail": {"id": 1, "type": "Run"}, "streams": {"heartrate": {"data": [140, 150]}}}
SENT = {"format": "fake_notification_v1", "url": "https://provider.example/file?token=t1"}


def counts(*, queued=0, running=0, dead=0, blocked=0) -> dict[ImportStatus, int]:
    return {
        ImportStatus.QUEUED: queued,
        ImportStatus.RUNNING: running,
        ImportStatus.DEAD: dead,
        ImportStatus.BLOCKED: blocked,
    }


async def enqueue(queue, user_id, *keys, now=NOW, provider=STRAVA) -> int:
    return await queue.enqueue_sync(user_id, provider, list(keys), spacing=SPACING, now=now)


async def claim_next(queue, *, now=NOW, provider=STRAVA) -> Claim | None:
    item = await queue.lock_next(provider, now=now)
    if item is None:
        return None
    return await queue.claim(item, lease=LEASE, now=now)


async def claim_order(queue, *, now, provider=STRAVA) -> list[str]:
    """Claim every item claimable at ``now``, and return their keys in claim order."""
    keys = []
    while (claim := await claim_next(queue, now=now, provider=provider)) is not None:
        keys.append(claim.activity_key)
    return keys


async def take_over(queue) -> Claim:
    """Expire the lease of the item claimed at NOW, and claim the item again."""
    await queue.expire_leases(STRAVA, max_attempts=MAX_ATTEMPTS, now=EXPIRED)
    return await claim_next(queue, now=EXPIRED)


async def make_dead(queue, user_id, key, *, now=NOW, provider=STRAVA) -> None:
    await enqueue(queue, user_id, key, now=now, provider=provider)
    claim = await claim_next(queue, now=now, provider=provider)
    assert claim.activity_key == key
    await queue.mark_dead(claim, error_code=ImportErrorCode.NOT_FOUND, last_error="404", now=now)


async def make_blocked(queue, user_id, key, *, now=NOW, provider=STRAVA) -> None:
    await enqueue(queue, user_id, key, now=now, provider=provider)
    claim = await claim_next(queue, now=now, provider=provider)
    assert claim.activity_key == key
    await queue.block(claim, last_error="401", now=now)


# ---------- enqueue_sync ----------


async def test_enqueue_sync_queues_one_item_per_key(queue, user_id):
    assert await enqueue(queue, user_id, "strava_1", "strava_2") == 2

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=2)


async def test_a_sync_item_is_queued_at_sync_priority_from_generation_0(queue, user_id):
    await enqueue(queue, user_id, "strava_1")

    assert await queue.lock_next(STRAVA, now=NOW) == QueuedItem(
        user_id=user_id,
        provider=STRAVA,
        activity_key="strava_1",
        source=ImportSource.SYNC,
        priority=ImportPriority.SYNC,
        generation=0,
        raw_payload=None,
    )


async def test_sync_items_are_claimed_in_the_order_given(queue, user_id):
    await enqueue(queue, user_id, "strava_3", "strava_1", "strava_2")

    assert await claim_order(queue, now=NOW) == ["strava_3", "strava_1", "strava_2"]


async def test_sync_items_are_not_claimable_before_now(queue, user_id):
    await enqueue(queue, user_id, "strava_1")

    assert await queue.lock_next(STRAVA, now=NOW - timedelta(seconds=1)) is None


async def test_enqueue_sync_skips_activities_already_stored(queue, save_activity, user_id):
    await save_activity("strava_1")

    assert await enqueue(queue, user_id, "strava_1", "strava_2") == 1

    assert await claim_order(queue, now=NOW) == ["strava_2"]


async def test_enqueue_sync_ignores_another_users_stored_activity(
    queue, activity_repo, user_id, other_user_id
):
    await activity_repo.save(make_activity("strava_1", user_id=other_user_id))

    assert await enqueue(queue, user_id, "strava_1") == 1


async def test_enqueue_sync_ignores_a_stored_activity_from_another_provider(
    queue, save_activity, user_id
):
    await save_activity("1", source=GARMIN)

    assert await enqueue(queue, user_id, "1") == 1


async def test_enqueue_sync_skips_items_already_queued(queue, user_id):
    await enqueue(queue, user_id, "strava_1")

    assert await enqueue(queue, user_id, "strava_1", "strava_2") == 1

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=2)


async def test_enqueue_sync_leaves_dead_items_dead(queue, user_id):
    await make_dead(queue, user_id, "strava_1")

    assert await enqueue(queue, user_id, "strava_1") == 0

    assert await queue.count_by_status(user_id, STRAVA) == counts(dead=1)


async def test_enqueue_sync_queues_a_repeated_key_once(queue, user_id):
    assert await enqueue(queue, user_id, "strava_1", "strava_1") == 1


async def test_enqueue_sync_without_keys_queues_nothing(queue, user_id):
    assert await enqueue(queue, user_id) == 0


async def test_a_key_is_queued_separately_per_user_and_provider(queue, user_id, other_user_id):
    await enqueue(queue, user_id, "1")

    assert await enqueue(queue, other_user_id, "1") == 1
    assert await enqueue(queue, user_id, "1", provider=GARMIN) == 1


async def test_a_backfill_is_spread_out_so_a_later_sync_lands_near_the_front(
    queue, user_id, other_user_id
):
    # NOW + 20 s, 40 s, 60 s and 80 s
    await enqueue(queue, user_id, "strava_11", "strava_12", "strava_13", "strava_14")
    # NOW + 50 s
    await enqueue(queue, other_user_id, "strava_21", now=NOW + timedelta(seconds=30))

    assert await claim_order(queue, now=LATER) == [
        "strava_11",
        "strava_12",
        "strava_21",
        "strava_13",
        "strava_14",
    ]


async def test_a_users_next_sync_follows_their_last_queued_item(queue, user_id, other_user_id):
    await enqueue(queue, user_id, "strava_11", "strava_12")  # NOW + 20 s, 40 s
    await enqueue(queue, other_user_id, "strava_21", now=NOW + timedelta(seconds=5))  # + 25 s
    await enqueue(queue, user_id, "strava_13", now=NOW + timedelta(seconds=10))  # + 60 s

    assert await claim_order(queue, now=LATER) == [
        "strava_11",
        "strava_21",
        "strava_12",
        "strava_13",
    ]


async def test_a_users_next_sync_starts_from_now_when_their_last_item_is_earlier(
    queue, user_id, other_user_id
):
    await enqueue(queue, user_id, "strava_11")
    await enqueue(queue, other_user_id, "strava_21", now=NOW + timedelta(minutes=30))
    await enqueue(queue, user_id, "strava_12", now=NOW + timedelta(hours=1))

    assert await claim_order(queue, now=LATER) == ["strava_11", "strava_21", "strava_12"]


async def test_a_users_running_items_do_not_hold_back_their_next_sync(
    queue, user_id, other_user_id
):
    await enqueue(queue, user_id, "strava_11")  # NOW + 20 s
    await claim_next(queue)
    await enqueue(queue, user_id, "strava_12", now=NOW + timedelta(seconds=5))  # + 25 s
    await enqueue(queue, other_user_id, "strava_21", now=NOW + timedelta(seconds=10))  # + 30 s

    assert await claim_order(queue, now=LATER) == ["strava_12", "strava_21"]


# ---------- lock_next and claim ----------


async def test_lock_next_returns_none_when_nothing_is_queued(queue):
    assert await queue.lock_next(STRAVA, now=NOW) is None


async def test_lock_next_only_returns_the_providers_items(queue, user_id):
    await enqueue(queue, user_id, "garmin_1", provider=GARMIN)

    assert await queue.lock_next(STRAVA, now=NOW) is None
    assert (await queue.lock_next(GARMIN, now=NOW)).activity_key == "garmin_1"


async def requeue(queue, claim: Claim, *, raw_payload: dict | None = None) -> None:
    """Queue the claimed item again, claimable from NOW, saving ``raw_payload`` if given."""
    await queue.retry_later(
        claim,
        run_after=NOW,
        error_code=ImportErrorCode.PROCESSING_FAILED,
        last_error="ValueError",
        raw_payload=raw_payload,
        now=NOW,
    )


async def payload_claim_order(queue) -> list[str]:
    """Claim every item with a saved payload claimable at NOW, and return their keys in
    claim order."""
    keys = []
    while (item := await queue.lock_next(STRAVA, now=NOW, saved_payload_only=True)) is not None:
        keys.append((await queue.claim(item, lease=LEASE, now=NOW)).activity_key)
    return keys


async def test_lock_next_saved_payload_only_skips_items_without_one(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    first, second = await claim_next(queue), await claim_next(queue)
    await requeue(queue, first)
    await requeue(queue, second, raw_payload=RAW)

    item = await queue.lock_next(STRAVA, now=NOW, saved_payload_only=True)

    assert (item.activity_key, item.raw_payload) == ("strava_2", RAW)


async def test_lock_next_saved_payload_only_takes_webhook_items_first_then_queue_order(
    queue, user_id
):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    await queue.enqueue_webhook(user_id, STRAVA, "strava_3", now=NOW)
    claims = [await claim_next(queue) for _ in range(3)]
    for claim in claims:
        await requeue(queue, claim, raw_payload=RAW)
    await queue.enqueue_webhook(user_id, STRAVA, "strava_4", now=NOW)

    assert await payload_claim_order(queue) == ["strava_3", "strava_1", "strava_2"]


async def test_lock_next_saved_payload_only_returns_none_without_one(queue, user_id):
    await enqueue(queue, user_id, "strava_1")

    assert await queue.lock_next(STRAVA, now=NOW, saved_payload_only=True) is None


async def test_lock_next_saved_payload_only_skips_a_payload_a_webhook_cleared(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    await requeue(queue, await claim_next(queue), raw_payload=RAW)
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW)

    assert await queue.lock_next(STRAVA, now=NOW, saved_payload_only=True) is None
    assert (await queue.lock_next(STRAVA, now=NOW)).activity_key == "strava_1"


async def test_claim_marks_the_item_running_and_uses_an_attempt(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    item = await queue.lock_next(STRAVA, now=NOW)

    claim = await queue.claim(item, lease=LEASE, now=NOW)

    assert (claim.user_id, claim.provider, claim.activity_key) == (user_id, STRAVA, "strava_1")
    assert (claim.generation, claim.attempts) == (0, 1)
    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1)


async def test_a_running_item_is_not_claimed_again(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    await claim_next(queue)

    assert await queue.lock_next(STRAVA, now=NOW + timedelta(minutes=1)) is None


async def test_every_claim_gets_a_new_lease_token(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    first = await claim_next(queue)
    await queue.release(first, run_after=NOW, now=NOW)

    second = await claim_next(queue)

    assert second.lease_token != first.lease_token


# ---------- finish ----------


async def test_finish_deletes_the_item(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)

    assert await queue.finish(claim, now=NOW) == FinishOutcome.DONE

    assert await queue.count_by_status(user_id, STRAVA) == counts()


async def test_finish_after_the_lease_was_lost_changes_nothing(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    stale = await claim_next(queue)
    current = await take_over(queue)

    assert await queue.finish(stale, now=EXPIRED) == FinishOutcome.LOST

    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1)
    assert await queue.finish(current, now=EXPIRED) == FinishOutcome.DONE


async def test_finish_after_the_item_was_deleted_is_lost(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.delete(user_id, STRAVA, "strava_1")

    assert await queue.finish(claim, now=NOW) == FinishOutcome.LOST


# ---------- save_payload ----------


async def test_save_payload_saves_the_payload_on_the_running_item(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)

    assert await queue.save_payload(claim, RAW, now=NOW) is True

    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1)
    await queue.expire_leases(STRAVA, max_attempts=MAX_ATTEMPTS, now=EXPIRED)
    assert (await queue.lock_next(STRAVA, now=EXPIRED, saved_payload_only=True)).raw_payload == RAW


async def test_save_payload_after_the_lease_was_lost_changes_nothing(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    stale = await claim_next(queue)
    current = await take_over(queue)

    assert await queue.save_payload(stale, RAW, now=EXPIRED) is False

    await queue.release(current, run_after=EXPIRED, now=EXPIRED)
    assert (await queue.lock_next(STRAVA, now=EXPIRED)).raw_payload is None


async def test_save_payload_after_the_item_was_deleted_changes_nothing(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.delete(user_id, STRAVA, "strava_1")

    assert await queue.save_payload(claim, RAW, now=NOW) is False

    assert await queue.count_by_status(user_id, STRAVA) == counts()


# ---------- retry_later ----------


async def test_retry_later_queues_the_item_again_from_run_after(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    retry_at = NOW + timedelta(minutes=1)

    assert (
        await queue.retry_later(
            claim,
            run_after=retry_at,
            error_code=ImportErrorCode.UNAVAILABLE,
            last_error="503",
            now=NOW,
        )
        is True
    )

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    assert await queue.lock_next(STRAVA, now=retry_at - timedelta(seconds=1)) is None
    assert (await claim_next(queue, now=retry_at)).attempts == 2


async def test_retry_later_saves_the_raw_payload(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)

    await queue.retry_later(
        claim,
        run_after=NOW,
        error_code=ImportErrorCode.PROCESSING_FAILED,
        last_error="ValueError",
        raw_payload=RAW,
        now=NOW,
    )

    assert (await queue.lock_next(STRAVA, now=NOW)).raw_payload == RAW


async def test_retry_later_without_a_payload_keeps_the_saved_one(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    first = await claim_next(queue)
    await queue.retry_later(
        first,
        run_after=NOW,
        error_code=ImportErrorCode.PROCESSING_FAILED,
        last_error="ValueError",
        raw_payload=RAW,
        now=NOW,
    )
    second = await claim_next(queue)

    await queue.retry_later(
        second,
        run_after=NOW,
        error_code=ImportErrorCode.UNAVAILABLE,
        last_error="503",
        now=NOW,
    )

    assert (await queue.lock_next(STRAVA, now=NOW)).raw_payload == RAW


async def test_retry_later_after_the_lease_was_lost_changes_nothing(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    stale = await claim_next(queue)
    current = await take_over(queue)

    assert (
        await queue.retry_later(
            stale,
            run_after=EXPIRED,
            error_code=ImportErrorCode.PROCESSING_FAILED,
            last_error="ValueError",
            raw_payload=RAW,
            now=EXPIRED,
        )
        is False
    )

    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1)
    await queue.release(current, run_after=EXPIRED, now=EXPIRED)
    assert (await queue.lock_next(STRAVA, now=EXPIRED)).raw_payload is None


# ---------- mark_dead ----------


async def test_mark_dead_lists_the_item_as_a_failure(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    failed_at = NOW + timedelta(minutes=1)

    assert (
        await queue.mark_dead(
            claim, error_code=ImportErrorCode.NOT_FOUND, last_error="404", now=failed_at
        )
        is True
    )

    assert await queue.count_by_status(user_id, STRAVA) == counts(dead=1)
    assert await queue.recent_failures(user_id, STRAVA) == [
        ImportFailure(
            activity_key="strava_1",
            error_code=ImportErrorCode.NOT_FOUND,
            attempts=1,
            failed_at=failed_at,
        )
    ]


async def test_a_dead_item_is_not_claimable(queue, user_id):
    await make_dead(queue, user_id, "strava_1")

    assert await queue.lock_next(STRAVA, now=LATER) is None


async def test_mark_dead_saves_the_raw_payload_for_a_retry(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.mark_dead(
        claim,
        error_code=ImportErrorCode.PROCESSING_FAILED,
        last_error="ValueError",
        raw_payload=RAW,
        now=NOW,
    )

    await queue.retry_failures(user_id, STRAVA, now=LATER)

    assert (await queue.lock_next(STRAVA, now=LATER)).raw_payload == RAW


async def test_mark_dead_after_the_lease_was_lost_changes_nothing(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    stale = await claim_next(queue)
    await take_over(queue)

    assert (
        await queue.mark_dead(
            stale, error_code=ImportErrorCode.NOT_FOUND, last_error="404", now=EXPIRED
        )
        is False
    )

    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1)
    assert await queue.recent_failures(user_id, STRAVA) == []


# ---------- release ----------


async def test_release_queues_the_item_from_run_after_without_using_an_attempt(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    resume = NOW + timedelta(minutes=8)

    assert await queue.release(claim, run_after=resume, now=NOW) is True

    assert await queue.lock_next(STRAVA, now=resume - timedelta(seconds=1)) is None
    assert (await claim_next(queue, now=resume)).attempts == 1


async def test_release_after_the_lease_was_lost_changes_nothing(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    stale = await claim_next(queue)
    current = await take_over(queue)

    assert await queue.release(stale, run_after=EXPIRED, now=EXPIRED) is False

    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1)
    assert await queue.finish(current, now=EXPIRED) == FinishOutcome.DONE


# ---------- block ----------


async def test_block_blocks_the_claimed_item_and_the_users_queued_items(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2", "strava_3")
    claim = await claim_next(queue)

    assert await queue.block(claim, last_error="401", now=NOW) == 3

    assert await queue.count_by_status(user_id, STRAVA) == counts(blocked=3)
    assert await queue.lock_next(STRAVA, now=LATER) is None


async def test_block_includes_items_waiting_for_a_retry(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    first = await claim_next(queue)
    await queue.retry_later(
        first,
        run_after=NOW + timedelta(hours=1),
        error_code=ImportErrorCode.UNAVAILABLE,
        last_error="503",
        now=NOW,
    )
    second = await claim_next(queue)

    assert await queue.block(second, last_error="401", now=NOW) == 2


async def test_block_leaves_other_users_and_providers_alone(queue, user_id, other_user_id):
    await enqueue(queue, user_id, "strava_1")
    await enqueue(queue, other_user_id, "strava_2")
    await enqueue(queue, user_id, "garmin_1", provider=GARMIN)
    claim = await claim_next(queue)

    assert await queue.block(claim, last_error="401", now=NOW) == 1

    assert await queue.count_by_status(other_user_id, STRAVA) == counts(queued=1)
    assert await queue.count_by_status(user_id, GARMIN) == counts(queued=1)


async def test_block_leaves_dead_items_dead(queue, user_id):
    await make_dead(queue, user_id, "strava_1")

    await make_blocked(queue, user_id, "strava_2")

    assert await queue.count_by_status(user_id, STRAVA) == counts(dead=1, blocked=1)


async def test_block_after_the_lease_was_lost_blocks_only_the_queued_items(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    stale = await claim_next(queue)
    await take_over(queue)

    assert await queue.block(stale, last_error="401", now=EXPIRED) == 1

    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1, blocked=1)


# ---------- unblock ----------


async def test_unblock_queues_blocked_items_with_their_attempts_reset(queue, user_id):
    await make_blocked(queue, user_id, "strava_1")

    assert await queue.unblock(user_id, STRAVA, now=LATER) == 1

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    assert (await claim_next(queue, now=LATER)).attempts == 1


async def test_unblocked_items_are_claimable_at_once_even_after_a_retry_wait(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    first = await claim_next(queue)
    await queue.retry_later(
        first,
        run_after=NOW + timedelta(hours=1),
        error_code=ImportErrorCode.UNAVAILABLE,
        last_error="503",
        now=NOW,
    )
    second = await claim_next(queue)
    await queue.block(second, last_error="401", now=NOW)
    reconnected = NOW + timedelta(minutes=1)

    await queue.unblock(user_id, STRAVA, now=reconnected)

    assert await claim_order(queue, now=reconnected) == ["strava_1", "strava_2"]


async def test_unblock_leaves_dead_items_and_other_users_alone(queue, user_id, other_user_id):
    await make_dead(queue, user_id, "strava_1")
    await make_blocked(queue, other_user_id, "strava_2")

    assert await queue.unblock(user_id, STRAVA, now=LATER) == 0

    assert await queue.count_by_status(user_id, STRAVA) == counts(dead=1)
    assert await queue.count_by_status(other_user_id, STRAVA) == counts(blocked=1)


# ---------- expire_leases ----------


async def test_an_expired_lease_queues_the_item_again(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    await claim_next(queue)

    assert await queue.expire_leases(STRAVA, max_attempts=MAX_ATTEMPTS, now=EXPIRED) == 1

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    assert (await claim_next(queue, now=EXPIRED)).attempts == 2


async def test_a_lease_is_kept_until_it_ends(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    await claim_next(queue)

    assert await queue.expire_leases(STRAVA, max_attempts=MAX_ATTEMPTS, now=NOW + LEASE) == 0

    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1)


async def test_an_expired_lease_at_max_attempts_makes_the_item_dead(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    await claim_next(queue)
    await queue.expire_leases(STRAVA, max_attempts=2, now=EXPIRED)
    await claim_next(queue, now=EXPIRED)
    lost_at = EXPIRED + LEASE + timedelta(seconds=1)

    assert await queue.expire_leases(STRAVA, max_attempts=2, now=lost_at) == 1

    assert await queue.recent_failures(user_id, STRAVA) == [
        ImportFailure(
            activity_key="strava_1",
            error_code=ImportErrorCode.WORKER_LOST,
            attempts=2,
            failed_at=lost_at,
        )
    ]


async def test_expire_leases_only_touches_the_provider(queue, user_id):
    await enqueue(queue, user_id, "garmin_1", provider=GARMIN)
    await claim_next(queue, provider=GARMIN)

    assert await queue.expire_leases(STRAVA, max_attempts=MAX_ATTEMPTS, now=EXPIRED) == 0

    assert await queue.count_by_status(user_id, GARMIN) == counts(running=1)


# ---------- purge_failures ----------


async def test_purge_failures_deletes_old_dead_and_blocked_items(queue, user_id):
    await make_dead(queue, user_id, "strava_1")
    await make_blocked(queue, user_id, "strava_2")

    purged = await queue.purge_failures(
        STRAVA, max_age=PURGE_AGE, now=NOW + PURGE_AGE + timedelta(seconds=1)
    )

    assert purged == 2
    assert await queue.count_by_status(user_id, STRAVA) == counts()


async def test_purge_failures_keeps_failures_up_to_max_age(queue, user_id):
    await make_dead(queue, user_id, "strava_1")

    assert await queue.purge_failures(STRAVA, max_age=PURGE_AGE, now=NOW + PURGE_AGE) == 0

    assert await queue.count_by_status(user_id, STRAVA) == counts(dead=1)


async def test_purge_failures_keeps_queued_and_running_items(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    await claim_next(queue)

    assert await queue.purge_failures(STRAVA, max_age=PURGE_AGE, now=NOW + 2 * PURGE_AGE) == 0

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1, running=1)


async def test_purge_failures_only_touches_the_provider(queue, user_id):
    await make_dead(queue, user_id, "garmin_1", provider=GARMIN)

    assert await queue.purge_failures(STRAVA, max_age=PURGE_AGE, now=NOW + 2 * PURGE_AGE) == 0

    assert await queue.count_by_status(user_id, GARMIN) == counts(dead=1)


# ---------- count_by_status ----------


async def test_count_by_status_is_zero_for_every_status_without_items(queue, user_id):
    assert await queue.count_by_status(user_id, STRAVA) == counts()


async def test_count_by_status_counts_each_status(queue, user_id):
    await make_blocked(queue, user_id, "strava_1")
    await make_dead(queue, user_id, "strava_2")
    await enqueue(queue, user_id, "strava_3", "strava_4", "strava_5")
    await claim_next(queue)

    assert await queue.count_by_status(user_id, STRAVA) == counts(
        queued=2, running=1, dead=1, blocked=1
    )


async def test_count_by_status_is_scoped_to_the_user_and_provider(queue, user_id, other_user_id):
    await enqueue(queue, other_user_id, "strava_1")
    await enqueue(queue, user_id, "garmin_1", provider=GARMIN)

    assert await queue.count_by_status(user_id, STRAVA) == counts()


async def test_count_by_status_for_a_user_id_that_is_not_a_uuid_is_zero(queue, user_id):
    await enqueue(queue, user_id, "strava_1")

    assert await queue.count_by_status("not-a-uuid", STRAVA) == counts()


# ---------- count_by_status_per_provider ----------


async def test_count_by_status_per_provider_counts_each_providers_items(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    await make_dead(queue, user_id, "garmin_1", provider=GARMIN)

    assert await queue.count_by_status_per_provider(user_id) == {
        STRAVA: counts(queued=2),
        GARMIN: counts(dead=1),
    }


async def test_count_by_status_per_provider_agrees_with_count_by_status(queue, user_id):
    await make_dead(queue, user_id, "strava_1")
    await enqueue(queue, user_id, "strava_2", "strava_3")
    await claim_next(queue)

    per_provider = await queue.count_by_status_per_provider(user_id)

    assert per_provider[STRAVA] == counts(queued=1, running=1, dead=1)
    assert per_provider[STRAVA] == await queue.count_by_status(user_id, STRAVA)


async def test_count_by_status_per_provider_leaves_out_other_users_and_empty_providers(
    queue, user_id, other_user_id
):
    await enqueue(queue, other_user_id, "strava_1")
    await enqueue(queue, user_id, "garmin_1", provider=GARMIN)

    assert await queue.count_by_status_per_provider(user_id) == {GARMIN: counts(queued=1)}


async def test_count_by_status_per_provider_without_items_is_empty(queue, user_id):
    assert await queue.count_by_status_per_provider(user_id) == {}


# ---------- recent_failures ----------


async def test_recent_failures_lists_the_most_recent_first(queue, user_id):
    await make_dead(queue, user_id, "strava_1")
    await make_dead(queue, user_id, "strava_2", now=NOW + timedelta(minutes=1))

    failures = await queue.recent_failures(user_id, STRAVA)

    assert [failure.activity_key for failure in failures] == ["strava_2", "strava_1"]


async def test_recent_failures_honours_the_limit(queue, user_id):
    await make_dead(queue, user_id, "strava_1")
    await make_dead(queue, user_id, "strava_2", now=NOW + timedelta(minutes=1))

    failures = await queue.recent_failures(user_id, STRAVA, limit=1)

    assert [failure.activity_key for failure in failures] == ["strava_2"]


async def test_recent_failures_lists_only_dead_items(queue, user_id):
    await make_blocked(queue, user_id, "strava_1")
    await enqueue(queue, user_id, "strava_2")

    assert await queue.recent_failures(user_id, STRAVA) == []


async def test_recent_failures_is_scoped_to_the_user_and_provider(queue, user_id, other_user_id):
    await make_dead(queue, other_user_id, "strava_1")
    await make_dead(queue, user_id, "garmin_1", provider=GARMIN)

    assert await queue.recent_failures(user_id, STRAVA) == []


# ---------- earliest_run_after ----------


async def test_earliest_run_after_is_empty_without_queued_items(queue, user_id):
    assert await queue.earliest_run_after(user_id, STRAVA) == {}


async def test_earliest_run_after_is_the_earliest_queued_item(queue, user_id):
    await enqueue(queue, user_id, "strava_1", now=NOW + timedelta(minutes=2))
    await enqueue(queue, user_id, "strava_2", now=NOW + timedelta(minutes=1))

    assert await queue.earliest_run_after(user_id, STRAVA) == {
        ImportPriority.SYNC: NOW + timedelta(minutes=1)
    }


async def test_earliest_run_after_includes_a_retry_wait(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.retry_later(
        claim,
        run_after=NOW + timedelta(minutes=10),
        error_code=ImportErrorCode.UNAVAILABLE,
        last_error="503",
        now=NOW,
    )

    assert await queue.earliest_run_after(user_id, STRAVA) == {
        ImportPriority.SYNC: NOW + timedelta(minutes=10)
    }


async def test_earliest_run_after_ignores_running_dead_and_blocked_items(queue, user_id):
    await make_blocked(queue, user_id, "strava_1")
    await make_dead(queue, user_id, "strava_2")
    await enqueue(queue, user_id, "strava_3")
    await claim_next(queue)
    await enqueue(queue, user_id, "strava_4", now=NOW + timedelta(minutes=5))

    assert await queue.earliest_run_after(user_id, STRAVA) == {
        ImportPriority.SYNC: NOW + timedelta(minutes=5)
    }


async def test_earliest_run_after_is_scoped_to_the_user_and_provider(queue, user_id, other_user_id):
    await enqueue(queue, other_user_id, "strava_1")
    await enqueue(queue, user_id, "garmin_1", provider=GARMIN)

    assert await queue.earliest_run_after(user_id, STRAVA) == {}


# ---------- retry_failures ----------


async def test_retry_failures_queues_dead_items_with_their_attempts_reset(queue, user_id):
    await make_dead(queue, user_id, "strava_1")

    assert await queue.retry_failures(user_id, STRAVA, now=LATER) == 1

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    assert (await claim_next(queue, now=LATER)).attempts == 1


async def test_retry_failures_retries_only_the_selected_items(queue, user_id):
    await make_dead(queue, user_id, "strava_1")
    await make_dead(queue, user_id, "strava_2")

    assert await queue.retry_failures(user_id, STRAVA, activity_keys=["strava_2"], now=LATER) == 1

    assert [failure.activity_key for failure in await queue.recent_failures(user_id, STRAVA)] == [
        "strava_1"
    ]


async def test_retry_failures_leaves_blocked_items_and_other_users_alone(
    queue, user_id, other_user_id
):
    await make_blocked(queue, user_id, "strava_1")
    await make_dead(queue, other_user_id, "strava_2")

    assert await queue.retry_failures(user_id, STRAVA, now=LATER) == 0

    assert await queue.count_by_status(user_id, STRAVA) == counts(blocked=1)
    assert await queue.count_by_status(other_user_id, STRAVA) == counts(dead=1)


# ---------- dismiss_failures ----------


async def test_dismiss_failures_deletes_dead_items(queue, user_id):
    await make_dead(queue, user_id, "strava_1")
    await make_dead(queue, user_id, "strava_2")

    assert await queue.dismiss_failures(user_id, STRAVA) == 2

    assert await queue.count_by_status(user_id, STRAVA) == counts()


async def test_dismiss_failures_deletes_only_the_selected_items(queue, user_id):
    await make_dead(queue, user_id, "strava_1")
    await make_dead(queue, user_id, "strava_2")

    assert await queue.dismiss_failures(user_id, STRAVA, activity_keys=["strava_1"]) == 1

    assert [failure.activity_key for failure in await queue.recent_failures(user_id, STRAVA)] == [
        "strava_2"
    ]


async def test_dismiss_failures_leaves_other_statuses_and_users_alone(
    queue, user_id, other_user_id
):
    await make_dead(queue, other_user_id, "strava_3")
    await make_blocked(queue, user_id, "strava_1")
    await enqueue(queue, user_id, "strava_2")

    assert await queue.dismiss_failures(user_id, STRAVA) == 0

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1, blocked=1)
    assert await queue.count_by_status(other_user_id, STRAVA) == counts(dead=1)


# ---------- delete ----------


async def test_delete_removes_the_item(queue, user_id):
    await enqueue(queue, user_id, "strava_1")

    assert await queue.delete(user_id, STRAVA, "strava_1") is True

    assert await queue.count_by_status(user_id, STRAVA) == counts()


async def test_delete_returns_false_when_there_is_no_item(queue, user_id):
    assert await queue.delete(user_id, STRAVA, "strava_1") is False


async def test_delete_is_scoped_to_the_user_and_provider(queue, user_id, other_user_id):
    await enqueue(queue, other_user_id, "1")
    await enqueue(queue, user_id, "1", provider=GARMIN)

    assert await queue.delete(user_id, STRAVA, "1") is False

    assert await queue.count_by_status(other_user_id, STRAVA) == counts(queued=1)
    assert await queue.count_by_status(user_id, GARMIN) == counts(queued=1)


# ---------- delete_user_items ----------


async def test_delete_user_items_deletes_items_in_every_status(queue, user_id):
    await make_blocked(queue, user_id, "strava_1")
    await make_dead(queue, user_id, "strava_2")
    await enqueue(queue, user_id, "strava_3", "strava_4")
    await claim_next(queue)

    assert await queue.delete_user_items(user_id, STRAVA) == 4

    assert await queue.count_by_status(user_id, STRAVA) == counts()


async def test_delete_user_items_is_scoped_to_the_user_and_provider(queue, user_id, other_user_id):
    await enqueue(queue, other_user_id, "strava_1")
    await enqueue(queue, user_id, "garmin_1", provider=GARMIN)

    assert await queue.delete_user_items(user_id, STRAVA) == 0

    assert await queue.count_by_status(other_user_id, STRAVA) == counts(queued=1)
    assert await queue.count_by_status(user_id, GARMIN) == counts(queued=1)


# ---------- enqueue_webhook ----------


async def test_webhook_queues_a_new_item_at_webhook_priority(queue, user_id):
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW)

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    assert await queue.lock_next(STRAVA, now=NOW) == QueuedItem(
        user_id=user_id,
        provider=STRAVA,
        activity_key="strava_1",
        source=ImportSource.WEBHOOK,
        priority=ImportPriority.WEBHOOK,
        generation=0,
        raw_payload=None,
    )


async def test_webhook_stores_what_the_provider_sent_and_claims_carry_it(queue, user_id):
    await queue.enqueue_webhook(user_id, GARMIN, "garmin_1", sent_data=SENT, now=NOW)

    item = await queue.lock_next(GARMIN, now=NOW)
    claim = await queue.claim(item, lease=LEASE, now=NOW)

    assert (item.sent_data, claim.sent_data) == (SENT, SENT)


async def test_a_repeated_webhook_replaces_what_the_provider_sent(queue, user_id):
    newer = {**SENT, "url": "https://provider.example/file?token=t2"}
    await queue.enqueue_webhook(user_id, GARMIN, "garmin_1", sent_data=SENT, now=NOW)

    await queue.enqueue_webhook(user_id, GARMIN, "garmin_1", sent_data=newer, now=NOW)

    assert (await queue.lock_next(GARMIN, now=NOW)).sent_data == newer


async def test_a_repeated_webhook_without_sent_data_clears_the_earlier_one(queue, user_id):
    await queue.enqueue_webhook(user_id, GARMIN, "garmin_1", sent_data=SENT, now=NOW)

    await queue.enqueue_webhook(user_id, GARMIN, "garmin_1", now=NOW)

    assert (await queue.lock_next(GARMIN, now=NOW)).sent_data is None


async def test_a_webhook_during_the_run_reaches_the_next_claim_with_what_it_sent(queue, user_id):
    newer = {**SENT, "url": "https://provider.example/file?token=t2"}
    await queue.enqueue_webhook(user_id, GARMIN, "garmin_1", sent_data=SENT, now=NOW)
    first = await claim_next(queue, provider=GARMIN)
    await queue.enqueue_webhook(user_id, GARMIN, "garmin_1", sent_data=newer, now=NOW)

    assert await queue.finish(first, now=NOW) == FinishOutcome.REQUEUED

    assert (await claim_next(queue, provider=GARMIN)).sent_data == newer


async def test_a_payload_saved_after_a_webhook_during_the_run_is_dropped(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(minutes=1))

    assert await queue.save_payload(claim, RAW, now=NOW + timedelta(minutes=1)) is True

    assert await queue.finish(claim, now=NOW + timedelta(minutes=1)) == FinishOutcome.REQUEUED
    assert (await queue.lock_next(STRAVA, now=LATER)).raw_payload is None


async def test_webhook_item_is_not_claimable_before_now(queue, user_id):
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW)

    assert await queue.lock_next(STRAVA, now=NOW - timedelta(seconds=1)) is None


async def test_webhook_items_are_claimed_before_sync_items(queue, user_id, other_user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    await queue.enqueue_webhook(other_user_id, STRAVA, "strava_3", now=NOW + timedelta(hours=1))

    assert await claim_order(queue, now=LATER) == ["strava_3", "strava_1", "strava_2"]


async def test_webhook_items_are_claimed_in_arrival_order(queue, user_id, other_user_id):
    await queue.enqueue_webhook(user_id, STRAVA, "strava_2", now=NOW)
    await queue.enqueue_webhook(other_user_id, STRAVA, "strava_1", now=NOW + timedelta(seconds=1))

    assert await claim_order(queue, now=LATER) == ["strava_2", "strava_1"]


async def test_a_repeated_webhook_merges_into_the_item_with_a_new_generation(queue, user_id):
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW)
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(seconds=1))

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    assert (await queue.lock_next(STRAVA, now=LATER)).generation == 1


async def test_a_repeated_webhook_keeps_the_items_place_in_the_queue(queue, user_id, other_user_id):
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW)
    await queue.enqueue_webhook(other_user_id, STRAVA, "strava_2", now=NOW + timedelta(seconds=1))
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(seconds=2))

    assert await claim_order(queue, now=LATER) == ["strava_1", "strava_2"]


async def test_a_webhook_turns_a_queued_sync_item_into_a_webhook_item(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")

    await queue.enqueue_webhook(user_id, STRAVA, "strava_2", now=NOW + timedelta(minutes=1))

    assert await queue.lock_next(STRAVA, now=LATER) == QueuedItem(
        user_id=user_id,
        provider=STRAVA,
        activity_key="strava_2",
        source=ImportSource.WEBHOOK,
        priority=ImportPriority.WEBHOOK,
        generation=1,
        raw_payload=None,
    )


async def test_a_webhook_for_a_backfill_item_orders_it_by_the_webhook(
    queue, user_id, other_user_id
):
    # NOW + 20 s, 40 s, 60 s
    await enqueue(queue, user_id, "strava_1", "strava_2", "strava_3")

    await queue.enqueue_webhook(user_id, STRAVA, "strava_3", now=NOW + timedelta(seconds=10))
    await queue.enqueue_webhook(other_user_id, STRAVA, "strava_9", now=NOW + timedelta(seconds=15))

    assert await claim_order(queue, now=LATER) == ["strava_3", "strava_9", "strava_1", "strava_2"]


async def test_a_webhook_during_a_run_keeps_the_item_running(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    await claim_next(queue)

    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(minutes=1))

    assert await queue.count_by_status(user_id, STRAVA) == counts(running=1)
    assert await queue.lock_next(STRAVA, now=LATER) is None


async def test_finishing_a_run_that_a_webhook_queued_again_queues_it_again(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(minutes=1))
    finished_at = NOW + timedelta(minutes=2)

    assert await queue.finish(claim, now=finished_at) == FinishOutcome.REQUEUED

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    again = await claim_next(queue, now=finished_at)
    assert (again.generation, again.attempts) == (1, 1)
    assert await queue.finish(again, now=finished_at) == FinishOutcome.DONE


async def test_a_webhook_during_a_run_keeps_its_attempts(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(minutes=1))
    retry_at = NOW + timedelta(minutes=2)

    await queue.retry_later(
        claim,
        run_after=retry_at,
        error_code=ImportErrorCode.UNAVAILABLE,
        last_error="503",
        now=NOW + timedelta(minutes=1),
    )

    assert (await claim_next(queue, now=retry_at)).attempts == 2


async def test_a_retry_after_a_webhook_during_the_run_drops_the_stale_payload(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(minutes=1))

    assert (
        await queue.retry_later(
            claim,
            run_after=NOW + timedelta(minutes=2),
            error_code=ImportErrorCode.PROCESSING_FAILED,
            last_error="ValueError",
            raw_payload=RAW,
            now=NOW + timedelta(minutes=1),
        )
        is True
    )

    assert (await queue.lock_next(STRAVA, now=LATER)).raw_payload is None


async def test_a_dead_end_after_a_webhook_during_the_run_drops_the_stale_payload(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(minutes=1))
    await queue.mark_dead(
        claim,
        error_code=ImportErrorCode.PROCESSING_FAILED,
        last_error="ValueError",
        raw_payload=RAW,
        now=NOW + timedelta(minutes=1),
    )

    await queue.retry_failures(user_id, STRAVA, now=LATER)

    assert (await queue.lock_next(STRAVA, now=LATER)).raw_payload is None


async def test_a_webhook_queues_a_dead_item_again_with_its_attempts_reset(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    first = await claim_next(queue)
    await queue.retry_later(
        first,
        run_after=NOW,
        error_code=ImportErrorCode.UNAVAILABLE,
        last_error="503",
        now=NOW,
    )
    second = await claim_next(queue)
    await queue.mark_dead(second, error_code=ImportErrorCode.UNAVAILABLE, last_error="503", now=NOW)

    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=LATER)

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    assert await queue.recent_failures(user_id, STRAVA) == []
    assert (await claim_next(queue, now=LATER)).attempts == 1


async def test_a_webhook_queues_a_blocked_item_again_claimable_at_once(queue, user_id):
    await enqueue(queue, user_id, "strava_1", "strava_2")
    first = await claim_next(queue)
    await queue.retry_later(
        first,
        run_after=NOW + timedelta(hours=1),
        error_code=ImportErrorCode.UNAVAILABLE,
        last_error="503",
        now=NOW,
    )
    second = await claim_next(queue)
    await queue.block(second, last_error="401", now=NOW)
    event_at = NOW + timedelta(minutes=1)

    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=event_at)

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1, blocked=1)
    claim = await claim_next(queue, now=event_at)
    assert (claim.activity_key, claim.attempts) == ("strava_1", 1)


async def test_a_webhook_keeps_a_queued_items_retry_wait(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    retry_at = NOW + timedelta(hours=1)
    await queue.retry_later(
        claim,
        run_after=retry_at,
        error_code=ImportErrorCode.UNAVAILABLE,
        last_error="503",
        now=NOW,
    )

    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(minutes=1))

    assert await queue.lock_next(STRAVA, now=retry_at - timedelta(seconds=1)) is None
    assert await queue.earliest_run_after(user_id, STRAVA) == {ImportPriority.WEBHOOK: retry_at}
    assert (await claim_next(queue, now=retry_at)).attempts == 2


async def test_a_webhook_clears_the_saved_raw_payload(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    claim = await claim_next(queue)
    await queue.retry_later(
        claim,
        run_after=NOW,
        error_code=ImportErrorCode.PROCESSING_FAILED,
        last_error="ValueError",
        raw_payload=RAW,
        now=NOW,
    )

    await queue.enqueue_webhook(user_id, STRAVA, "strava_1", now=NOW + timedelta(minutes=1))

    assert (await queue.lock_next(STRAVA, now=LATER)).raw_payload is None


async def test_webhook_items_are_separate_per_user_and_provider(queue, user_id, other_user_id):
    await queue.enqueue_webhook(user_id, STRAVA, "1", now=NOW)
    await queue.enqueue_webhook(other_user_id, STRAVA, "1", now=NOW)
    await queue.enqueue_webhook(user_id, GARMIN, "1", now=NOW)

    assert await queue.count_by_status(user_id, STRAVA) == counts(queued=1)
    assert await queue.count_by_status(other_user_id, STRAVA) == counts(queued=1)
    assert await queue.count_by_status(user_id, GARMIN) == counts(queued=1)
    assert (await queue.lock_next(GARMIN, now=NOW)).generation == 0


async def test_earliest_run_after_reports_webhook_items_under_their_priority(queue, user_id):
    await enqueue(queue, user_id, "strava_1")
    await queue.enqueue_webhook(user_id, STRAVA, "strava_2", now=NOW + timedelta(minutes=1))

    assert await queue.earliest_run_after(user_id, STRAVA) == {
        ImportPriority.SYNC: NOW,
        ImportPriority.WEBHOOK: NOW + timedelta(minutes=1),
    }
