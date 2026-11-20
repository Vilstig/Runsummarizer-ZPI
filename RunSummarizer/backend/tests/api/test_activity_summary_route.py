"""PATCH /api/v1/activities/{id}/summary, POST /api/v1/activities/{id}/summary/reset, and the
summary fields of an activity response."""

from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service, require_user
from app.api.schemas.activities import SummaryEditRequest
from app.domain.errors import ActivityNotFoundError
from app.domain.models import ActivityRecord, Summary
from app.main import app
from tests.db.builders import make_activity

ACTIVITY = "/api/v1/activities/strava_7"
USER_ID = "user-1"

EDITED = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
RECORD = replace(
    make_activity("strava_7", user_id=USER_ID),
    summary=Summary(text="every kind", text_edited_at=EDITED),
)


class FakeActivityService:
    """Stands in for ``ActivityService``: records each call and answers with ``record``,
    or raises ``error``."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.record: ActivityRecord | None = RECORD
        self.error: Exception | None = None

    async def edit_summary(self, *args, **kwargs) -> ActivityRecord | None:
        return self._answer("edit_summary", args, kwargs)

    async def reset_summary(self, *args, **kwargs) -> ActivityRecord | None:
        return self._answer("reset_summary", args, kwargs)

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


def patch_summary(body: dict) -> httpx.Response:
    return TestClient(app).patch(f"{ACTIVITY}/summary", json=body)


# ---------- PATCH /summary ----------


def test_a_text_edit_is_passed_to_the_service(service):
    response = patch_summary({"text": "my own words"})

    assert response.status_code == 200
    assert service.calls == [("edit_summary", ("strava_7", "my own words"), {"user_id": USER_ID})]


def test_an_empty_text_is_passed_to_the_service(service):
    response = patch_summary({"text": ""})

    assert response.status_code == 200
    assert service.calls == [("edit_summary", ("strava_7", ""), {"user_id": USER_ID})]


def test_the_edit_response_carries_the_summary_text_and_its_edit_flag(service):
    service.record = replace(
        make_activity("strava_7", user_id=USER_ID),
        summary=Summary(text="my own words", text_edited_at=EDITED),
    )

    body = patch_summary({"text": "my own words"}).json()

    assert body["summary"] == "my own words"
    assert body["summaryTextEdited"] is True


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no text"),
        pytest.param({"text": None}, id="null text"),
        pytest.param({"text": "words", "textPolicy": "keep"}, id="a policy"),
        pytest.param({"segments": [{"startLapIndex": 4, "label": "Seria"}]}, id="segments"),
        pytest.param({"text": "words", "textpolicy": "keep"}, id="a misspelt field"),
    ],
)
def test_a_malformed_body_is_rejected(service, body):
    response = patch_summary(body)

    assert response.status_code == 422
    assert service.calls == []


def test_the_request_examples_are_valid_edits():
    operation = app.openapi()["paths"]["/api/v1/activities/{activity_id}/summary"]["patch"]
    examples = operation["requestBody"]["content"]["application/json"]["examples"]

    assert [example["summary"] for example in examples.values()] == ["Edit the text"]
    for example in examples.values():
        SummaryEditRequest.model_validate(example["value"])


def test_the_error_responses_are_documented():
    responses = app.openapi()["paths"]["/api/v1/activities/{activity_id}/summary"]["patch"][
        "responses"
    ]

    assert "404" in responses


def test_a_summary_edit_of_an_activity_that_is_not_found_is_a_404(service):
    service.record = None

    response = patch_summary({"text": "words"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}


# ---------- POST /summary/reset ----------


def test_a_reset_is_passed_to_the_service(service):
    response = TestClient(app).post(f"{ACTIVITY}/summary/reset")

    assert response.status_code == 200
    assert service.calls == [("reset_summary", ("strava_7",), {"user_id": USER_ID})]


def test_the_reset_response_clears_the_edit_flag(service):
    service.record = make_activity("strava_7", user_id=USER_ID, summary="5 km easy")

    body = TestClient(app).post(f"{ACTIVITY}/summary/reset").json()

    assert body["summary"] == "5 km easy"
    assert body["summaryTextEdited"] is False


def test_a_reset_of_an_activity_that_is_not_found_is_a_404(service):
    service.record = None

    response = TestClient(app).post(f"{ACTIVITY}/summary/reset")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found", "code": "activity_not_found"}


# ---------- response ----------


def test_the_response_carries_the_summary_text_and_its_edit_flag(service):
    body = TestClient(app).get(ACTIVITY).json()

    assert body["summary"] == "every kind"
    assert body["summaryTextEdited"] is True
    assert "summaryParams" not in body
    assert "summaryParamsEdited" not in body


def test_a_summary_the_user_did_not_edit_is_flagged_so(service):
    service.record = make_activity("strava_7", user_id=USER_ID, summary="5 km easy")

    assert TestClient(app).get(ACTIVITY).json()["summaryTextEdited"] is False
