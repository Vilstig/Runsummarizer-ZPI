"""Typed errors for Strava responses."""

import httpx

from app.domain.models import RateLimitUsage
from app.providers.strava.budget import rate_limit_usage


class StravaError(httpx.HTTPStatusError):
    """A Strava error response that callers handle by its type."""


class StravaUnauthorizedError(StravaError):
    """401 or 403, or a rejected token request: the Strava authorization doesn't work."""


class StravaNotFoundError(StravaError):
    """404: the activity was deleted, or the token can't see it."""


class StravaRateLimitedError(StravaError):
    """429: Strava's rate limit is used up."""

    def __init__(
        self,
        message: str,
        *,
        request: httpx.Request,
        response: httpx.Response,
        usage: RateLimitUsage | None,
    ) -> None:
        super().__init__(message, request=request, response=response)
        self.usage = usage


def raise_for_api_status(response: httpx.Response, usage: RateLimitUsage | None) -> None:
    """Raise for an error response from the Strava API.

    401, 403, 404 and 429 raise a ``StravaError``; any other error status raises a
    plain ``httpx.HTTPStatusError``.
    """
    message = f"Strava returned {response.status_code} for {response.request.url.path}"
    match response.status_code:
        case 401 | 403:
            raise StravaUnauthorizedError(message, request=response.request, response=response)
        case 404:
            raise StravaNotFoundError(message, request=response.request, response=response)
        case 429:
            raise StravaRateLimitedError(
                message, request=response.request, response=response, usage=usage
            )
    response.raise_for_status()


def raise_for_token_status(response: httpx.Response) -> None:
    """Raise for an error response from Strava's token endpoint.

    400 and 401 mean Strava rejected the authorization code or refresh token, and
    raise ``StravaUnauthorizedError``. Other statuses are handled as for the API.
    """
    if response.status_code in (400, 401):
        raise StravaUnauthorizedError(
            f"Strava rejected the token request with {response.status_code}",
            request=response.request,
            response=response,
        )
    raise_for_api_status(response, rate_limit_usage(response.headers))
