"""Concurrent edits of one activity through ``ActivityService`` over Postgres: each runs
in a transaction of its own, and both edits are in the stored record."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.enums import LapType
from app.services.activity_service import ActivityService
from app.summaries.editing import TextPolicy
from app.summaries.segmentation import relabel_laps
from app.summaries.summary import summarize
from tests.db.builders import make_activity, make_lap
from tests.db.conftest import until_a_query_waits_for_a_lock

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
KEY = "strava_1"
REST_LAP = {2: LapType.REST}


def text_edit(service: ActivityService, user_id: str):
    return service.edit_summary(KEY, "my own words", user_id=user_id)


def lap_edit(service: ActivityService, user_id: str):
    return service.edit_laps(KEY, REST_LAP, {}, text_policy=TextPolicy.KEEP, user_id=user_id)


@pytest.mark.parametrize(
    ("first_edit", "second_edit"), [(lap_edit, text_edit), (text_edit, lap_edit)]
)
async def test_two_concurrent_edits_both_survive(
    committed_engine, committed_transaction, committed_user_id, first_edit, second_edit
):
    record = make_activity(
        KEY, user_id=committed_user_id, laps=[make_lap(1), make_lap(2), make_lap(3)]
    )
    async with committed_transaction() as repos:
        await repos.activities.save(replace(record, summary=summarize(record.activity)))

    async def edit_in_another_transaction() -> None:
        async with committed_transaction() as repos:
            await second_edit(
                ActivityService(repos.activities, clock=lambda: NOW), committed_user_id
            )

    async with committed_transaction() as first:
        await first_edit(ActivityService(first.activities, clock=lambda: NOW), committed_user_id)
        second = asyncio.create_task(edit_in_another_transaction())
        await until_a_query_waits_for_a_lock(committed_engine)
        assert not second.done()

    await asyncio.wait_for(second, timeout=5)

    async with committed_transaction() as repos:
        stored = await repos.activities.get_by_id(KEY, user_id=committed_user_id)
    relabelled = relabel_laps(record.activity, REST_LAP)
    # the summary segments are those of the laps the text edit read
    summarized = relabelled if first_edit is lap_edit else record.activity
    assert stored.activity.laps == relabelled.laps
    assert stored.summary == replace(summarize(summarized), text="my own words", text_edited_at=NOW)
