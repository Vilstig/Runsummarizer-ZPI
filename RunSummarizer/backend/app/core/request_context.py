"""Request-scoped context (request id) for logging correlation."""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import redact_path

logger = logging.getLogger(__name__)

# The incoming request's id for an HTTP request; ``provider:activity_key`` while the
# worker imports that item; ``-`` otherwise.
log_context_var: ContextVar[str] = ContextVar("log_context", default="-")

_REQUEST_ID_HEADER = b"x-request-id"
_HEALTH_PATH_PREFIX = "/api/health"


class RequestContextMiddleware:
    """Set a request-id contextvar, echo it on the response, and log one line per
    request: INFO, WARNING for a 5xx response, DEBUG for the health check.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex[:12]
        token = log_context_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((_REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            method = scope.get("method", "?")
            raw_path = scope.get("path") or ""
            path = redact_path(_raw_path(scope))
            level = _request_log_level(status_code, raw_path)
            logger.log(
                level,
                "%s %s -> %s in %.0fms",
                method,
                path,
                status_code,
                elapsed_ms,
            )
            log_context_var.reset(token)


def _request_log_level(status_code: int, raw_path: str) -> int:
    if status_code >= 500:
        return logging.WARNING
    if raw_path.startswith(_HEALTH_PATH_PREFIX):
        return logging.DEBUG
    return logging.INFO


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == _REQUEST_ID_HEADER:
            decoded = value.decode("latin-1").strip()
            return decoded or None
    return None


def _raw_path(scope: Scope) -> str:
    path = scope.get("path") or ""
    query = scope.get("query_string") or b""
    if query:
        return f"{path}?{query.decode('latin-1')}"
    return path
