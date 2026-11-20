"""Typed errors for Garmin Developer Program responses."""

import json
import re

import httpx

# a token-endpoint error body longer than this is not read for its OAuth error code
TOKEN_ERROR_MAX_BYTES = 4096
# OAuth error code: the authorization code or refresh token is invalid, expired or revoked
INVALID_GRANT = "invalid_grant"
_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")  # an OAuth error code the app reads


class GarminError(httpx.HTTPStatusError):
    """A Garmin error response. Its message names the request's path only: the query
    of an activity file link holds a download token.
    """


class GarminTokenRejectedError(GarminError):
    """400 or 401 from the token endpoint: Garmin rejected the token request.

    ``error_code`` is the OAuth error code of the response body (``'invalid_grant'``,
    ``'invalid_client'``, ...), or None when the body carries none.
    """

    def __init__(
        self,
        message: str,
        *,
        request: httpx.Request,
        response: httpx.Response,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message, request=request, response=response)
        self.error_code = error_code


class GarminUnauthorizedError(GarminError):
    """401, 403 or 412 from the API: the access token doesn't work, or the user no longer
    grants the app access.
    """


class GarminFileGoneError(GarminError):
    """404, 410 or another 4xx on an activity file download, or a download without a
    body: the file can't be had from this link any more.
    """


class GarminRateLimitedError(GarminError):
    """429: Garmin's rate limit is used up."""

    def __init__(
        self,
        message: str,
        *,
        request: httpx.Request,
        response: httpx.Response,
        retry_after: int | None,
    ) -> None:
        super().__init__(message, request=request, response=response)
        self.retry_after = retry_after  # seconds; None when Garmin didn't say


class GarminFileTooLargeError(Exception):
    """An activity file download larger than the app accepts."""


class GarminInvalidResponseError(ValueError):
    """A successful Garmin response without the content its endpoint returns, e.g. a
    token that isn't a JWT, or a download that is empty, isn't a ZIP or holds several
    FIT files.
    """


class GarminUnsupportedFileError(ValueError):
    """An activity whose original file isn't a FIT file, e.g. an uploaded GPX or TCX."""

    def __init__(self, message: str, *, files: list[str]):
        super().__init__(message)
        self.files = files  # names of the files in the download


def retry_after_seconds(headers: httpx.Headers) -> int | None:
    """``Retry-After`` in seconds, or None when it is missing or not a number of seconds."""
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def _message(response: httpx.Response) -> str:
    return f"Garmin returned {response.status_code} for {response.request.url.path}"


def _raise_if_error(response: httpx.Response) -> None:
    """Raise a ``GarminError`` for any response that isn't a success."""
    if not response.is_success:
        raise GarminError(_message(response), request=response.request, response=response)


def _raise_rate_limited(response: httpx.Response) -> None:
    raise GarminRateLimitedError(
        _message(response),
        request=response.request,
        response=response,
        retry_after=retry_after_seconds(response.headers),
    )


def raise_for_api_status(response: httpx.Response) -> None:
    """Raise for an error response from the Garmin API.

    401, 403 and 412 raise ``GarminUnauthorizedError``, 429 ``GarminRateLimitedError``;
    any other status that isn't a success, redirects included, raises a ``GarminError``.
    """
    match response.status_code:
        case 401 | 403 | 412:
            raise GarminUnauthorizedError(
                _message(response), request=response.request, response=response
            )
        case 429:
            _raise_rate_limited(response)
    _raise_if_error(response)


def raise_for_download_status(response: httpx.Response) -> None:
    """Raise for an error response to an activity file download.

    As ``raise_for_api_status``, except that 404, 410 and any other 4xx raise
    ``GarminFileGoneError``.
    """
    if 400 <= response.status_code < 500 and response.status_code not in (401, 403, 412, 429):
        raise GarminFileGoneError(_message(response), request=response.request, response=response)
    raise_for_api_status(response)


def oauth_error_code(body: bytes) -> str | None:
    """The OAuth error code (``error``) of a token-endpoint error ``body``, or None when
    the body is longer than ``TOKEN_ERROR_MAX_BYTES``, isn't a JSON object, or its code
    isn't a short word of letters, digits, ``_``, ``.`` or ``-``.
    """
    if len(body) > TOKEN_ERROR_MAX_BYTES:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    code = data.get("error") if isinstance(data, dict) else None
    if not isinstance(code, str) or not _ERROR_CODE.fullmatch(code):
        return None
    return code


def raise_for_token_status(response: httpx.Response, error_body: bytes = b"") -> None:
    """Raise for an error response from Garmin's token endpoint, whose body (or its
    first bytes) is ``error_body``.

    400 and 401 raise ``GarminTokenRejectedError`` with the body's ``oauth_error_code``,
    429 ``GarminRateLimitedError``; any other status that isn't a success raises a
    ``GarminError``.
    """
    if response.status_code in (400, 401):
        error_code = oauth_error_code(error_body)
        raise GarminTokenRejectedError(
            f"Garmin rejected the token request with {response.status_code} "
            f"({error_code or 'no error code'})",
            request=response.request,
            response=response,
            error_code=error_code,
        )
    if response.status_code == 429:
        _raise_rate_limited(response)
    _raise_if_error(response)
