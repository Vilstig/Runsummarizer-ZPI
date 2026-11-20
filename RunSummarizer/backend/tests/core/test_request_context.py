"""RequestContextMiddleware: one log line per request, its level, and path redaction."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.request_context import RequestContextMiddleware, log_context_var

LOGGER_NAME = "app.core.request_context"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/boom")
    async def boom():
        return JSONResponse({"detail": "boom"}, status_code=500)

    @app.get("/webhooks/strava/{secret}")
    async def webhook(secret: str):
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def _line(caplog) -> logging.LogRecord:
    [record] = [r for r in caplog.records if r.name == LOGGER_NAME]
    return record


def test_a_successful_request_is_logged_at_info(client, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    client.get("/ok")

    record = _line(caplog)
    assert record.levelno == logging.INFO
    assert "GET /ok -> 200" in record.getMessage()


def test_a_5xx_response_is_logged_at_warning(client, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    client.get("/boom")

    assert _line(caplog).levelno == logging.WARNING


def test_the_health_check_is_logged_at_debug(client, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    client.get("/api/health")

    assert _line(caplog).levelno == logging.DEBUG


def test_a_webhook_path_secret_is_redacted_in_the_log(client, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    client.get("/webhooks/strava/s3cret")

    message = _line(caplog).getMessage()
    assert "s3cret" not in message
    assert "[REDACTED]" in message


def test_the_log_context_is_reset_after_the_request(client):
    client.get("/ok")

    assert log_context_var.get() == "-"


def test_the_response_echoes_the_request_id_header(client):
    response = client.get("/ok", headers={"x-request-id": "req-123"})

    assert response.headers["x-request-id"] == "req-123"
