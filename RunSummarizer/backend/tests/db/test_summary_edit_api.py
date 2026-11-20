"""Editing an activity's summary through the API, over the real service and Postgres
repository."""

from dataclasses import replace

import httpx
import pytest

from app.api.deps import get_activity_service, require_user
from app.domain.enums import LapType
from app.main import app
from app.services.activity_service import ActivityService
from app.summaries.summary import summarize
from tests.db.builders import make_activity, make_lap

pytestmark = pytest.mark.anyio

ACTIVITY = "/api/v1/activities/strava_1"


@pytest.fixture
async def client(activity_repo, user_id):
    record = make_activity(
        "strava_1", user_id=user_id, laps=[make_lap(1), make_lap(2), make_lap(3)]
    )
    await activity_repo.save(replace(record, summary=summarize(record.activity)))
    await activity_repo.save(make_activity("strava_2", user_id=user_id, summary="5 km easy"))

    app.dependency_overrides[require_user] = lambda: user_id
    app.dependency_overrides[get_activity_service] = lambda: ActivityService(activity_repo)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(get_activity_service, None)


async def test_an_edited_summary_survives_a_lap_edit_until_it_is_reset(client, activity_repo):
    text_edit = await client.patch(f"{ACTIVITY}/summary", json={"text": "my own words"})
    lap_edit = await client.patch(
        f"{ACTIVITY}/laps",
        json={"laps": [{"lapIndex": 2, "typeId": LapType.REST.value}], "textPolicy": "keep"},
    )
    reset = await client.post(f"{ACTIVITY}/summary/reset")

    assert text_edit.json()["summary"] == "my own words"
    assert text_edit.json()["summaryTextEdited"] is True
    assert lap_edit.json()["processed_data"]["laps"][1]["typeId"] == LapType.REST.value
    assert lap_edit.json()["summary"] == "my own words"
    stored = await activity_repo.get_by_id("strava_1")
    assert reset.json()["summary"] == summarize(stored.activity).text
    assert reset.json()["summaryTextEdited"] is False


async def test_the_segment_stats_follow_a_lap_edit_that_keeps_the_text(client, activity_repo):
    await client.patch(f"{ACTIVITY}/summary", json={"text": "my own words"})
    before = await activity_repo.get_by_id("strava_1")

    lap_edit = await client.patch(
        f"{ACTIVITY}/laps",
        json={"laps": [{"lapIndex": 2, "distance": 1200}], "textPolicy": "keep"},
    )

    after = await activity_repo.get_by_id("strava_1")
    assert lap_edit.json()["summary"] == "my own words"
    assert [segment.stats.distance for segment in before.activity.segments] == [3000]
    assert [segment.stats.distance for segment in after.activity.segments] == [3200]
