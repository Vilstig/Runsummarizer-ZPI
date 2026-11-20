"""The JSON of the activity endpoints, over the real service and Postgres repository,
against a committed fixture. ``UPDATE_GOLDEN=1`` rewrites the fixture."""

import json
import os
from pathlib import Path

import httpx
import pytest

from app.api.deps import get_activity_service, require_user
from app.domain.enums import LapType
from app.main import app
from app.services.activity_service import ActivityService
from tests.db.builders import make_activity, make_lap
from tests.services.fakes import stored_run

pytestmark = pytest.mark.anyio

GOLDEN = Path(__file__).parent / "golden" / "activities_api.json"
ACTIVITIES = "/api/v1/activities"

INTERVAL_LAPS = [
    make_lap(1, duration=330.0, avg_hr=135.0),
    make_lap(2, duration=320.0, avg_hr=138.0),
    make_lap(3, distance=400.0, duration=80.0, avg_hr=172.0),
    make_lap(4, type_id=LapType.RECOVERY, distance=200.0, duration=90.0, avg_hr=140.0),
    make_lap(5, distance=400.0, duration=79.0, avg_hr=174.0),
    make_lap(6, type_id=LapType.RECOVERY, distance=200.0, duration=92.0, avg_hr=142.0),
    make_lap(7, distance=400.0, duration=78.0, avg_hr=176.0),
    make_lap(8, type_id=LapType.REST, distance=10.0, duration=60.0, avg_hr=130.0),
    make_lap(9, duration=335.0, avg_hr=136.0),
]

LAP_UPDATES = {
    "laps": [
        {"lapIndex": 4, "typeId": LapType.REST.value},
        {"lapIndex": 8, "typeId": LapType.RECOVERY.value},
    ]
}


@pytest.fixture
async def client(activity_repo, user_id):
    await activity_repo.save(
        make_activity(
            "strava_intervals",
            user_id=user_id,
            start_time_local="2026-03-05T07:00:00Z",
            laps=INTERVAL_LAPS,
            summary="intervals",
        )
    )
    await activity_repo.save(
        make_activity("strava_easy", user_id=user_id, start_time_local="2026-02-05T07:00:00Z")
    )
    await activity_repo.save(
        make_activity(
            "strava_no_laps",
            user_id=user_id,
            start_time_local="2026-01-05T07:00:00Z",
            laps=[],
            summary="",
        )
    )
    await activity_repo.save(stored_run(42, user_id=user_id, laps=4, summary="from strava"))

    app.dependency_overrides[require_user] = lambda: user_id
    app.dependency_overrides[get_activity_service] = lambda: ActivityService(activity_repo)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(get_activity_service, None)


async def _responses(client: httpx.AsyncClient) -> dict:
    requests = {
        "list": client.get(ACTIVITIES),
        "list_with_laps": client.get(ACTIVITIES, params={"include_laps": "true"}),
        "search": client.post(
            f"{ACTIVITIES}/search",
            json={"distance": {"min": 1000}, "sort": {"by": "distance"}, "limit": 2},
        ),
        "search_segments": client.post(
            f"{ACTIVITIES}/search",
            json={"segments": [{"runTypes": [1], "repDistance": {"value": 400}}]},
        ),
        "get_intervals": client.get(f"{ACTIVITIES}/strava_intervals"),
        "get_strava_run": client.get(f"{ACTIVITIES}/strava_42"),
        "get_no_laps": client.get(f"{ACTIVITIES}/strava_no_laps"),
        "laps_intervals": client.get(f"{ACTIVITIES}/strava_intervals/laps"),
        "patch_intervals": client.patch(f"{ACTIVITIES}/strava_intervals/laps", json=LAP_UPDATES),
        "patch_unknown_lap": client.patch(
            f"{ACTIVITIES}/strava_easy/laps",
            json={"laps": [{"lapIndex": 99, "typeId": 0}]},
        ),
    }
    responses = {}
    for name, request in requests.items():
        response = await request
        responses[name] = {"status": response.status_code, "body": response.json()}
    return responses


async def test_activity_endpoints_match_the_golden_json(client):
    responses = await _responses(client)

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(
            json.dumps(responses, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    assert responses == json.loads(GOLDEN.read_text(encoding="utf-8"))
