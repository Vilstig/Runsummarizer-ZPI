import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.core.request_context import log_context_var
from app.db.protocols.import_queue import Claim, QueuedItem
from app.domain.enums import ImportErrorCode, ImportPriority, ImportStatus, Provider, WindowKind
from app.domain.errors import ProviderAuthorizationError, ProviderUnavailableError
from app.domain.models import BudgetPolicy, BudgetWindow, ProviderCredentials, ZoneTimes
from app.providers.base import NormalizedActivity, ResponseObserver
from app.services import activity_pipeline
from app.services.activity_import import (
    BACKOFF_BASE,
    BACKOFF_JITTER,
    BACKOFF_MAX,
    LEASE,
    ItemOutcome,
    ItemResult,
    import_next_item,
    retry_delay,
)
from app.services.activity_pipeline import ImportedActivity
from tests.db.builders import make_run
from tests.services.fakes import FakeImportItem


@pytest.mark.parametrize(
    ("attempts", "delay"),
    [(1, BACKOFF_BASE), (2, BACKOFF_BASE * 2), (3, BACKOFF_BASE * 4), (100, BACKOFF_MAX)],
    ids=["first", "second", "third", "capped"],
)
def test_the_retry_delay_doubles_with_every_attempt_up_to_the_cap(attempts, delay):
    assert retry_delay(attempts, rand=lambda: 0.5) == delay


@pytest.mark.parametrize(("rand", "factor"), [(0.0, 1 - BACKOFF_JITTER), (1.0, 1 + BACKOFF_JITTER)])
def test_the_retry_delay_varies_by_up_to_the_jitter_either_way(rand, factor):
    delay = retry_delay(2, rand=lambda: rand)

    assert delay.total_seconds() == pytest.approx((BACKOFF_BASE * 2).total_seconds() * factor)


def test_the_retry_delay_is_capped_after_the_jitter():
    assert retry_delay(100, rand=lambda: 1.0) == BACKOFF_MAX


# ---------- what the importer says about its items ----------
#
# A provider's importer, as the queue sees it, over the fake database: what was sent with
# the item, a fetch that can't be repeated, and the attempts the importer gives an item.

PROVIDER = Provider.GARMIN
USER_ID = "user-1"
KEY = "garmin_7"
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
SENT = {"format": "fake_notification_v1", "url": "https://provider.example/file?token=t1"}
POLICY = BudgetPolicy(
    windows=(
        BudgetWindow(
            name="minute",
            length=timedelta(minutes=1),
            kind=WindowKind.ROLLING,
            bucket=timedelta(seconds=10),
            default_limit=50,
        ),
    ),
    ceilings={},
)


class WorkerDiedError(BaseException):
    """Ends a run the way a killed worker does: nothing after it is written."""


class FakeImporter:
    """An importer whose fetch downloads what the item's ``sent_data`` points at."""

    provider = PROVIDER

    def __init__(self, *, single_use_fetch: bool = True, max_attempts: int = 3):
        self.single_use_fetch = single_use_fetch
        self.max_attempts = max_attempts
        self.fetched: list[dict | None] = []  # the sent_data of each fetch's claim
        self.normalized: list[dict] = []  # each payload normalize was given
        self.error: Exception | None = None  # raised by fetch
        self.during_fetch: Callable[[], Awaitable[None]] | None = None

    def cost(self, item: QueuedItem) -> int:
        return 1

    async def fetch(
        self, claim: Claim, credentials: ProviderCredentials, on_response: ResponseObserver
    ) -> dict | None:
        self.fetched.append(claim.sent_data)
        if self.during_fetch is not None:
            await self.during_fetch()
        if self.error is not None:
            raise self.error
        return {"format": "fake_file_v1", "key": claim.activity_key, "file": "Zml0"}

    def normalize(self, payload: dict) -> NormalizedActivity | None:
        self.normalized.append(payload)
        activity = make_run(payload["key"], source=PROVIDER.value)
        activity = replace(activity, zone_times=ZoneTimes(), zone_bounds=None)
        return NormalizedActivity(
            activity=activity, streams={}, payload_kind="fake_file", stored_payload=payload
        )


@pytest.fixture
def connected(db):
    """The user's stored credentials for ``PROVIDER``, which don't expire."""
    db.provider_credentials[PROVIDER, USER_ID] = ProviderCredentials("access-1", None, None)


@pytest.fixture
def importer() -> FakeImporter:
    return FakeImporter()


async def import_next(db, importer: FakeImporter, *, now: datetime = NOW):
    return await import_next_item(
        importer, budget_policy=POLICY, transaction=db.transaction, clock=lambda: now
    )


def queue(db, **fields) -> None:
    """Commit a webhook item for ``KEY``, holding ``SENT``."""
    db.queue_item(
        USER_ID, KEY, provider=PROVIDER, priority=ImportPriority.WEBHOOK, sent_data=SENT, **fields
    )


def item(db) -> FakeImportItem | None:
    return db.import_item(USER_ID, KEY, provider=PROVIDER)


def result(outcome: ItemOutcome) -> ItemResult:
    return ItemResult(PROVIDER, USER_ID, KEY, outcome)


