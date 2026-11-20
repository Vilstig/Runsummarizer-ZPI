from datetime import UTC, datetime, timedelta

import anyio
import pytest

from app.domain.enums import ImportErrorCode, ImportStatus
from app.providers.strava.budget import STRAVA_BUDGET_POLICY
from app.providers.strava.importer import StravaImporter
from app.services import activity_pipeline
from app.services.activity_import import LEASE
from app.services.activity_pipeline import ImportedActivity
from app.worker import loop
from app.worker.loop import PURGE_AFTER, ImportWorker
from tests.services.fakes import strava_run

pytestmark = pytest.mark.anyio

USER_ID = "user-1"
NOW = datetime(2026, 10, 8, 12, 7, tzinfo=UTC)
NEXT_WINDOW = datetime(2026, 10, 8, 12, 15, tzinfo=UTC)
QUICK = timedelta(milliseconds=1)


@pytest.fixture(autouse=True)
def connected(db):
    db.add_strava_user(USER_ID, 101, "refresh-1")


def worker(db, strava, *, poll_interval: timedelta = QUICK) -> ImportWorker:
    """A Strava worker over ``db`` and ``strava``, whose clock stands at NOW."""

    def clock() -> datetime:
        return NOW

    importer = StravaImporter(transport=strava.transport, clock=clock)
    return ImportWorker(
        importer,
        budget_policy=STRAVA_BUDGET_POLICY,
        transaction=db.transaction,
        clock=clock,
        poll_interval=poll_interval,
    )


def queue_runs(db, strava, *activity_ids: int) -> None:
    for activity_id in activity_ids:
        strava.add(strava_run(activity_id))
        db.queue_item(USER_ID, f"strava_{activity_id}")


def stop_during_processing(monkeypatch, stop: anyio.Event) -> None:
    """Set ``stop`` once an item's payload is in hand, before its record is built."""
    build_import = activity_pipeline.build_import

    def build_then_stop(*args) -> ImportedActivity:
        anyio.from_thread.run_sync(stop.set)
        return build_import(*args)

    monkeypatch.setattr(activity_pipeline, "build_import", build_then_stop)


# ---------- run ----------


async def test_run_imports_the_queued_items_until_stopped(db, strava):
    queue_runs(db, strava, 1, 2)
    stop = anyio.Event()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(worker(db, strava).run, stop)
            while db.import_items:
                await anyio.sleep(0.01)
            stop.set()

    assert set(db.activities) == {"strava_1", "strava_2"}


async def test_run_finishes_the_item_being_imported_once_stopped(db, strava, monkeypatch):
    queue_runs(db, strava, 1, 2)
    stop = anyio.Event()
    stop_during_processing(monkeypatch, stop)

    with anyio.fail_after(5):
        await worker(db, strava).run(stop)

    assert set(db.activities) == {"strava_1"}
    assert db.import_item(USER_ID, "strava_2").status == ImportStatus.QUEUED


async def test_run_stops_waiting_once_stopped(db, strava):
    stop = anyio.Event()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(worker(db, strava, poll_interval=timedelta(minutes=1)).run, stop)
            await anyio.wait_all_tasks_blocked()
            stop.set()


async def test_a_failing_round_is_logged_and_the_loop_goes_on(db, strava, monkeypatch, caplog):
    stop = anyio.Event()
    rounds = []

    async def import_next_item(*args, **kwargs):
        rounds.append(len(rounds) + 1)
        if len(rounds) == 1:
            raise RuntimeError("database down")
        stop.set()

    monkeypatch.setattr(loop, "import_next_item", import_next_item)

    with anyio.fail_after(5):
        await worker(db, strava).run(stop)

    assert rounds == [1, 2]
    assert "round failed" in caplog.text


async def test_a_failing_sweep_is_tried_again_at_the_next_sweep_interval(db, strava, monkeypatch):
    the_worker = worker(db, strava)
    stop = anyio.Event()
    sweeps = []
    rounds = []

    async def sweep() -> None:
        sweeps.append(len(sweeps) + 1)
        raise RuntimeError("database down")

    async def import_next_item(*args, **kwargs):
        rounds.append(len(rounds) + 1)
        if len(rounds) == 3:
            stop.set()

    monkeypatch.setattr(the_worker, "sweep", sweep)
    monkeypatch.setattr(loop, "import_next_item", import_next_item)

    with anyio.fail_after(5):
        await the_worker.run(stop)

    assert sweeps == [1]
    assert rounds == [1, 2, 3]


