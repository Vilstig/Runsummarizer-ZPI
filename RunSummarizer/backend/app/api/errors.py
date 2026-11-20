"""Central FastAPI handlers that turn errors into ``{"detail", "code"}`` responses."""

import logging
import math
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.providers import OAuthCallbackFailedError, oauth_callback_failed
from app.api.validation_errors import request_validation_error
from app.core.logging import redact_path
from app.domain.errors import (
    ActivityNotFoundError,
    AnotherProviderConnectedError,
    DomainError,
    HeartRateZonesConflictError,
    InvalidSegmentationError,
    InvalidSyncLimitError,
    InvalidSyncWindowError,
    OAuthStateMismatchError,
    ProviderAccountTakenError,
    ProviderAuthorizationError,
    ProviderError,
    ProviderNotConnectedError,
    ProviderNotSupportedError,
    ProviderPausedError,
    SyncNotSupportedError,
    TextPolicyRequiredError,
    UnknownLapError,
    UserNotFoundError,
    WebhookPayloadError,
    WebhookRejectedError,
)

logger = logging.getLogger(__name__)

# (status, code, detail). A detail of None is ``str(exc)``; otherwise a template whose
# ``{provider}`` is the provider in the request path. The most specific class in the
# exception's MRO wins.
ERRORS: dict[type[DomainError], tuple[int, str, str | None]] = {
    ActivityNotFoundError: (404, "activity_not_found", None),
    UserNotFoundError: (404, "user_not_found", None),
    ProviderNotSupportedError: (404, "provider_not_supported", None),
    UnknownLapError: (400, "unknown_lap", None),
    InvalidSegmentationError: (400, "invalid_segmentation", None),
    InvalidSyncWindowError: (400, "invalid_sync_window", None),
    InvalidSyncLimitError: (400, "invalid_sync_limit", None),
    OAuthStateMismatchError: (400, "oauth_state_mismatch", None),
    WebhookRejectedError: (403, "webhook_rejected", None),
    WebhookPayloadError: (422, "invalid_webhook_event", None),
    TextPolicyRequiredError: (409, "text_policy_required", None),
    HeartRateZonesConflictError: (409, "hr_zones_conflict", None),
    AnotherProviderConnectedError: (409, "another_provider_connected", None),
    ProviderAccountTakenError: (409, "provider_account_taken", None),
    SyncNotSupportedError: (
        409,
        "sync_not_supported",
        "{provider} can't be synced. New activities arrive on their own.",
    ),
    # str() of a provider error can hold provider internals, so these use templates.
    ProviderNotConnectedError: (409, "provider_not_connected", "{provider} not connected"),
    ProviderAuthorizationError: (
        409,
        "provider_reauthorization_required",
        "{provider} authorization expired. Please reconnect {provider}.",
    ),
    ProviderPausedError: (
        503,
        "provider_rate_limited",
        "{provider}'s rate limit is used up. Please try again later.",
    ),
    ProviderError: (
        502,
        "provider_unavailable",
        "Failed to reach {provider}. Please try again later.",
    ),
}

_HTTP_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
}

# Expected client responses; the uvicorn access log already records their status.
_ROUTINE_HTTP_STATUSES = frozenset({401, 403, 404, 405})


def _resolve(exc: DomainError, request: Request) -> tuple[int, str, str]:
    for cls in type(exc).__mro__:
        if cls in ERRORS:
            status, code, template = ERRORS[cls]
            if template is None:
                return status, code, str(exc)
            provider = str(request.path_params.get("provider", "the provider")).title()
            return status, code, template.format(provider=provider)
    return 500, "internal_error", "An unexpected error occurred."


def _retry_after(until: datetime) -> str:
    """The ``Retry-After`` header value for ``until``: whole seconds from now, at least 1."""
    return str(max(1, math.ceil((until - datetime.now(UTC)).total_seconds())))


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status, code, detail = _resolve(exc, request)
    path = redact_path(request.url.path)
    if status >= 500:
        logger.error("%s %s failed: %s", request.method, path, code, exc_info=exc)
    else:
        logger.warning("%s %s -> %d %s: %s", request.method, path, status, code, exc)
    headers = (
        {"Retry-After": _retry_after(exc.until)} if isinstance(exc, ProviderPausedError) else None
    )
    return JSONResponse({"detail": detail, "code": code}, status, headers=headers)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status = exc.status_code
    if status >= 500:
        level = logging.ERROR
    elif status in _ROUTINE_HTTP_STATUSES:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logger.log(
        level,
        "%s %s -> %d: %s",
        request.method,
        redact_path(request.url.path),
        status,
        exc.detail,
    )
    return JSONResponse(
        {"detail": str(exc.detail), "code": _HTTP_CODES.get(exc.status_code, "error")},
        exc.status_code,
        headers=exc.headers,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error on %s %s",
        request.method,
        redact_path(request.url.path),
        exc_info=exc,
    )
    return JSONResponse({"detail": "An unexpected error occurred.", "code": "internal_error"}, 500)


def register_exception_handlers(app: FastAPI) -> None:
    """Install the app's exception handlers."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(OAuthCallbackFailedError, oauth_callback_failed)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error)
    app.add_exception_handler(Exception, unhandled_error_handler)
