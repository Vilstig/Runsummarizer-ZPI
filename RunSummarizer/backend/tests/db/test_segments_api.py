"""Setting an activity's segments through the API, over the real service and Postgres
repository."""

from dataclasses import replace

import httpx
import pytest

from app.api.deps import get_activity_service, require_user
from app.domain.enums import LapType
from app.main import app
from app.services.activity_service import ActivityService
from app.summaries.summary import summarize
from tests.db.builders import make_activity, make_lap, make_run

pytestmark = pytest.mark.anyio

ACTIVITY = "/api/v1/activities/strava_1"

LAPS = [
    make_lap(1, duration=330.0, avg_hr=135.0),
    make_lap(2, duration=325.0, avg_hr=137.0),
    make_lap(3, distance=400.0, duration=80.0, avg_hr=172.0),
    make_lap(4, type_id=LapType.RECOVERY, distance=200.0, duration=90.0, avg_hr=140.0),
    make_lap(5, distance=400.0, duration=79.0, avg_hr=174.0),
    make_lap(6, type_id=LapType.RECOVERY, distance=200.0, duration=92.0, avg_hr=142.0),
    make_lap(7, distance=400.0, duration=78.0, avg_hr=176.0),
    make_lap(8, duration=335.0, avg_hr=136.0),
]
USER_SEGMENTS = [
    {"startLapIndex": 1, "role": "preamble", "runTypeId": None},
    {"startLapIndex": 5, "role": "work", "runTypeId": None},
    {"startLapIndex": 8, "role": "epilogue", "runTypeId": None},
]


@pytest.fixture
async def client(activity_repo, user_id):
    record = make_activity("strava_1", user_id=user_id, laps=LAPS)
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


def outline(body: dict) -> list[tuple]:
    """(start, end, role, label) of each segment of an activity response."""
    return [
        (segment["startLapIndex"], segment["endLapIndex"], segment["role"], segment["label"])
        for segment in body["processed_data"]["segments"]
    ]


async def test_the_users_segments_last_through_lap_edits_and_resets(client):
    automatic = (await client.get(ACTIVITY)).json()

    refused = await client.put(
        f"{ACTIVITY}/segments", json={"segments": [{"startLapIndex": 2, "role": "work"}]}
    )
    put = await client.put(f"{ACTIVITY}/segments", json={"segments": USER_SEGMENTS})
    lap_edit = await client.patch(
        f"{ACTIVITY}/laps", json={"laps": [{"lapIndex": 6, "typeId": LapType.RUN.value}]}
    )
    text_edit = await client.patch(f"{ACTIVITY}/summary", json={"text": "my own words"})
    reset = await client.post(f"{ACTIVITY}/summary/reset")
    await client.patch(f"{ACTIVITY}/summary", json={"text": "my own words"})
    needs_policy = await client.put(f"{ACTIVITY}/segments", json={"segments": None})
    back = await client.put(
        f"{ACTIVITY}/segments", json={"segments": None, "textPolicy": "regenerate"}
    )

    assert automatic["segmentsEdited"] is False
    assert outline(automatic)[0] == (1, 2, "preamble", "Rozgrzewka")

    assert refused.status_code == 400
    assert refused.json()["code"] == "invalid_segmentation"
    assert isinstance(refused.json()["detail"], str)

    assert put.status_code == 200
    assert put.json()["segmentsEdited"] is True
    assert outline(put.json()) == [
        (1, 4, "preamble", "Rozgrzewka"),
        (5, 7, "work", "Interwały"),
        (8, 8, "epilogue", "Schłodzenie"),
    ]
    assert put.json()["summary"].startswith("Rozgrzewka:\n")

    assert lap_edit.json()["segmentsEdited"] is True
    assert outline(lap_edit.json()) == [
        (1, 4, "preamble", "Rozgrzewka"),
        (5, 7, "work", None),
        (8, 8, "epilogue", "Schłodzenie"),
    ]

    assert text_edit.json()["segmentsEdited"] is True
    assert reset.json()["segmentsEdited"] is True
    assert reset.json()["summary"] == lap_edit.json()["summary"]

    assert needs_policy.status_code == 409
    assert needs_policy.json()["code"] == "text_policy_required"
    assert isinstance(needs_policy.json()["detail"], str)

    assert back.status_code == 200
    assert back.json()["segmentsEdited"] is False
    assert back.json()["summaryTextEdited"] is False
    edited_laps = [replace(lap, type=LapType.RUN) if lap.index == 6 else lap for lap in LAPS]
    assert outline(back.json()) == [
        (segment.start_lap_index, segment.end_lap_index, segment.role.value, segment.label)
        for segment in make_run("strava_1", laps=edited_laps).segments
    ]