# ---------- run_once ----------


async def test_run_once_reports_whether_an_item_was_claimed(db, strava):
    queue_runs(db, strava, 1)
    the_worker = worker(db, strava)

    assert await the_worker.run_once() is True
    assert await the_worker.run_once() is False


async def test_a_budget_hold_is_logged_once(db, strava, caplog):
    db.budget("strava").calls_left = 0
    db.budget("strava").refills_at = NEXT_WINDOW
    queue_runs(db, strava, 1)
    the_worker = worker(db, strava)
    caplog.set_level("INFO", logger="app.worker")

    assert await the_worker.run_once() is False
    assert await the_worker.run_once() is False

    assert caplog.text.count("holds the next item back") == 1


# ---------- sweep ----------


async def test_the_sweep_queues_an_item_with_an_expired_lease_again(db, strava):
    db.queue_item(
        USER_ID,
        "strava_1",
        status=ImportStatus.RUNNING,
        attempts=1,
        lease_until=NOW - timedelta(seconds=1),
    )

    await worker(db, strava).sweep()

    item = db.import_item(USER_ID, "strava_1")
    assert (item.status, item.attempts, item.run_after) == (ImportStatus.QUEUED, 1, NOW)


async def test_the_sweep_makes_an_item_dead_once_it_used_the_importers_max_attempts(db, strava):
    importer = StravaImporter(transport=strava.transport)
    importer.max_attempts = 2
    the_worker = ImportWorker(
        importer, budget_policy=STRAVA_BUDGET_POLICY, transaction=db.transaction, clock=lambda: NOW
    )
    for key, attempts in (("strava_1", 1), ("strava_2", 2)):
        db.queue_item(
            USER_ID,
            key,
            status=ImportStatus.RUNNING,
            attempts=attempts,
            lease_until=NOW - timedelta(seconds=1),
        )

    await the_worker.sweep()

    requeued = db.import_item(USER_ID, "strava_1")
    dead = db.import_item(USER_ID, "strava_2")
    assert requeued.status == ImportStatus.QUEUED
    assert (dead.status, dead.error_code) == (ImportStatus.DEAD, ImportErrorCode.WORKER_LOST)


async def test_the_sweep_leaves_a_running_item_whose_lease_holds(db, strava):
    db.queue_item(
        USER_ID, "strava_1", status=ImportStatus.RUNNING, attempts=1, lease_until=NOW + LEASE
    )

    await worker(db, strava).sweep()

    assert db.import_item(USER_ID, "strava_1").status == ImportStatus.RUNNING


async def test_the_sweep_deletes_failures_older_than_the_purge_age(db, strava):
    old = NOW - PURGE_AFTER - timedelta(seconds=1)
    recent = NOW - PURGE_AFTER + timedelta(seconds=1)
    for key, updated_at in (("strava_1", old), ("strava_2", recent)):
        db.queue_item(
            USER_ID,
            key,
            status=ImportStatus.DEAD,
            error_code=ImportErrorCode.NOT_FOUND,
            updated_at=updated_at,
        )

    await worker(db, strava).sweep()

    assert db.import_item(USER_ID, "strava_1") is None
    assert db.import_item(USER_ID, "strava_2") is not None


async def test_the_sweep_deletes_the_old_buckets_of_the_providers_budget(db, strava):
    await worker(db, strava).sweep()

    assert db.budget("strava").sweeps == [NOW]
    assert db.budget("garmin").sweeps == []


async def test_the_sweep_refreshes_no_unused_tokens(db, strava):
    class Refresher:
        calls = 0

        async def refresh(self, credentials):
            Refresher.calls += 1
            raise AssertionError("the import worker refreshed an unused token")

    the_worker = ImportWorker(
        StravaImporter(transport=strava.transport),
        budget_policy=STRAVA_BUDGET_POLICY,
        token_refresher=Refresher(),
        transaction=db.transaction,
        clock=lambda: NOW + timedelta(days=365),
    )

    await the_worker.sweep()

    assert Refresher.calls == 0
    assert db.credentials[USER_ID].expires_at == 0
