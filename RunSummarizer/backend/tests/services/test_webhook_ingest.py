"""ingest_webhook: what each webhook command does to the queue and the user's credentials."""

from datetime import UTC, datetime

import pytest

from app.domain.enums import ImportPriority, ImportSource, ImportStatus, Provider
from app.providers.base import AccountRevoked, ActivityChanged, WebhookCommand
from app.services import webhook_ingest
from tests.services.fakes import FakeImportQueueRepository, stored_run

pytestmark = pytest.mark.anyio

USER_ID = "user-1"
ATHLETE_ID = "101"
UNKNOWN_ATHLETE_ID = "999"
KEY = "strava_7"

NOW = datetime(2026, 10, 11, 12, 7, tzinfo=UTC)


@pytest.fixture(autouse=True)
def connected(db):
    """The user, with their stored Strava tokens."""
    db.add_strava_user(USER_ID, int(ATHLETE_ID), "refresh-1")


async def ingest(db, *commands: WebhookCommand) -> None:
    await webhook_ingest.ingest_webhook(
        Provider.STRAVA, list(commands), transaction=db.transaction, clock=lambda: NOW
    )


# ---------- ActivityChanged ----------


async def test_a_changed_activity_is_queued_at_webhook_priority(db):
    await ingest(db, ActivityChanged(ATHLETE_ID, KEY))

    queued = db.import_item(USER_ID, KEY)
    assert queued.status == ImportStatus.QUEUED
    assert (queued.source, queued.priority) == (ImportSource.WEBHOOK, ImportPriority.WEBHOOK)
    assert queued.run_after == NOW


async def test_what_the_provider_sent_with_the_event_is_queued_with_the_activity(db):
    sent = {"format": "fake_notification_v1", "url": "https://provider.example/file?token=t1"}

    await ingest(db, ActivityChanged(ATHLETE_ID, KEY, sent_data=sent))

    assert db.import_item(USER_ID, KEY).sent_data == sent


async def test_a_later_event_replaces_what_an_earlier_one_sent(db):
    first = {"url": "https://provider.example/file?token=t1"}
    second = {"url": "https://provider.example/file?token=t2"}

    await ingest(db, ActivityChanged(ATHLETE_ID, KEY, sent_data=first))
    await ingest(db, ActivityChanged(ATHLETE_ID, KEY, sent_data=second))

    queued = db.import_item(USER_ID, KEY)
    assert (queued.sent_data, queued.generation) == (second, 1)


async def test_what_the_provider_sent_is_not_logged(db, caplog):
    caplog.set_level("DEBUG")

    await ingest(db, ActivityChanged(ATHLETE_ID, KEY, sent_data={"token": "secret-token"}))

    assert "secret-token" not in caplog.text
    assert "secret-token" not in repr(ActivityChanged(ATHLETE_ID, KEY, {"token": "secret-token"}))


def test_a_command_with_sent_data_stays_hashable():
    command = ActivityChanged(ATHLETE_ID, KEY, sent_data={"url": "https://provider.example/f"})

    assert command in {command}


async def test_a_changed_activity_the_user_has_stored_queues_nothing(db):
    db.activities[KEY] = stored_run(7, user_id=USER_ID)

    await ingest(db, ActivityChanged(ATHLETE_ID, KEY))

    assert db.import_items == {}


async def test_a_database_failure_propagates(db, monkeypatch):
    async def failing_enqueue(self, *args, **kwargs) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(FakeImportQueueRepository, "enqueue_webhook", failing_enqueue)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await ingest(db, ActivityChanged(ATHLETE_ID, KEY))


async def test_a_queued_activity_clears_the_users_pending_sync_request(db):
    db.sync_requests[Provider.STRAVA, USER_ID] = NOW
    db.sync_requests[Provider.STRAVA, "user-2"] = NOW

    await ingest(db, ActivityChanged(ATHLETE_ID, KEY))

    assert db.sync_requests == {(Provider.STRAVA, "user-2"): NOW}


async def test_a_change_to_a_stored_activity_keeps_the_pending_sync_request(db):
    db.sync_requests[Provider.STRAVA, USER_ID] = NOW
    db.activities[KEY] = stored_run(7, user_id=USER_ID)

    await ingest(db, ActivityChanged(ATHLETE_ID, KEY))

    assert db.sync_requests == {(Provider.STRAVA, USER_ID): NOW}


# ---------- AccountRevoked ----------


async def test_a_revocation_clears_the_pending_sync_request(db):
    db.sync_requests[Provider.STRAVA, USER_ID] = NOW

    await ingest(db, AccountRevoked(ATHLETE_ID))

    assert db.sync_requests == {}


async def test_a_revoked_account_clears_only_that_users_credentials(db):
    db.add_strava_user("user-2", 102, "refresh-2")

    await ingest(db, AccountRevoked(ATHLETE_ID))

    assert USER_ID not in db.credentials
    assert "user-2" in db.credentials


async def test_a_revoked_account_leaves_the_users_items_and_activities_alone(db):
    db.queue_item(USER_ID, KEY)
    db.activities["strava_8"] = stored_run(8, user_id=USER_ID)

    await ingest(db, AccountRevoked(ATHLETE_ID))

    assert db.import_item(USER_ID, KEY).status == ImportStatus.QUEUED
    assert "strava_8" in db.activities


# ---------- several commands, and commands that change nothing ----------


async def test_the_commands_of_one_event_are_applied_in_one_transaction(db):
    await ingest(db, ActivityChanged(ATHLETE_ID, KEY), ActivityChanged(ATHLETE_ID, "strava_8"))

    assert db.blocks_opened == 1
    assert db.import_item(USER_ID, KEY) is not None
    assert db.import_item(USER_ID, "strava_8") is not None


@pytest.mark.parametrize(
    "command",
    [ActivityChanged(UNKNOWN_ATHLETE_ID, KEY), AccountRevoked(UNKNOWN_ATHLETE_ID)],
    ids=["activity", "revocation"],
)
async def test_a_command_for_an_account_without_a_user_changes_nothing(db, command):
    await ingest(db, command)

    assert db.import_items == {}
    assert USER_ID in db.credentials


async def test_a_command_for_a_user_who_disconnected_changes_nothing(db):
    del db.credentials[USER_ID]  # linked to the athlete, but not connected

    await ingest(db, ActivityChanged(ATHLETE_ID, KEY), AccountRevoked(ATHLETE_ID))

    assert db.import_items == {}


async def test_a_revoked_account_disconnects_the_user_from_further_events(db):
    await ingest(db, AccountRevoked(ATHLETE_ID))
    await ingest(db, ActivityChanged(ATHLETE_ID, KEY))

    assert db.import_items == {}


async def test_no_commands_open_no_transaction(db):
    await ingest(db)

    assert db.blocks_opened == 0
