"""Downloading an activity file from the link a Garmin notification carries."""

import logging
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from app.core.clock import utc_now
from app.providers.base import ResponseObserver
from app.providers.garmin.constants import (
    ACTIVITY_FILE_PATH,
    GARMIN_API_HOST,
    GARMIN_TIMEOUT,
    MAX_FILE_BYTES,
)
from app.providers.garmin.errors import (
    GarminFileGoneError,
    GarminFileTooLargeError,
    raise_for_download_status,
)

logger = logging.getLogger(__name__)

SNIFF_BYTES = 8  # leading bytes of a download that are logged, to tell FIT from ZIP


def is_activity_file_url(url: object) -> bool:
    """Whether ``url`` is a link to Garmin's activity file endpoint: ``https``, the host
    ``GARMIN_API_HOST`` on the default port, and the path ``ACTIVITY_FILE_PATH``.
    """
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname == GARMIN_API_HOST
        and port is None
        and not parts.username
        and not parts.password
        and parts.path == ACTIVITY_FILE_PATH
    )


async def download_activity_file(
    url: str,
    access_token: str,
    *,
    on_response: ResponseObserver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] = utc_now,
    max_bytes: int = MAX_FILE_BYTES,
) -> bytes:
    """The body of the activity file at ``url``, fetched with ``access_token``.

    Redirects aren't followed. The response is passed to ``on_response``, with the time
    its request was sent, before its body is read. Error statuses raise as
    ``raise_for_download_status`` says; a body larger than ``max_bytes`` raises
    ``GarminFileTooLargeError``, an empty one ``GarminFileGoneError``. A timeout or a
    connection error raises its ``httpx.HTTPError``. ``transport`` replaces the network,
    e.g. with ``httpx.MockTransport``; ``clock`` gives the current time.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(
        timeout=GARMIN_TIMEOUT, transport=transport, follow_redirects=False
    ) as client:
        sent_at = clock()
        async with client.stream("GET", url, headers=headers) as response:
            if on_response is not None:
                await on_response(response, sent_at)
            if not response.is_success:
                _log_response(response, b"")
                raise_for_download_status(response)
            _check_length(response, max_bytes)
            content = await _read_capped(response, max_bytes)
            _log_response(response, content)
    if not content:
        raise GarminFileGoneError(
            "Garmin sent an empty activity file", request=response.request, response=response
        )
    return content


def _check_length(response: httpx.Response, max_bytes: int) -> None:
    length = response.headers.get("Content-Length")
    if length is not None and length.isdigit() and int(length) > max_bytes:
        raise GarminFileTooLargeError(f"The activity file is {length} bytes, over {max_bytes}")


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise GarminFileTooLargeError(f"The activity file is over {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _log_response(response: httpx.Response, content: bytes) -> None:
    logger.info(
        "garmin activity file: status %s, content type %s, length %d, first bytes %s",
        response.status_code,
        response.headers.get("Content-Type"),
        len(content),
        content[:SNIFF_BYTES].hex(),
    )
