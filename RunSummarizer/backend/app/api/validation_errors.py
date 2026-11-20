"""The 422 answer to a request that fails validation."""

import logging
from math import isfinite

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import redact_path

logger = logging.getLogger(__name__)


def _json_safe(value):
    """``value`` with each float JSON can't hold (NaN, infinity), at any depth, as its text."""
    if isinstance(value, float) and not isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


async def request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422 answer, with the inputs JSON can't hold given as text."""
    logger.warning(
        "%s %s -> 422: %s",
        request.method,
        redact_path(request.url.path),
        "; ".join(
            f"{'.'.join(str(part) for part in error.get('loc', ()))} {error.get('type')}"
            for error in exc.errors()
        ),
    )
    return JSONResponse(
        status_code=422,
        content={
            "detail": _json_safe(jsonable_encoder(exc.errors())),
            "code": "validation_error",
        },
    )
