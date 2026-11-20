import dataclasses
import threading
import uuid
from datetime import UTC, datetime, timedelta

import anyio
import httpx
import pytest

from app.domain.enums import ImportErrorCode, ImportPriority, ImportStatus
from app.domain.models import HeartRateZonesRecord, ZoneTimes
from app.providers.strava import importer as strava_importer
from app.providers.strava.budget import STRAVA_BUDGET_POLICY
from app.providers.strava.importer import ITEM_COST, StravaImporter
from app.providers.strava.oauth import StravaTokenRefresher
from app.services import activity_pipeline
from app.services.activity_import import (
    BACKOFF_MAX,
    LEASE,
    PROCESSING_MAX_ATTEMPTS,
    ItemOutcome,
    ItemResult,
    OverBudget,
    import_next_item,
    retry_delay,
)
from app.services.activity_pipeline import ImportedActivity
from tests.services.fakes import (
    USER_HR_ZONES,
    FakeActivityRepository,
    FakeImportItem,
    run_payload,
    stored_run,
    strava_run,
    strava_usage,
)

USER_ID = "user-1"
OTHER_USER_ID = "user-2"  # holds no Strava tokens
KEY = "strava_7"

DETAIL = "/api/v3/activities/7"
STREAMS = "/api/v3/activities/7/streams"

NOW = datetime(2026, 10, 8, 12, 7, tzinfo=UTC)
NEXT_WINDOW = datetime(2026, 10, 8, 12, 15, tzinfo=UTC)
NEXT_MIDNIGHT = datetime(2026, 10, 9, tzinfo=UTC)


@pytest.fixture(autouse=True)
def connected(db):
    """The user's stored Strava tokens, with an access token that has expired."""
    db.add_strava_user(USER_ID, 101, "refresh-1")


async def import_next(db, strava, *, now: datetime = NOW):
    """``import_next_item`` for Strava, at ``now``."""

    def clock() -> datetime:
        return now

    importer = StravaImporter(transport=strava.transport, clock=clock)
    refresher = StravaTokenRefresher(transport=strava.transport, clock=clock)
    return await import_next_item(
        importer,
        budget_policy=STRAVA_BUDGET_POLICY,
        token_refresher=refresher,
        transaction=db.transaction,
        clock=clock,
    )


def queue(db, activity_id: int = 7, *, user_id: str = USER_ID, **fields) -> None:
    db.queue_item(user_id, f"strava_{activity_id}", **fields)


def item(db, activity_id: int = 7, *, user_id: str = USER_ID) -> FakeImportItem | None:
    return db.import_item(user_id, f"strava_{activity_id}")


def result(outcome: ItemOutcome, activity_id: int = 7) -> ItemResult:
    return ItemResult("strava", USER_ID, f"strava_{activity_id}", outcome)


def api_paths(strava) -> list[str]:
    """The paths of the Strava API calls made, token requests left out."""
    return [r.url.path for r in strava.requests if r.url.path.startswith("/api/v3/")]


def during_processing(monkeypatch, action) -> None:
    """Await ``action()`` once the item's payload is in hand, before its record is built."""
    build_import = activity_pipeline.build_import

    def build_after_action(*args) -> ImportedActivity:
        anyio.from_thread.run(action)
        return build_import(*args)

    monkeypatch.setattr(activity_pipeline, "build_import", build_after_action)


def failing_classifier(activity):
    raise RuntimeError("model unavailable")


def assert_backed_off(run_after: datetime, attempts: int) -> None:
    """``run_after`` is ``NOW`` plus the retry delay after ``attempts`` attempts."""
    earliest = NOW + retry_delay(attempts, rand=lambda: 0.0)
    latest = NOW + retry_delay(attempts, rand=lambda: 1.0)
    assert earliest <= run_after <= latest


# ---------- claiming ----------


@pytest.mark.anyio
async def test_an_empty_queue_claims_nothing(db, strava):
    assert await import_next(db, strava) is None
    assert strava.requests == []


@pytest.mark.anyio
async def test_an_item_is_not_claimed_before_its_run_after(db, strava):
    queue(db, run_after=NOW + timedelta(seconds=1))

    assert await import_next(db, strava) is None
    assert item(db).status == ImportStatus.QUEUED


