"""redact_path, redact_callback_url, JsonFormatter and configure_logging."""

import json
import logging
import sys

import pytest

from app.config.loader import CONFIG
from app.core.logging import (
    ContextFilter,
    JsonFormatter,
    configure_logging,
    redact_callback_url,
    redact_path,
)
from app.core.request_context import log_context_var


@pytest.mark.parametrize("provider", ["strava", "garmin", "intervals"])
def test_a_webhook_path_secret_is_redacted(provider):
    assert redact_path(f"/api/webhooks/{provider}/s3cret") == (
        f"/api/webhooks/{provider}/[REDACTED]"
    )


def test_a_webhook_query_is_redacted_too():
    path = "/api/webhooks/strava/s3cret?hub.verify_token=t&hub.mode=subscribe"

    assert redact_path(path) == (
        "/api/webhooks/strava/[REDACTED]?hub.verify_token=[REDACTED]&hub.mode=subscribe"
    )


def test_the_clerk_webhook_path_is_kept():
    assert redact_path("/api/webhooks/clerk") == "/api/webhooks/clerk"


def test_a_callback_url_has_its_path_secret_redacted():
    assert redact_callback_url("https://example.com/api/webhooks/strava/s3cret") == (
        "https://example.com/api/webhooks/strava/[REDACTED]"
    )


# ---------- ContextFilter ----------


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%s item %s",
        args=("strava", "strava_7"),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_the_context_filter_reads_the_log_context():
    token = log_context_var.set("strava:strava_7")
    try:
        record = _record()
        assert ContextFilter().filter(record) is True
        assert record.request_id == "strava:strava_7"
    finally:
        log_context_var.reset(token)


def test_the_context_filter_defaults_to_a_dash():
    record = _record()

    ContextFilter().filter(record)

    assert record.request_id == "-"


# ---------- JsonFormatter ----------


def test_the_json_formatter_has_the_core_fields():
    record = _record(request_id="req-1")

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.worker"
    assert payload["request_id"] == "req-1"
    assert payload["message"] == "strava item strava_7"
    assert "ts" in payload


def test_the_json_formatter_defaults_the_request_id():
    payload = json.loads(JsonFormatter().format(_record()))

    assert payload["request_id"] == "-"


def test_the_json_formatter_passes_extra_fields_through():
    payload = json.loads(JsonFormatter().format(_record(activity_key="strava_7")))

    assert payload["activity_key"] == "strava_7"


def test_the_json_formatter_renders_an_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="app",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in payload["exc_info"]


# ---------- configure_logging ----------


@pytest.fixture
def clean_logging():
    """Restore the ``app`` and root loggers' handlers and levels after the test."""
    app_logger = logging.getLogger("app")
    root_logger = logging.getLogger()
    saved = (
        list(app_logger.handlers),
        app_logger.level,
        app_logger.propagate,
        list(root_logger.handlers),
        root_logger.level,
    )
    app_logger.handlers = []
    root_logger.handlers = []
    yield
    app_handlers, app_level, app_propagate, root_handlers, root_level = saved
    app_logger.handlers = app_handlers
    app_logger.setLevel(app_level)
    app_logger.propagate = app_propagate
    root_logger.handlers = root_handlers
    root_logger.setLevel(root_level)


def test_configure_logging_attaches_one_handler_to_app_and_root(clean_logging, monkeypatch):
    monkeypatch.setitem(CONFIG, "LOG_LEVEL", "DEBUG")
    monkeypatch.setitem(CONFIG, "LOG_FORMAT", "text")

    configure_logging()

    assert len(logging.getLogger("app").handlers) == 1
    # The root logger may already carry pytest's own log-capture handler; only ours
    # has the context filter.
    assert any(
        any(isinstance(f, ContextFilter) for f in handler.filters)
        for handler in logging.getLogger().handlers
    )
    assert logging.getLogger("app").level == logging.DEBUG
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_does_not_add_a_second_handler(clean_logging, monkeypatch):
    monkeypatch.setitem(CONFIG, "LOG_LEVEL", "INFO")

    configure_logging()
    app_handlers = len(logging.getLogger("app").handlers)
    root_handlers = len(logging.getLogger().handlers)

    configure_logging()

    assert len(logging.getLogger("app").handlers) == app_handlers
    assert len(logging.getLogger().handlers) == root_handlers


def test_configure_logging_selects_the_json_formatter(clean_logging, monkeypatch):
    monkeypatch.setitem(CONFIG, "LOG_FORMAT", "json")

    configure_logging()

    [handler] = logging.getLogger("app").handlers
    assert isinstance(handler.formatter, JsonFormatter)


def test_configure_logging_defaults_to_the_text_formatter(clean_logging, monkeypatch):
    monkeypatch.delitem(CONFIG, "LOG_FORMAT", raising=False)

    configure_logging()

    [handler] = logging.getLogger("app").handlers
    assert not isinstance(handler.formatter, JsonFormatter)
