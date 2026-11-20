from fastapi import Query
from fastapi.exceptions import RequestValidationError

from app.domain.enums import StreamType

_NAMES = ", ".join(StreamType)

# OpenAPI parameter for ``keys``: an array of stream names sent comma-separated
# (form style, not exploded), which Swagger UI shows as a multi-select.
KEYS_PARAMETER = {
    "name": "keys",
    "in": "query",
    "required": False,
    "description": "Streams to return, comma-separated, e.g. time,heartrate; all of them "
    "when left out.",
    "style": "form",
    "explode": False,
    "schema": {
        "type": "array",
        "items": {"type": "string", "enum": [stream_type.value for stream_type in StreamType]},
    },
}


def parse_stream_keys(keys: str) -> tuple[StreamType, ...]:
    """The stream types a comma-separated ``keys`` names, in order and without repeats.

    Blank names are skipped. Raises ``ValueError`` for an unknown name, or when no name
    is left.
    """
    names = [name.strip() for name in keys.split(",") if name.strip()]
    unknown = [name for name in names if name not in StreamType]
    if unknown:
        raise ValueError(f"Unknown streams: {', '.join(unknown)}. Expected some of: {_NAMES}")
    if not names:
        raise ValueError(f"'keys' names no stream. Expected some of: {_NAMES}")
    return tuple(dict.fromkeys(StreamType(name) for name in names))


def get_stream_types(
    # documented by KEYS_PARAMETER, which the route adds to its OpenAPI operation
    keys: str | None = Query(default=None, include_in_schema=False),
) -> tuple[StreamType, ...]:
    if keys is None:
        return tuple(StreamType)
    try:
        return parse_stream_keys(keys)
    except ValueError as exc:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("query", "keys"), "msg": str(exc), "input": keys}]
        ) from exc
