"""Typed errors for Garmin responses."""

import httpx

from app.providers.garmin.errors import retry_after_seconds


class GarminError(httpx.HTTPStatusError):
    """A Garmin error response that callers handle by its type."""


class GarminUnauthorizedError(GarminError):
    """401 or 403, or a rejected token request: the API key, or the access token traded
    for it, doesn't work.
    """


class GarminNotFoundError(GarminError):
    """404: the activity was deleted, or the account can't see it."""


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


def raise_for_api_status(response: httpx.Response) -> None:
    """Raise for an error response from the Garmin API.

    401, 403, 404 and 429 raise a ``GarminError``; any other error status raises a
    plain ``httpx.HTTPStatusError``.
    """
    message = f"Garmin returned {response.status_code} for {response.request.url.path}"
    match response.status_code:
        case 401 | 403:
            raise GarminUnauthorizedError(message, request=response.request, response=response)
        case 404:
            raise GarminNotFoundError(message, request=response.request, response=response)
        case 429:
            raise GarminRateLimitedError(
                message,
                request=response.request,
                response=response,
                retry_after=retry_after_seconds(response.headers),
            )
    response.raise_for_status()


def raise_for_token_status(response: httpx.Response) -> None:
    """Raise for an error response from Garmin's token endpoint.

    400 means Garmin rejected the API key, and raises ``GarminUnauthorizedError`` like
    401 and 403. Other statuses are handled as for the API.
    """
    if response.status_code == 400:
        raise GarminUnauthorizedError(
            f"Garmin rejected the token request with {response.status_code}",
            request=response.request,
            response=response,
        )
    raise_for_api_status(response)
