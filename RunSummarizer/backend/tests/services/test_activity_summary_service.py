"""ActivityService: editing and resetting an activity's summary, and which calls lock the
activity."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.enums import LapType
from app.domain.errors import ActivityNotFoundError
from app.domain.models import ActivityRecord
from app.services.activity_service import ActivityService
from app.summaries.summary import summarize
from tests.services.fakes import FakeDatabase, stored_run

pytestmark = pytest.mark.anyio

EARLIER = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
KEY = "strava_1"


def generated(record: ActivityRecord) -> ActivityRecord:
    """``record`` with the summary its activity is written into."""
    return replace(record, summary=summarize(record.activity))


def text_edited(record: ActivityRecord) -> ActivityRecord:
    """``generated(record)`` with its text edited by the user."""
    record = generated(record)
    return replace(
        record, summary=replace(record.summary, text="my own words", text_edited_at=EARLIER)
    )


def database(*records: ActivityRecord) -> FakeDatabase:
    db = FakeDatabase()
    for record in records:
        db.activities[record.activity.key] = record
    return db


async def call(db: FakeDatabase, method: str, *args, **kwargs):
    """``ActivityService.<method>(*args, **kwargs)`` in a transaction, at ``NOW``."""
    async with db.transaction() as repos:
        service = ActivityService(repos.activities, clock=lambda: NOW)
        return await getattr(service, method)(*args, **kwargs)


# ---------- edit_summary ----------


async def test_a_text_edit_is_stored_and_flagged():
    record = generated(stored_run(1))
    db = database(record)

    returned = await call(db, "edit_summary", KEY, "my own words", user_id="user-1")

    expected = replace(
        record, summary=replace(record.summary, text="my own words", text_edited_at=NOW)
    )
    assert returned == expected
    assert db.activities[KEY] == expected


async def test_a_text_edit_of_an_activity_that_is_not_found_raises():
    db = database(generated(stored_run(1)))

    with pytest.raises(ActivityNotFoundError):
        await call(db, "edit_summary", "strava_2", "text", user_id="user-1")


async def test_a_text_edit_of_another_users_activity_writes_nothing():
    record = generated(stored_run(1))
    db = database(record)

    with pytest.raises(ActivityNotFoundError):
        await call(db, "edit_summary", KEY, "text", user_id="user-2")
    assert db.activities[KEY] == record


# ---------- reset_summary ----------


async def test_a_reset_writes_the_summary_again_and_clears_its_edit_time():
    record = text_edited(stored_run(1))
    db = database(record)

    returned = await call(db, "reset_summary", KEY, user_id="user-1")

    assert returned == generated(record)
    assert db.activities[KEY] == generated(record)


async def test_a_reset_of_an_activity_that_is_not_found_raises():
    with pytest.raises(ActivityNotFoundError):
        await call(database(), "reset_summary", KEY, user_id="user-1")


# ---------- locking ----------


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("edit_laps", ({2: LapType.REST}, {1: 1100.0})),
        ("reset_laps", ()),
        ("set_segments", (None,)),
        ("edit_summary", ("my own words",)),
        ("reset_summary", ()),
    ],
)
async def test_an_edit_locks_the_activity(method, args):
    db = database(generated(stored_run(1)))

    await call(db, method, KEY, *args, user_id="user-1")

    assert db.activity_locks == [[KEY]]


async def test_a_read_does_not_lock_the_activity():
    db = database(generated(stored_run(1)))

    await call(db, "get_activity", KEY, user_id="user-1")

    assert db.activity_locks == [[]]
