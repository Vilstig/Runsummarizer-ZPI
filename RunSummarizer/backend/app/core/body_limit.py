"""Refuse request bodies larger than a limit before the app reads them whole."""

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import redact_path

logger = logging.getLogger(__name__)

DEFAULT_MAX_BODY_BYTES = 1024 * 1024  # 1 MiB


class _BodyTooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    """Answer 413 to a request whose body is over ``max_bytes``.

    A ``Content-Length`` over the limit is refused before any of the body is read. A body
    without one (chunked) is counted as the app reads it, and refused once it passes the
    limit, if the app hasn't started its response by then.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_BODY_BYTES):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await self._refuse(scope, receive, send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if response_started:
                raise
            await self._refuse(scope, receive, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        logger.warning(
            "%s: request body over %d bytes refused",
            redact_path(scope.get("path") or ""),
            self.max_bytes,
        )
        response = JSONResponse(
            {
                "detail": f"Request body is larger than {self.max_bytes} bytes",
                "code": "request_too_large",
            },
            status_code=413,
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