@pytest.mark.anyio
async def test_another_providers_items_are_not_claimed(db, strava):
    db.queue_item(USER_ID, "garmin_7", provider="garmin")

    assert await import_next(db, strava) is None
    assert db.import_item(USER_ID, "garmin_7", provider="garmin").status == ImportStatus.QUEUED


@pytest.mark.anyio
async def test_a_run_is_saved_and_its_item_deleted(db, strava):
    strava.add(strava_run(7))
    queue(db)

    assert await import_next(db, strava) == result(ItemOutcome.IMPORTED)
    assert db.activities[KEY].user_id == USER_ID
    assert db.raw_payloads[KEY] == strava_run(7)
    assert db.payload_kinds[KEY] == "strava_detail"
    assert item(db) is None
    assert api_paths(strava) == [DETAIL, STREAMS]


@pytest.mark.anyio
async def test_a_run_is_saved_with_heart_rate_zone_time_in_the_users_zones(db, strava):
    db.hr_zones[USER_ID] = [HeartRateZonesRecord(valid_from=NOW, zones=USER_HR_ZONES)]
    strava.add(strava_run(7))
    queue(db)

    await import_next(db, strava)

    assert db.activities[KEY].activity.zone_times == ZoneTimes(zone2=1.0, zone3=1.0)
    assert db.activities[KEY].activity.zone_bounds == (120, 145, 155, 175)


@pytest.mark.anyio
async def test_a_run_of_a_user_without_zones_is_saved_with_the_default_zones(db, strava):
    strava.add(strava_run(7))
    queue(db)

    await import_next(db, strava)

    assert db.activities[KEY].activity.zone_times == ZoneTimes(zone3=2.0)
    assert db.activities[KEY].activity.zone_bounds == (120, 140, 160, 180)


@pytest.mark.anyio
async def test_the_claim_is_committed_before_the_item_is_imported(db, strava, monkeypatch):
    strava.add(strava_run(7))
    queue(db)
    seen = []

    async def look() -> None:
        seen.append(dataclasses.replace(item(db)))

    during_processing(monkeypatch, look)

    await import_next(db, strava)

    [running] = seen
    assert running.status == ImportStatus.RUNNING
    assert running.attempts == 1
    assert running.lease_until == NOW + LEASE
    assert running.lease_token is not None


@pytest.mark.anyio
async def test_webhook_items_are_claimed_before_sync_items(db, strava):
    strava.add(strava_run(1))
    strava.add(strava_run(2))
    queue(db, 1)
    queue(db, 2, priority=ImportPriority.WEBHOOK, sort_key=NOW)

    assert await import_next(db, strava) == result(ItemOutcome.IMPORTED, 2)
    assert await import_next(db, strava) == result(ItemOutcome.IMPORTED, 1)


@pytest.mark.anyio
@pytest.mark.parametrize("priority", list(ImportPriority), ids=lambda p: p.name.lower())
async def test_the_detail_and_streams_are_reserved_under_the_items_priority(db, strava, priority):
    strava.add(strava_run(7))
    queue(db, priority=priority)

    await import_next(db, strava)

    assert db.budget("strava").reservations == [(ITEM_COST, priority)]


@pytest.mark.anyio
async def test_an_item_the_budget_cannot_take_stays_queued(db, strava):
    db.budget("strava").calls_left = 0
    db.budget("strava").refills_at = NEXT_WINDOW
    strava.add(strava_run(7))
    queue(db)

    assert await import_next(db, strava) == OverBudget(NEXT_WINDOW)
    queued = item(db)
    assert queued.status == ImportStatus.QUEUED
    assert queued.attempts == 0
    assert strava.requests == []


@pytest.mark.anyio
async def test_a_saved_payload_is_imported_without_strava_or_budget(db, strava):
    db.budget("strava").calls_left = 0
    queue(db, raw_payload=run_payload(7))

    assert await import_next(db, strava) == result(ItemOutcome.IMPORTED)
    assert db.raw_payloads[KEY] == strava_run(7)
    assert item(db) is None
    assert strava.requests == []
    assert db.budget("strava").reservations == []


