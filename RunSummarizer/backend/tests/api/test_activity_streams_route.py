"""GET /api/v1/activities/{id}/streams with its keys query parameter."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service, require_user
from app.domain.enums import StreamType
from app.domain.errors import ActivityNotFoundError
from app.main import app

ACTIVITY = "/api/v1/activities/strava_7"
USER_ID = "user-1"


class FakeActivityService:
    """Stands in for ``ActivityService``: records the keyword arguments of each call."""

    def __init__(self):
        self.calls: list[dict] = []
        self.streams: dict | None = {}  # what get_activity_streams returns

    async def get_activity_streams(self, activity_id: str, **kwargs) -> dict | None:
        self.calls.append({"activity_id": activity_id, **kwargs})
        if self.streams is None:
            raise ActivityNotFoundError("Activity not found")
        return self.streams


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


def get_streams(**params) -> httpx.Response:
    return TestClient(app).get(f"{ACTIVITY}/streams", params=params)


def test_every_stream_is_requested_without_keys(service):
    service.streams = {
        "time": [0, 1],
        "distance": None,
        "heartrate": [140, 141],
        "velocity": None,
        "altitude": None,
    }

    response = get_streams()

    assert response.status_code == 200
    assert response.json() == service.streams
    assert service.calls == [
        {"activity_id": "strava_7", "user_id": USER_ID, "stream_types": tuple(StreamType)}
    ]


def test_only_the_requested_streams_are_returned_with_missing_ones_null(service):
    service.streams = {"heartrate": None, "time": [0, 1]}

    response = get_streams(keys="heartrate,time")

    assert response.status_code == 200
    assert response.json() == {"time": [0, 1], "heartrate": None}
    assert service.calls[0]["stream_types"] == (StreamType.HEARTRATE, StreamType.TIME)


def test_a_single_key_is_passed_to_the_service(service):
    service.streams = {"heartrate": [140, 141]}

    response = get_streams(keys="heartrate")

    assert response.status_code == 200
    assert response.json() == {"heartrate": [140, 141]}
    assert service.calls[0]["stream_types"] == (StreamType.HEARTRATE,)


def test_streams_not_returned_by_the_service_are_left_out(service):
    service.streams = {"time": [0, 1]}

    response = get_streams(keys="time,heartrate")

    assert response.status_code == 200
    assert response.json() == {"time": [0, 1]}
    assert "heartrate" not in response.json()


def test_keys_are_trimmed_and_named_once(service):
    get_streams(keys="time, heartrate,time,")

    assert service.calls[0]["stream_types"] == (StreamType.TIME, StreamType.HEARTRATE)


def test_an_unknown_stream_is_rejected(service):
    response = get_streams(keys="time,cadence")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert any("cadence" in item.get("msg", "") for item in body["detail"])
    assert service.calls == []


@pytest.mark.parametrize("keys", ["", ",", " , "])
def test_keys_naming_no_stream_are_rejected(service, keys):
    response = get_streams(keys=keys)

    assert response.status_code == 422
    assert service.calls == []


def test_streams_of_an_activity_that_is_not_found_are_a_404(service):
    service.streams = None

    response = get_streams()

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}


def test_keys_are_documented_as_a_comma_separated_array_of_streams():
    operation = app.openapi()["paths"]["/api/v1/activities/{activity_id}/streams"]["get"]

    [keys] = [parameter for parameter in operation["parameters"] if parameter["name"] == "keys"]
    assert keys["in"] == "query"
    assert (keys["style"], keys["explode"]) == ("form", False)
    assert keys["schema"] == {
        "type": "array",
        "items": {
            "type": "string",
            "enum": ["time", "distance", "heartrate", "velocity", "altitude"],
        },
    }
