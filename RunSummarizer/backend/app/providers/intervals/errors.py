"""Typed errors for Intervals.icu responses."""

import httpx


class IntervalsError(httpx.HTTPStatusError):
    """An Intervals.icu error response that callers handle by its type."""


class IntervalsUnauthorizedError(IntervalsError):
    """401 or 403, or a rejected token request: the Intervals.icu authorization doesn't
    work."""


class IntervalsNotFoundError(IntervalsError):
    """404: the activity, or its file, doesn't exist or isn't visible to the token."""


class IntervalsRateLimitedError(IntervalsError):
    """429: Intervals.icu's rate limit is used up."""


def raise_for_api_status(response: httpx.Response) -> None:
    """Raise for an error response from the Intervals.icu API.

    401, 403, 404 and 429 raise an ``IntervalsError``; any other error status raises a
    plain ``httpx.HTTPStatusError``.
    """
    message = f"Intervals.icu returned {response.status_code} for {response.request.url.path}"
    match response.status_code:
        case 401 | 403:
            raise IntervalsUnauthorizedError(message, request=response.request, response=response)
        case 404:
            raise IntervalsNotFoundError(message, request=response.request, response=response)
        case 429:
            raise IntervalsRateLimitedError(message, request=response.request, response=response)
    response.raise_for_status()


def raise_for_token_status(response: httpx.Response) -> None:
    """Raise for an error response from Intervals.icu's token endpoint.

    400, 401 and 403 mean Intervals.icu rejected the authorization code, and raise
    ``IntervalsUnauthorizedError``. Other statuses are handled as for the API.
    """
    if response.status_code in (400, 401, 403):
        raise IntervalsUnauthorizedError(
            f"Intervals.icu rejected the token request with {response.status_code}",
            request=response.request,
            response=response,
        )
    raise_for_api_status(response)