@pytest.mark.anyio
async def test_an_untagged_saved_payload_is_read_as_strava_v1(db, strava):
    untagged = run_payload(7)
    del untagged["format"]
    queue(db, raw_payload=untagged)

    assert await import_next(db, strava) == result(ItemOutcome.IMPORTED)
    assert db.raw_payloads[KEY] == strava_run(7)


@pytest.mark.anyio
async def test_a_saved_payload_of_an_unknown_format_fails_processing(db, strava):
    queue(db, raw_payload={**run_payload(7), "format": "strava_v9"})

    assert await import_next(db, strava) == result(ItemOutcome.RETRYING)
    retried = item(db)
    assert retried.error_code == ImportErrorCode.PROCESSING_FAILED
    assert "strava_v9" in retried.last_error
    assert db.activities == {}


@pytest.mark.anyio
async def test_the_activity_is_built_off_the_event_loop_thread(db, strava, monkeypatch):
    classify = activity_pipeline.classify_laps
    threads = []

    def recording_classifier(activity):
        threads.append(threading.get_ident())
        return classify(activity)

    monkeypatch.setattr(activity_pipeline, "classify_laps", recording_classifier)
    strava.add(strava_run(7))
    queue(db)

    await import_next(db, strava)

    assert threads
    assert threading.get_ident() not in threads


@pytest.mark.anyio
async def test_a_saved_payload_is_imported_while_the_budget_holds_back_the_next_item(db, strava):
    db.budget("strava").calls_left = 0
    db.budget("strava").refills_at = NEXT_WINDOW
    queue(db, 1, priority=ImportPriority.WEBHOOK, sort_key=NOW)
    queue(db, 2, raw_payload=run_payload(2))

    assert await import_next(db, strava) == result(ItemOutcome.IMPORTED, 2)
    held = item(db, 1)
    assert (held.status, held.attempts) == (ImportStatus.QUEUED, 0)
    assert strava.requests == []
    assert await import_next(db, strava) == OverBudget(NEXT_WINDOW)


@pytest.mark.anyio
async def test_the_rate_limit_usage_of_every_response_is_recorded(db, strava):
    strava.usage = strava_usage(10, 200, 100, 1000)
    strava.add(strava_run(7))
    queue(db)

    await import_next(db, strava)

    assert db.budget("strava").usage_reports == [strava.usage, strava.usage]


@pytest.mark.anyio
async def test_an_unexpected_error_leaves_the_item_running_until_its_lease_ends(
    db, strava, monkeypatch
):
    async def fetch_strava_payload(client, activity_id: int) -> dict:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(strava_importer, "fetch_strava_payload", fetch_strava_payload)
    queue(db)

    with pytest.raises(RuntimeError, match="unexpected"):
        await import_next(db, strava)

    running = item(db)
    assert running.status == ImportStatus.RUNNING
    assert running.attempts == 1
    assert running.lease_until == NOW + LEASE


# ---------- outcomes ----------


@pytest.mark.anyio
async def test_an_activity_that_is_not_a_run_is_dropped_unsaved(db, strava):
    strava.add(strava_run(7, activity_type="Ride"))
    queue(db)

    assert await import_next(db, strava) == result(ItemOutcome.SKIPPED)
    assert item(db) is None
    assert db.activities == {}
    assert api_paths(strava) == [DETAIL]


@pytest.mark.anyio
async def test_a_stored_activity_is_left_untouched_and_its_item_deleted(db, strava):
    db.activities[KEY] = stored_run(7, user_id=USER_ID, summary="edited")
    strava.add(strava_run(7))
    queue(db)

    assert await import_next(db, strava) == result(ItemOutcome.ALREADY_STORED)
    assert db.activities[KEY] == stored_run(7, user_id=USER_ID, summary="edited")
    assert item(db) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("usage", "until"),
    [
        (strava_usage(100, 400, 100, 1000), NEXT_WINDOW),
        (strava_usage(100, 1000, 100, 1000), NEXT_MIDNIGHT),
        (None, NEXT_WINDOW),
    ],
    ids=["15-minute-limit", "daily-limit", "no-usage"],
)
async def test_a_429_pauses_strava_and_requeues_the_item_without_using_an_attempt(
    db, strava, usage, until
):
    strava.usage = usage
    strava.add(strava_run(7))
    strava.fail(STREAMS, 429)
    queue(db, attempts=1)

    assert await import_next(db, strava) == result(ItemOutcome.RATE_LIMITED)
    released = item(db)
    assert released.status == ImportStatus.QUEUED
    assert released.attempts == 1
    assert released.run_after == until
    assert released.lease_token is None
    assert db.budget("strava").paused_until == until


