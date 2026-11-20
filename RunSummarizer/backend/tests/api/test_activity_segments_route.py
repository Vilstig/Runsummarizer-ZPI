"""PUT /api/v1/activities/{id}/segments, and how an activity response shows the user's
segments."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service, require_user
from app.domain.enums import RunType, SegmentRole
from app.domain.errors import (
    ActivityNotFoundError,
    InvalidSegmentationError,
    TextPolicyRequiredError,
)
from app.domain.models import ActivityRecord, UserSegment
from app.main import app
from app.summaries.editing import TextPolicy
from tests.db.builders import make_activity, make_lap

ACTIVITY = "/api/v1/activities/strava_7"
USER_ID = "user-1"

LAPS = [make_lap(index) for index in range(1, 6)]
USER_SEGMENTS = (
    UserSegment(1, SegmentRole.PREAMBLE),
    UserSegment(3, SegmentRole.WORK, RunType.TEMPO),
    UserSegment(5, SegmentRole.BREAK),
)
USER_SEGMENTS_JSON = [
    {"startLapIndex": 1, "role": "preamble", "runTypeId": None},
    {"startLapIndex": 3, "role": "work", "runTypeId": 3},
    {"startLapIndex": 5, "role": "break", "runTypeId": None},
]
RECORD = make_activity("strava_7", user_id=USER_ID, laps=LAPS, user_segments=USER_SEGMENTS)


class FakeActivityService:
    """Stands in for ``ActivityService``: records each call and answers with ``record``,
    or raises ``error``."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.record: ActivityRecord | None = RECORD
        self.error: Exception | None = None

    async def set_segments(self, *args, **kwargs) -> ActivityRecord | None:
        return self._answer("set_segments", args, kwargs)

    async def get_activity(self, *args, **kwargs) -> ActivityRecord | None:
        return self._answer("get_activity", args, kwargs)

    def _answer(self, name: str, args: tuple, kwargs: dict) -> ActivityRecord | None:
        self.calls.append((name, args, kwargs))
        if self.error is not None:
            raise self.error
        if self.record is None:
            raise ActivityNotFoundError("Activity not found")
        return self.record


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


def put_segments(body: dict) -> httpx.Response:
    return TestClient(app).put(f"{ACTIVITY}/segments", json=body)


# ---------- PUT /segments ----------


def test_the_segments_are_passed_to_the_service(service):
    response = put_segments({"segments": USER_SEGMENTS_JSON, "textPolicy": "keep"})

    assert response.status_code == 200
    assert service.calls == [
        (
            "set_segments",
            ("strava_7", USER_SEGMENTS),
            {"text_policy": TextPolicy.KEEP, "user_id": USER_ID},
        )
    ]


def test_null_segments_go_back_to_automatic_segments(service):
    response = put_segments({"segments": None})

    assert response.status_code == 200
    assert service.calls == [
        ("set_segments", ("strava_7", None), {"text_policy": None, "user_id": USER_ID})
    ]


def test_empty_segments_are_passed_to_the_service(service):
    response = put_segments({"segments": []})

    assert response.status_code == 200
    assert service.calls == [
        ("set_segments", ("strava_7", ()), {"text_policy": None, "user_id": USER_ID})
    ]


def test_a_regenerate_policy_is_passed_to_the_service(service):
    put_segments({"segments": USER_SEGMENTS_JSON, "textPolicy": "regenerate"})

    assert service.calls == [
        (
            "set_segments",
            ("strava_7", USER_SEGMENTS),
            {"text_policy": TextPolicy.REGENERATE, "user_id": USER_ID},
        )
    ]


def test_a_segment_without_a_run_type_is_classified(service):
    put_segments({"segments": [{"startLapIndex": 1, "role": "work"}]})

    assert service.calls[0][1] == ("strava_7", (UserSegment(1, SegmentRole.WORK, None),))


def test_the_response_is_the_resegmented_activity(service):
    body = put_segments({"segments": USER_SEGMENTS_JSON}).json()

    assert body["segmentsEdited"] is True
    assert [segment["startLapIndex"] for segment in body["processed_data"]["segments"]] == [
        1,
        3,
        5,
    ]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no segments field"),
        pytest.param({"segments": [{"role": "work"}]}, id="no start lap"),
        pytest.param({"segments": [{"startLapIndex": 1}]}, id="no role"),
        pytest.param({"segments": [{"startLapIndex": 1, "role": "middle"}]}, id="unknown role"),
        pytest.param(
            {"segments": [{"startLapIndex": 1, "role": "work", "runTypeId": 99}]},
            id="unknown run type",
        ),
        pytest.param({"segments": None, "textPolicy": "merge"}, id="unknown text policy"),
    ],
)
def test_a_malformed_body_is_rejected(service, body):
    response = put_segments(body)

    assert response.status_code == 422
    assert service.calls == []


def test_segments_of_an_activity_that_is_not_found_are_a_404(service):
    service.record = None

    response = put_segments({"segments": USER_SEGMENTS_JSON})

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (
            InvalidSegmentationError("Segment 1: the activity has no lap 9"),
            400,
            "invalid_segmentation",
        ),
        (TextPolicyRequiredError("text edited"), 409, "text_policy_required"),
    ],
)
def test_a_refused_segmentation_answers_with_its_code(service, error, status, code):
    service.error = error

    response = put_segments({"segments": USER_SEGMENTS_JSON})

    assert response.status_code == status
    assert response.json() == {"detail": str(error), "code": code}


def test_the_error_responses_are_documented():
    responses = app.openapi()["paths"]["/api/v1/activities/{activity_id}/segments"]["put"][
        "responses"
    ]

    assert {"200", "400", "404", "409", "422"} <= set(responses)


# ---------- response ----------


def test_an_activity_with_the_users_segments_says_which_run_types_are_worked_out(service):
    body = TestClient(app).get(ACTIVITY).json()

    assert body["segmentsEdited"] is True
    assert [
        (segment["startLapIndex"], segment["runTypeAuto"])
        for segment in body["processed_data"]["segments"]
    ] == [(1, True), (3, False), (5, True)]


def test_an_automatically_segmented_activity_has_every_run_type_worked_out(service):
    service.record = make_activity("strava_7", user_id=USER_ID, laps=LAPS)

    body = TestClient(app).get(ACTIVITY).json()

    assert body["segmentsEdited"] is False
    assert all(segment["runTypeAuto"] for segment in body["processed_data"]["segments"])
