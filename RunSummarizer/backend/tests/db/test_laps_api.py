"""Editing and resetting an activity's lap distances through the API, over the real service
and Postgres repository."""

from dataclasses import replace

import httpx
import pytest

from app.api.deps import get_activity_service, require_user
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

    app.dependency_overrides[require_user] = lambda: user_id
    app.dependency_overrides[get_activity_service] = lambda: ActivityService(activity_repo)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(get_activity_service, None)


def laps_of(body: dict) -> list[tuple]:
    """(lapIndex, distance, version) of each lap of an activity response."""
    return [
        (lap["lapIndex"], lap["distance"], lap["version"]) for lap in body["processed_data"]["laps"]
    ]


async def test_lap_distances_are_edited_and_reset(client):
    imported = (await client.get(ACTIVITY)).json()

    edit = await client.patch(
        f"{ACTIVITY}/laps",
        json={"laps": [{"lapIndex": 2, "distance": 1500}, {"lapIndex": 3, "distance": 1200}]},
    )
    partial_reset = await client.post(f"{ACTIVITY}/laps/reset", json={"lapIndexes": [3]})
    full_reset = await client.post(f"{ACTIVITY}/laps/reset", json={})

    assert laps_of(imported) == [(1, 1000.0, 0), (2, 1000.0, 0), (3, 1000.0, 0)]

    assert edit.status_code == 200
    assert laps_of(edit.json()) == [(1, 1000.0, 0), (2, 1500.0, 1), (3, 1200.0, 1)]
    assert edit.json()["processed_data"]["laps"][1]["speed"] == 1500.0 / 257.0
    assert edit.json()["summary"] != imported["summary"]
    assert edit.json()["processed_data"]["distance"] == imported["processed_data"]["distance"]

    assert laps_of(partial_reset.json()) == [(1, 1000.0, 0), (2, 1500.0, 1), (3, 1000.0, 0)]
    assert partial_reset.json()["summary"] not in (imported["summary"], edit.json()["summary"])

    assert full_reset.json() == imported
    assert (await client.get(ACTIVITY)).json() == imported


async def test_edited_summary_text_needs_a_policy_for_a_lap_edit(client):
    await client.patch(f"{ACTIVITY}/summary", json={"text": "my own words"})
    distance = {"laps": [{"lapIndex": 2, "distance": 1500}]}

    refused = await client.patch(f"{ACTIVITY}/laps", json=distance)
    kept = await client.patch(f"{ACTIVITY}/laps", json={**distance, "textPolicy": "keep"})
    reset_refused = await client.post(f"{ACTIVITY}/laps/reset", json={})
    regenerated = await client.post(f"{ACTIVITY}/laps/reset", json={"textPolicy": "regenerate"})

    assert refused.status_code == 409
    assert refused.json()["code"] == "text_policy_required"
    assert isinstance(refused.json()["detail"], str)
    assert laps_of(kept.json())[1] == (2, 1500.0, 1)
    assert kept.json()["summary"] == "my own words"
    assert reset_refused.status_code == 409
    assert regenerated.json()["summaryTextEdited"] is False
    assert laps_of(regenerated.json())[1] == (2, 1000.0, 0)


async def test_an_unknown_lap_is_a_400_and_writes_nothing(client):
    before = (await client.get(ACTIVITY)).json()

    edit = await client.patch(
        f"{ACTIVITY}/laps",
        json={"laps": [{"lapIndex": 2, "distance": 1500}, {"lapIndex": 9, "distance": 900}]},
    )
    reset = await client.post(f"{ACTIVITY}/laps/reset", json={"lapIndexes": [9]})

    assert edit.status_code == 400
    assert edit.json() == {"detail": "Unknown lapIndex: 9", "code": "unknown_lap"}
    assert reset.status_code == 400
    assert (await client.get(ACTIVITY)).json() == before