@pytest.mark.anyio
async def test_a_429_on_the_token_refresh_pauses_strava_and_requeues_the_item(db, strava):
    strava.add(strava_run(7))
    strava.fail("/oauth/token", 429)
    queue(db, attempts=1)

    assert await import_next(db, strava) == result(ItemOutcome.RATE_LIMITED)
    released = item(db)
    assert (released.status, released.attempts) == (ImportStatus.QUEUED, 1)
    assert released.run_after == NEXT_WINDOW
    assert db.budget("strava").paused_until == NEXT_WINDOW
    assert api_paths(strava) == []


@pytest.mark.anyio
async def test_paused_strava_calls_hold_the_next_item_until_the_pause_ends(db, strava):
    db.budget("strava").paused_until = NEXT_WINDOW
    strava.add(strava_run(7))
    queue(db)

    assert await import_next(db, strava) == OverBudget(NEXT_WINDOW)
    assert item(db).status == ImportStatus.QUEUED
    assert strava.requests == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "failure"),
    [
        (DETAIL, 500),
        (STREAMS, 503),
        (DETAIL, httpx.ReadTimeout("timed out")),
        (STREAMS, httpx.ConnectError("connection refused")),
    ],
    ids=["detail-500", "streams-503", "timeout", "connection-error"],
)
async def test_an_unavailable_strava_retries_the_item_after_a_backoff(db, strava, path, failure):
    strava.add(strava_run(7))
    strava.fail(path, failure)
    queue(db)

    assert await import_next(db, strava) == result(ItemOutcome.RETRYING)
    retried = item(db)
    assert retried.status == ImportStatus.QUEUED
    assert retried.attempts == 1
    assert retried.error_code == ImportErrorCode.UNAVAILABLE
    assert retried.last_error
    assert retried.raw_payload is None
    assert_backed_off(retried.run_after, attempts=1)
    assert db.activities == {}


@pytest.mark.anyio
async def test_an_item_unavailable_on_its_last_attempt_is_dead(db, strava):
    strava.add(strava_run(7))
    strava.fail(DETAIL, 500)
    queue(db, attempts=StravaImporter.max_attempts - 1)

    assert await import_next(db, strava) == result(ItemOutcome.DEAD)
    dead = item(db)
    assert dead.status == ImportStatus.DEAD
    assert dead.attempts == StravaImporter.max_attempts
    assert dead.error_code == ImportErrorCode.UNAVAILABLE


@pytest.mark.anyio
async def test_an_activity_strava_does_not_find_is_dead(db, strava):
    queue(db)

    assert await import_next(db, strava) == result(ItemOutcome.DEAD)
    dead = item(db)
    assert dead.status == ImportStatus.DEAD
    assert dead.error_code == ImportErrorCode.NOT_FOUND
    assert api_paths(strava) == [DETAIL]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "status"),
    [(DETAIL, 401), (DETAIL, 403), (STREAMS, 401), ("/oauth/token", 400)],
    ids=["detail-401", "detail-403", "streams-401", "refresh-rejected"],
)
async def test_a_revoked_authorization_blocks_the_users_queued_items(db, strava, path, status):
    strava.add(strava_run(7))
    strava.fail(path, status)
    queue(db, 7)
    queue(db, 8, sort_key=NOW)
    queue(db, 9, user_id=OTHER_USER_ID)

    assert await import_next(db, strava) == result(ItemOutcome.BLOCKED)
    blocked = item(db, 7)
    assert blocked.status == ImportStatus.BLOCKED
    assert blocked.error_code == ImportErrorCode.AUTHORIZATION_REVOKED
    assert blocked.last_error
    assert item(db, 8).status == ImportStatus.BLOCKED
    assert item(db, 9, user_id=OTHER_USER_ID).status == ImportStatus.QUEUED


