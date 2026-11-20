"""App-wide logging setup: a text or JSON line format, and access-log redaction of
sensitive URL parts.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import override
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

_APP_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"

# The attributes a plain ``logging.LogRecord`` carries; anything else on a record came
# from a caller's ``extra=`` and is passed through by ``JsonFormatter``.
_LOG_RECORD_ATTRS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__
) | {"message", "asctime"}

SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "code",
        "state",
        "access_token",
        "refresh_token",
        "token",
        "client_secret",
        "hub.verify_token",
        "hub.challenge",
    }
)

# /api/webhooks/<provider>/<path-secret> — keep secret out of access logs
_WEBHOOK_PATH_SECRET_RE = re.compile(
    r"(?P<prefix>/webhooks/[^/?#]+/)(?P<secret>[^/?#]+)",
    re.IGNORECASE,
)


def redact_callback_url(url: str) -> str:
    """Redact webhook path secrets in a full callback URL (for scripts/logs)."""
    return _WEBHOOK_PATH_SECRET_RE.sub(r"\g<prefix>[REDACTED]", url)


def redact_path(path: str) -> str:
    """Replace sensitive path segments and query values with ``[REDACTED]``."""
    parts = urlsplit(path)
    safe_path = _WEBHOOK_PATH_SECRET_RE.sub(r"\g<prefix>[REDACTED]", parts.path)

    if not parts.query:
        return urlunsplit((parts.scheme, parts.netloc, safe_path, "", parts.fragment))

    redacted_pairs: list[str] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_PARAMS:
            redacted_pairs.append(f"{quote(key)}=[REDACTED]")
        else:
            redacted_pairs.append(urlencode([(key, value)]))

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            safe_path,
            "&".join(redacted_pairs),
            parts.fragment,
        )
    )


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ``ts``, ``level``, ``logger``, ``request_id``,
    ``message``, ``exc_info`` when an exception is attached, and any ``extra`` fields a
    caller passed to the log call.
    """

    @override
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exc_info"] = record.exc_text
        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_ATTRS and key != "request_id":
                payload[key] = value
        return json.dumps(payload, default=str)


def _formatter_for(log_format: str) -> logging.Formatter:
    """The configured line formatter: ``JsonFormatter`` for ``'json'``, the text format
    otherwise.
    """
    if log_format == "json":
        return JsonFormatter()
    return logging.Formatter(_APP_LOG_FORMAT)


def _app_handler(formatter: logging.Formatter) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter())
    return handler


def _install_handler(logger: logging.Logger, formatter: logging.Formatter) -> None:
    """Attach one app handler with ``formatter`` to ``logger``; replace the formatter of
    an existing one instead of adding a second, so this is safe to call again.
    """
    if not logger.handlers:
        logger.addHandler(_app_handler(formatter))
        return
    for handler in logger.handlers:
        handler.setFormatter(formatter)
        if not any(isinstance(f, ContextFilter) for f in handler.filters):
            handler.addFilter(ContextFilter())


def install_redacting_access_log() -> None:
    """Route uvicorn's server log through the app log format, and silence its access
    log: ``RequestContextMiddleware`` already logs one line per request, with the path
    redacted.
    """
    from app.config.loader import CONFIG

    formatter = _formatter_for(str(CONFIG.get("LOG_FORMAT", "text")))

    server_logger = logging.getLogger("uvicorn")
    server_logger.handlers = [_app_handler(formatter)]
    server_logger.propagate = False

    error_logger = logging.getLogger("uvicorn.error")
    error_logger.handlers = []
    error_logger.propagate = True

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = []
    access_logger.propagate = False
    access_logger.disabled = True


class ContextFilter(logging.Filter):
    """Inject ``request_id`` from the log-context ContextVar (default ``-``): the
    incoming request's id for an HTTP request, or ``provider:activity_key`` while the
    worker imports that item.
    """

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        from app.core.request_context import log_context_var

        record.request_id = log_context_var.get()
        return True


def configure_logging() -> None:
    """Apply ``LOG_LEVEL`` and ``LOG_FORMAT`` from config.yml to the whole process.

    The ``app`` logger package runs at ``LOG_LEVEL``; the root logger, which every
    other logger (SQLAlchemy, alembic, captured ``warnings``, ...) propagates to unless
    it sets its own handler, runs at WARNING. Both share one formatter and handler
    setup, so third-party lines look like the app's own.
    """
    from app.config.loader import CONFIG

    level_name = str(CONFIG.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO

    formatter = _formatter_for(str(CONFIG.get("LOG_FORMAT", "text")))
    logging.captureWarnings(True)

    root_logger = logging.getLogger()
    _install_handler(root_logger, formatter)
    root_logger.setLevel(logging.WARNING)

    app_logger = logging.getLogger("app")
    _install_handler(app_logger, formatter)
    app_logger.setLevel(level)
    app_logger.propagate = False

    # httpx logs each request at INFO; show those only when LOG_LEVEL is DEBUG
    logging.getLogger("httpx").setLevel(
        logging.DEBUG if level <= logging.DEBUG else logging.WARNING
    )
