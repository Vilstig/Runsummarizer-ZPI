"""GET /api/v1/activities/{id}/laps, PATCH /api/v1/activities/{id}/laps,
POST /api/v1/activities/{id}/laps/reset, and the lap versions of an activity response."""

from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service, require_user
from app.api.schemas.activities import (
    EDIT_LAPS_EXAMPLES,
    RESET_LAPS_EXAMPLES,
    TEXT_POLICY_DESCRIPTION,
    EditLapsRequest,
    ResetLapsRequest,
)
from app.domain.enums import LapType
from app.domain.errors import (
    ActivityNotFoundError,
    TextPolicyRequiredError,
    UnknownLapError,
)
from app.domain.models import ActivityRecord, Lap
from app.main import app
from app.summaries.editing import TextPolicy
from tests.db.builders import make_activity, make_lap

ACTIVITY = "/api/v1/activities/strava_7"
USER_ID = "user-1"

RECORD = make_activity(
    "strava_7",
    user_id=USER_ID,
    laps=[make_lap(1), replace(make_lap(2, distance=1100.0), version=1), make_lap(3)],
)


class FakeActivityService:
    """Stands in for ``ActivityService``: records each call and answers with ``record`` /
    ``laps``, or raises ``error``."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.record: ActivityRecord | None = RECORD
        self.laps: list[Lap] | None = list(RECORD.activity.laps)
        self.error: Exception | None = None

    async def get_activity_laps(self, *args, **kwargs) -> list[Lap]:
        self.calls.append(("get_activity_laps", args, kwargs))
        if self.laps is None:
            raise ActivityNotFoundError("Activity not found")
        return self.laps

    async def edit_laps(self, *args, **kwargs) -> ActivityRecord:
        return self._answer("edit_laps", args, kwargs)

    async def reset_laps(self, *args, **kwargs) -> ActivityRecord:
        return self._answer("reset_laps", args, kwargs)

    def _answer(self, name: str, args: tuple, kwargs: dict) -> ActivityRecord:
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


def patch_laps(body: dict) -> httpx.Response:
    return TestClient(app).patch(f"{ACTIVITY}/laps", json=body)


def reset_laps(body: dict | None) -> httpx.Response:
    return TestClient(app).post(f"{ACTIVITY}/laps/reset", json=body)


def operation(path: str, method: str) -> dict:
    return app.openapi()["paths"][f"/api/v1/activities/{{activity_id}}{path}"][method]


# ---------- GET /laps ----------


def test_the_laps_are_returned(service):
    response = TestClient(app).get(f"{ACTIVITY}/laps")

    assert response.status_code == 200
    assert [(lap["lapIndex"], lap["distance"], lap["version"]) for lap in response.json()] == [
        (1, 1000.0, 0),
        (2, 1100.0, 1),
        (3, 1000.0, 0),
    ]
    assert service.calls == [("get_activity_laps", ("strava_7",), {"user_id": USER_ID})]


def test_laps_of_an_activity_that_is_not_found_are_a_404(service):
    service.laps = None

    response = TestClient(app).get(f"{ACTIVITY}/laps")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}


# ---------- PATCH /laps ----------


def test_a_type_edit_is_passed_to_the_service(service):
    response = patch_laps({"laps": [{"lapIndex": 2, "typeId": LapType.REST.value}]})

    assert response.status_code == 200
    assert service.calls == [
        (
            "edit_laps",
            ("strava_7", {2: LapType.REST}, {}),
            {"text_policy": None, "user_id": USER_ID},
        )
    ]


def test_types_distances_and_the_policy_are_passed_to_the_service(service):
    body = {
        "laps": [
            {"lapIndex": 1, "distance": 950.5},
            {"lapIndex": 2, "typeId": LapType.REST.value, "distance": 1100},
        ],
        "textPolicy": "keep",
    }

    patch_laps(body)

    assert service.calls == [
        (
            "edit_laps",
            ("strava_7", {2: LapType.REST}, {1: 950.5, 2: 1100.0}),
            {"text_policy": TextPolicy.KEEP, "user_id": USER_ID},
        )
    ]


def test_a_distance_of_50_km_is_taken(service):
    assert patch_laps({"laps": [{"lapIndex": 1, "distance": 50_000}]}).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"laps": [{"lapIndex": 1}]}, id="neither type nor distance"),
        pytest.param({"laps": [{"lapIndex": 1, "typeId": None}]}, id="null type"),
        pytest.param(
            {"laps": [{"lapIndex": 1, "typeId": 0}, {"lapIndex": 1, "distance": 900}]},
            id="a lap twice",
        ),
        pytest.param({"laps": []}, id="no laps"),
        pytest.param({}, id="no laps field"),
        pytest.param({"laps": [{"lapIndex": 1, "distance": 0}]}, id="distance 0"),
        pytest.param({"laps": [{"lapIndex": 1, "distance": -5}]}, id="negative distance"),
        pytest.param({"laps": [{"lapIndex": 1, "distance": 50_001}]}, id="over 50 km"),
        pytest.param({"laps": [{"lapIndex": 1, "distance": "far"}]}, id="text distance"),
        pytest.param({"laps": [{"lapIndex": 1, "typeId": 99}]}, id="unknown type"),
        pytest.param({"laps": [{"lapIndex": 1, "speed": 4.0}]}, id="another lap value"),
        pytest.param(
            {"laps": [{"lapIndex": 1, "typeId": 0}], "regenerateSummary": True},
            id="regenerateSummary",
        ),
        pytest.param({"laps": [{"lapIndex": 1, "typeId": 0}], "textPolicy": "maybe"}, id="policy"),
    ],
)
def test_a_malformed_lap_edit_is_rejected(service, body):
    response = patch_laps(body)

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_distance_that_is_not_finite_is_rejected(service, value):
    response = TestClient(app).patch(
        f"{ACTIVITY}/laps",
        content=f'{{"laps": [{{"lapIndex": 1, "distance": {value}}}]}}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert [error["type"] for error in response.json()["detail"]] == ["finite_number"]
    assert service.calls == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"laps": [{"lapIndex": 4}]}, "Lap 4: send 'typeId' or 'distance'"),
        (
            {"laps": [{"lapIndex": 4, "typeId": 0}, {"lapIndex": 4, "typeId": 1}]},
            "Send each lap once; lap 4 came more than once",
        ),
    ],
)
def test_a_lap_edit_without_changes_says_what_to_send(service, body, message):
    [error] = patch_laps(body).json()["detail"]

    assert error["msg"] == f"Value error, {message}"


# ---------- POST /laps/reset ----------


def test_a_reset_needs_a_body(service):
    assert reset_laps(None).status_code == 422
    assert service.calls == []


def test_a_policy_alone_resets_every_lap(service):
    reset_laps({"textPolicy": "keep"})

    assert service.calls == [
        ("reset_laps", ("strava_7", None), {"text_policy": TextPolicy.KEEP, "user_id": USER_ID})
    ]


def test_an_empty_body_resets_every_lap(service):
    reset_laps({})

    assert service.calls == [
        ("reset_laps", ("strava_7", None), {"text_policy": None, "user_id": USER_ID})
    ]


def test_the_laps_and_policy_of_a_reset_are_passed_to_the_service(service):
    reset_laps({"lapIndexes": [2, 3], "textPolicy": "regenerate"})

    assert service.calls == [
        (
            "reset_laps",
            ("strava_7", [2, 3]),
            {"text_policy": TextPolicy.REGENERATE, "user_id": USER_ID},
        )
    ]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"lapIndexes": []}, id="no laps"),
        pytest.param({"lapIndexes": ["two"]}, id="a lap that is not an index"),
        pytest.param({"lapIndexes": [2], "textPolicy": "maybe"}, id="unknown policy"),
        pytest.param({"laps": [2]}, id="a misspelt field"),
    ],
)
def test_a_malformed_reset_is_rejected(service, body):
    assert reset_laps(body).status_code == 422
    assert service.calls == []


# ---------- refusals ----------

EDITS = [
    pytest.param(lambda: patch_laps({"laps": [{"lapIndex": 9, "distance": 900}]}), id="edit"),
    pytest.param(lambda: reset_laps({"lapIndexes": [9]}), id="reset"),
]


@pytest.mark.parametrize("send", EDITS)
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (UnknownLapError("Unknown lapIndex: 9"), 400, "unknown_lap"),
        (TextPolicyRequiredError("text edited"), 409, "text_policy_required"),
    ],
)
def test_a_refused_lap_change_answers_with_its_code(service, send, error, status, code):
    service.error = error

    response = send()

    assert response.status_code == status
    assert response.json() == {"detail": str(error), "code": code}


@pytest.mark.parametrize("send", EDITS)
def test_a_lap_change_of_an_activity_that_is_not_found_is_a_404(service, send):
    service.record = None

    response = send()

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}


@pytest.mark.parametrize(("path", "method"), [("/laps", "patch"), ("/laps/reset", "post")])
def test_the_error_responses_are_documented(path, method):
    assert {"200", "400", "404", "409", "422"} <= set(operation(path, method)["responses"])


@pytest.mark.parametrize(
    ("path", "method", "model", "examples"),
    [
        ("/laps", "patch", EditLapsRequest, EDIT_LAPS_EXAMPLES),
        ("/laps/reset", "post", ResetLapsRequest, RESET_LAPS_EXAMPLES),
    ],
)
def test_the_request_examples_are_documented_and_valid(path, method, model, examples):
    documented = operation(path, method)["requestBody"]["content"]["application/json"]

    assert documented["examples"].keys() == examples.keys()
    for example in examples.values():
        model.model_validate(example["value"])


@pytest.mark.parametrize("model", ["EditLapsRequest", "ResetLapsRequest", "SetSegmentsRequest"])
def test_the_text_policy_values_are_documented(model):
    schemas = app.openapi()["components"]["schemas"]
    text_policy = schemas[model]["properties"]["textPolicy"]

    assert text_policy["description"] == TEXT_POLICY_DESCRIPTION
    assert schemas["TextPolicy"]["enum"] == ["regenerate", "keep"]


# ---------- response ----------


@pytest.mark.parametrize("send", EDITS)
def test_each_lap_says_whether_the_user_edited_it(service, send):
    laps = send().json()["processed_data"]["laps"]

    assert [(lap["lapIndex"], lap["distance"], lap["version"]) for lap in laps] == [
        (1, 1000.0, 0),
        (2, 1100.0, 1),
        (3, 1000.0, 0),
    ]