def during_processing(monkeypatch, action: Callable[[], None]) -> None:
    """Call ``action()`` once the item's payload is in hand, before its record is built."""
    build_import = activity_pipeline.build_import

    def build_after_action(*args) -> ImportedActivity:
        action()
        return build_import(*args)

    monkeypatch.setattr(activity_pipeline, "build_import", build_after_action)


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_the_fetch_reads_what_the_provider_sent_with_the_item(db, importer):
    queue(db)

    assert await import_next(db, importer) == result(ItemOutcome.IMPORTED)
    assert importer.fetched == [SENT]
    assert KEY in db.activities


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_a_single_use_fetch_is_saved_on_the_item_before_processing(db, importer, monkeypatch):
    queue(db)
    seen: list[tuple[ImportStatus, dict | None]] = []
    during_processing(monkeypatch, lambda: seen.append((item(db).status, item(db).raw_payload)))

    assert await import_next(db, importer) == result(ItemOutcome.IMPORTED)
    [payload] = importer.normalized
    assert seen == [(ImportStatus.RUNNING, payload)]
    assert item(db) is None


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_a_fetch_that_can_be_repeated_is_not_saved_before_processing(db, monkeypatch):
    importer = FakeImporter(single_use_fetch=False)
    queue(db)
    seen: list[dict | None] = []
    during_processing(monkeypatch, lambda: seen.append(item(db).raw_payload))

    assert await import_next(db, importer) == result(ItemOutcome.IMPORTED)
    assert seen == [None]


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_a_lease_lost_before_the_checkpoint_ends_the_run_unprocessed(db, importer):
    queue(db)
    other_token = uuid.uuid4()

    async def claimed_elsewhere() -> None:
        item(db).lease_token = other_token

    importer.during_fetch = claimed_elsewhere

    assert await import_next(db, importer) == result(ItemOutcome.LOST)
    assert importer.normalized == []
    assert db.activities == {}
    lost = item(db)
    assert (lost.status, lost.lease_token, lost.raw_payload) == (
        ImportStatus.RUNNING,
        other_token,
        None,
    )


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_a_webhook_during_the_fetch_keeps_the_payload_off_the_requeued_item(db, importer):
    queue(db)
    newer = {**SENT, "url": "https://provider.example/file?token=t2"}

    async def webhook() -> None:
        async with db.transaction() as repos:
            await repos.import_queue.enqueue_webhook(
                USER_ID, PROVIDER, KEY, sent_data=newer, now=NOW
            )

    importer.during_fetch = webhook

    assert await import_next(db, importer) == result(ItemOutcome.REQUEUED)
    assert KEY in db.activities
    requeued = item(db)
    assert (requeued.status, requeued.generation) == (ImportStatus.QUEUED, 1)
    assert (requeued.raw_payload, requeued.sent_data) == (None, newer)


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_an_item_whose_worker_died_after_the_checkpoint_is_imported_without_a_fetch(
    db, importer, monkeypatch
):
    queue(db)
    deaths: list[int] = []

    def die_once() -> None:
        if not deaths:
            deaths.append(1)
            raise WorkerDiedError

    during_processing(monkeypatch, die_once)
    with pytest.raises(WorkerDiedError):
        await import_next(db, importer)
    after_lease = NOW + LEASE + timedelta(seconds=1)
    async with db.transaction() as repos:
        await repos.import_queue.expire_leases(
            PROVIDER, max_attempts=importer.max_attempts, now=after_lease
        )
    db.budget(PROVIDER).calls_left = 0

    assert await import_next(db, importer, now=after_lease) == result(ItemOutcome.IMPORTED)
    assert importer.fetched == [SENT]
    [first, second] = importer.normalized
    assert first == second
    assert db.raw_payloads[KEY] == first
    assert item(db) is None


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
@pytest.mark.parametrize(
    ("attempts_before", "outcome", "status"),
    [(1, ItemOutcome.RETRYING, ImportStatus.QUEUED), (2, ItemOutcome.DEAD, ImportStatus.DEAD)],
    ids=["before-the-last-attempt", "on-the-last-attempt"],
)
async def test_an_unavailable_provider_retries_the_item_until_the_importers_max_attempts(
    db, attempts_before, outcome, status
):
    importer = FakeImporter(max_attempts=3)
    importer.error = ProviderUnavailableError("503")
    queue(db, attempts=attempts_before)

    assert await import_next(db, importer) == result(outcome)
    failed = item(db)
    assert (failed.status, failed.attempts) == (status, attempts_before + 1)
    assert failed.error_code == ImportErrorCode.UNAVAILABLE


# ---------- logging ----------


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_the_log_context_is_the_item_while_it_is_imported_then_reset(
    db, importer, monkeypatch
):
    queue(db)
    seen: list[str] = []
    during_processing(monkeypatch, lambda: seen.append(log_context_var.get()))

    assert log_context_var.get() == "-"
    assert await import_next(db, importer) == result(ItemOutcome.IMPORTED)
    assert seen == [f"{PROVIDER}:{KEY}"]
    assert log_context_var.get() == "-"


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_an_authorization_error_logs_a_warning_with_the_reason(db, importer, caplog):
    caplog.set_level("WARNING", logger="app.services.activity_import")
    importer.error = ProviderAuthorizationError("revoked")
    queue(db)

    assert await import_next(db, importer) == result(ItemOutcome.BLOCKED)
    assert "blocked" in caplog.text
    assert "revoked" in caplog.text


@pytest.mark.anyio
@pytest.mark.usefixtures("connected")
async def test_a_failed_item_logs_the_error_code_and_whether_it_is_dead(db, caplog):
    caplog.set_level("WARNING", logger="app.services.activity_import")
    importer = FakeImporter(max_attempts=1)
    importer.error = ProviderUnavailableError("503")
    queue(db)

    assert await import_next(db, importer) == result(ItemOutcome.DEAD)
    assert "unavailable" in caplog.text
    assert "dead" in caplog.text
    assert "503" in caplog.text
