"""GET /api/v1/activities, GET /api/v1/activities/{id}, and DELETE /api/v1/activities/{id}."""

from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service, require_user
from app.domain.errors import ActivityNotFoundError
from app.domain.models import ActivityRecord
from app.main import app
from tests.db.builders import make_activity

ACTIVITIES = "/api/v1/activities"
ACTIVITY = f"{ACTIVITIES}/strava_7"
USER_ID = "user-1"

RECORD = make_activity("strava_7", user_id=USER_ID)


class FakeActivityService:
    """Stands in for ``ActivityService``: records each call and answers from its fields."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.records: list[ActivityRecord] = []
        self.record: ActivityRecord | None = RECORD
        self.deleted = True

    async def list_activities(self, **kwargs) -> list[ActivityRecord]:
        self.calls.append(("list_activities", (), kwargs))
        return self.records

    async def get_activity(self, *args, **kwargs) -> ActivityRecord | None:
        self.calls.append(("get_activity", args, kwargs))
        if self.record is None:
            raise ActivityNotFoundError("Activity not found")
        return self.record

    async def delete_activity(self, *args, **kwargs) -> bool:
        self.calls.append(("delete_activity", args, kwargs))
        if not self.deleted:
            raise ActivityNotFoundError("Activity not found")
        return self.deleted


@pytest.fixture(autouse=True)
def current_user():
    app.dependency_overrides[require_user] = lambda: USER_ID
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def service():
    fake = FakeActivityService()
    app.dependency_overrides[get_activity_service] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_activity_service, None)


def get_activities(**params) -> httpx.Response:
    return TestClient(app).get(ACTIVITIES, params=params)


def list_call(service) -> dict:
    return service.calls[0][2]


# ---------- GET /activities ----------


def test_include_laps_is_passed_to_the_service(service):
    response = get_activities(include_laps="true")

    assert response.status_code == 200
    assert list_call(service)["include_laps"] is True


def test_the_list_defaults_and_the_user_reach_the_service(service):
    get_activities()

    assert list_call(service) == {
        "limit": 50,
        "skip": 0,
        "source": None,
        "include_laps": False,
        "after": None,
        "before": None,
        "user_id": USER_ID,
    }


def test_limit_skip_and_source_are_passed_to_the_service(service):
    response = get_activities(limit=20, skip=10, source="strava")

    assert response.status_code == 200
    call = list_call(service)
    assert (call["limit"], call["skip"], call["source"]) == (20, 10, "strava")


def test_the_date_window_is_passed_to_the_service(service):
    response = get_activities(after="2026-10-01", before="2026-11-01")

    assert response.status_code == 200
    assert list_call(service)["after"] == date(2026, 10, 1)
    assert list_call(service)["before"] == date(2026, 11, 1)


def test_either_bound_may_be_given_alone(service):
    get_activities(after="2026-10-01")
    get_activities(before="2026-11-01")

    assert (service.calls[0][2]["after"], service.calls[0][2]["before"]) == (
        date(2026, 10, 1),
        None,
    )
    assert (service.calls[1][2]["after"], service.calls[1][2]["before"]) == (
        None,
        date(2026, 11, 1),
    )


@pytest.mark.parametrize(
    ("after", "before"),
    [("2026-11-01", "2026-10-01"), ("2026-10-01", "2026-10-01")],
)
def test_a_window_that_does_not_start_before_it_ends_is_rejected(service, after, before):
    response = get_activities(after=after, before=before)

    assert response.status_code == 422
    assert service.calls == []


def test_an_invalid_date_is_rejected(service):
    response = get_activities(after="2026-13-01")

    assert response.status_code == 422
    assert service.calls == []


def test_a_non_boolean_include_laps_is_rejected(service):
    response = get_activities(include_laps="maybe")

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"limit": 0}, id="limit too small"),
        pytest.param({"limit": 201}, id="limit too large"),
        pytest.param({"skip": -1}, id="negative skip"),
        pytest.param({"source": "polar"}, id="unknown source"),
    ],
)
def test_an_invalid_list_query_is_rejected(service, params):
    response = get_activities(**params)

    assert response.status_code == 422
    assert service.calls == []


def test_the_listed_activities_come_back(service):
    service.records = [RECORD]

    response = get_activities()

    assert response.status_code == 200
    assert [item["activityId"] for item in response.json()] == ["strava_7"]


# ---------- GET /activities/{id} ----------


def test_an_activity_is_returned(service):
    response = TestClient(app).get(ACTIVITY)

    assert response.status_code == 200
    assert response.json()["activityId"] == "strava_7"
    assert service.calls == [("get_activity", ("strava_7",), {"user_id": USER_ID})]


def test_an_activity_names_its_recording_device(service):
    service.record = make_activity("garmin_9", user_id=USER_ID, source="garmin")
    service.record.activity.device_name = "Forerunner 965"

    response = TestClient(app).get(f"{ACTIVITIES}/garmin_9")

    assert response.json()["processed_data"]["deviceName"] == "Forerunner 965"


def test_an_activity_without_a_known_device_has_a_null_device_name(service):
    response = TestClient(app).get(ACTIVITY)

    assert response.json()["processed_data"]["deviceName"] is None


def test_an_activity_that_is_not_found_is_a_404(service):
    service.record = None

    response = TestClient(app).get(ACTIVITY)

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}


# ---------- DELETE /activities/{id} ----------


def test_a_deleted_activity_is_a_204(service):
    response = TestClient(app).delete(ACTIVITY)

    assert response.status_code == 204
    assert service.calls == [("delete_activity", ("strava_7",), {"user_id": USER_ID})]


def test_deleting_an_activity_that_is_not_found_is_a_404(service):
    service.deleted = False

    response = TestClient(app).delete(ACTIVITY)

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}