@pytest.mark.anyio
async def test_a_user_without_strava_tokens_has_their_queued_items_blocked(db, strava):
    queue(db, 7, user_id=OTHER_USER_ID)
    queue(db, 8, user_id=OTHER_USER_ID, sort_key=NOW)

    assert await import_next(db, strava) == ItemResult(
        "strava", OTHER_USER_ID, KEY, ItemOutcome.BLOCKED
    )
    blocked = item(db, 7, user_id=OTHER_USER_ID)
    assert blocked.status == ImportStatus.BLOCKED
    assert blocked.error_code == ImportErrorCode.AUTHORIZATION_REVOKED
    assert blocked.last_error == (
        f"ProviderNotConnectedError: User {OTHER_USER_ID} has no strava credentials"
    )
    assert item(db, 8, user_id=OTHER_USER_ID).status == ImportStatus.BLOCKED
    assert strava.requests == []


@pytest.mark.anyio
async def test_a_processing_failure_saves_the_payload_and_retries_the_item(db, strava, monkeypatch):
    monkeypatch.setattr(activity_pipeline, "classify_laps", failing_classifier)
    strava.add(strava_run(7))
    queue(db)

    assert await import_next(db, strava) == result(ItemOutcome.RETRYING)
    retried = item(db)
    assert retried.status == ImportStatus.QUEUED
    assert retried.error_code == ImportErrorCode.PROCESSING_FAILED
    assert retried.last_error == "RuntimeError: model unavailable"
    assert retried.raw_payload == run_payload(7)
    assert_backed_off(retried.run_after, attempts=1)
    assert db.activities == {}


@pytest.mark.anyio
async def test_an_item_failing_processing_on_its_last_attempt_is_dead_without_calling_strava(
    db, strava, monkeypatch
):
    monkeypatch.setattr(activity_pipeline, "classify_laps", failing_classifier)
    strava.add(strava_run(7))
    queue(db, attempts=PROCESSING_MAX_ATTEMPTS - 2)

    await import_next(db, strava)
    later = NOW + BACKOFF_MAX * 2

    assert await import_next(db, strava, now=later) == result(ItemOutcome.DEAD)
    dead = item(db)
    assert dead.status == ImportStatus.DEAD
    assert dead.attempts == PROCESSING_MAX_ATTEMPTS
    assert dead.error_code == ImportErrorCode.PROCESSING_FAILED
    assert dead.raw_payload == run_payload(7)
    assert api_paths(strava) == [DETAIL, STREAMS]


@pytest.mark.anyio
async def test_a_document_that_fails_to_save_retries_the_item_with_its_payload(
    db, strava, monkeypatch
):
    async def failing_save(self, activity: dict) -> bool:
        raise RuntimeError("invalid document")

    monkeypatch.setattr(FakeActivityRepository, "save", failing_save)
    strava.add(strava_run(7))
    queue(db)

    assert await import_next(db, strava) == result(ItemOutcome.RETRYING)
    retried = item(db)
    assert retried.error_code == ImportErrorCode.PROCESSING_FAILED
    assert retried.raw_payload == run_payload(7)


@pytest.mark.anyio
async def test_an_item_a_webhook_queues_during_its_run_is_saved_and_queued_again(
    db, strava, monkeypatch
):
    strava.add(strava_run(7))
    queue(db)

    async def webhook() -> None:
        async with db.transaction() as repos:
            await repos.import_queue.enqueue_webhook(USER_ID, "strava", KEY, now=NOW)

    during_processing(monkeypatch, webhook)

    assert await import_next(db, strava) == result(ItemOutcome.REQUEUED)
    assert KEY in db.activities
    requeued = item(db)
    assert requeued.status == ImportStatus.QUEUED
    assert requeued.attempts == 0
    assert requeued.generation == 1
    assert requeued.run_after == NOW


@pytest.mark.anyio
async def test_an_item_whose_lease_was_lost_is_left_alone_and_its_save_rolled_back(
    db, strava, monkeypatch
):
    strava.add(strava_run(7))
    queue(db)

    async def claimed_elsewhere() -> None:
        item(db).lease_token = uuid.uuid4()

    during_processing(monkeypatch, claimed_elsewhere)

    assert await import_next(db, strava) == result(ItemOutcome.LOST)
    assert db.activities == {}
    assert item(db).status == ImportStatus.RUNNING
