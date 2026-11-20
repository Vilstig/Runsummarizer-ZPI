"""Size limits on request bodies: the body size middleware and the caps of edit bodies."""

import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.schemas.activities import (
    MAX_LAPS,
    MAX_SUMMARY_TEXT_LENGTH,
    EditLapsRequest,
    ResetLapsRequest,
    SetSegmentsRequest,
    SummaryEditRequest,
)
from app.core.body_limit import BodySizeLimitMiddleware
from app.main import app

# ---------- edit bodies ----------


def _lap_edits(count: int) -> dict:
    return {"laps": [{"lapIndex": index, "distance": 100} for index in range(count)]}


def test_an_edit_of_max_laps_validates_quickly():
    started = time.monotonic()
    EditLapsRequest.model_validate(_lap_edits(MAX_LAPS))
    assert time.monotonic() - started < 1


def test_an_edit_of_more_than_max_laps_is_refused():
    with pytest.raises(ValidationError):
        EditLapsRequest.model_validate(_lap_edits(MAX_LAPS + 1))


def test_an_edit_naming_a_lap_twice_is_refused():
    body = {"laps": [{"lapIndex": 3, "distance": 100}, {"lapIndex": 3, "typeId": 1}]}
    with pytest.raises(ValidationError, match="lap 3 came more than once"):
        EditLapsRequest.model_validate(body)


def test_a_reset_of_more_than_max_laps_is_refused():
    with pytest.raises(ValidationError):
        ResetLapsRequest.model_validate({"lapIndexes": list(range(MAX_LAPS + 1))})


def test_more_than_max_laps_segments_are_refused():
    segment = {"startLapIndex": 0, "role": "work"}
    with pytest.raises(ValidationError):
        SetSegmentsRequest.model_validate({"segments": [segment] * (MAX_LAPS + 1)})


def test_a_summary_text_over_the_limit_is_refused():
    SummaryEditRequest.model_validate({"text": "x" * MAX_SUMMARY_TEXT_LENGTH})
    with pytest.raises(ValidationError):
        SummaryEditRequest.model_validate({"text": "x" * (MAX_SUMMARY_TEXT_LENGTH + 1)})


# ---------- body size middleware ----------


def _echo_client(max_bytes: int) -> TestClient:
    echo = FastAPI()

    @echo.post("/echo")
    async def _echo(request: Request) -> dict:
        return {"size": len(await request.body())}

    echo.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    return TestClient(echo)


def test_a_body_within_the_limit_reaches_the_app():
    response = _echo_client(10).post("/echo", content=b"x" * 10)

    assert response.status_code == 200
    assert response.json() == {"size": 10}


def test_a_content_length_over_the_limit_is_refused():
    response = _echo_client(10).post("/echo", content=b"x" * 11)

    assert response.status_code == 413
    assert response.json()["code"] == "request_too_large"


def test_a_refused_body_logs_a_warning_with_the_limit(caplog):
    caplog.set_level("WARNING", logger="app.core.body_limit")

    _echo_client(10).post("/echo", content=b"x" * 11)

    assert "10" in caplog.text
    assert "/echo" in caplog.text


def test_a_chunked_body_over_the_limit_is_refused():
    def chunks():
        for _ in range(3):
            yield b"x" * 6

    response = _echo_client(10).post("/echo", content=chunks())

    assert response.status_code == 413
    assert response.json()["code"] == "request_too_large"


def test_the_app_refuses_an_oversized_body_before_authentication():
    response = TestClient(app).patch(
        "/api/v1/activities/strava_7/laps",
        content=b"x" * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
