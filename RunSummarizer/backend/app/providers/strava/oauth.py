"""Strava's OAuth endpoints, and the app's authorization and token refresh built on them."""

from collections.abc import Callable, Mapping
from datetime import datetime
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.core.clock import utc_now
from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderResponseError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import (
    AuthorizationStart,
    LinkResult,
    ProviderOAuth,
    TokenRefresher,
    describe_error,
)
from app.providers.strava.budget import rate_limited_until
from app.providers.strava.errors import (
    StravaRateLimitedError,
    StravaUnauthorizedError,
    raise_for_token_status,
)

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"  # noqa: S105
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"
STRAVA_TIMEOUT = 30  # seconds, for each phase of a Strava HTTP request

DEFAULT_SCOPES = "activity:read_all"


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: str = DEFAULT_SCOPES,
) -> str:
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": scopes,
            "state": state,
        }
    )
    return f"{STRAVA_AUTHORIZE_URL}?{params}"


async def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Trade an authorization code for Strava tokens and the athlete profile.

    A code Strava rejects raises ``StravaUnauthorizedError``. ``transport`` replaces
    the network, e.g. with ``httpx.MockTransport``.
    """
    async with httpx.AsyncClient(timeout=STRAVA_TIMEOUT, transport=transport) as client:
        resp = await client.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        raise_for_token_status(resp)
        return resp.json()


async def deauthorize(
    *,
    access_token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Revoke the athlete's authorization of the app, invalidating all of its tokens.

    An access token Strava rejects raises ``StravaUnauthorizedError``. ``transport``
    replaces the network, e.g. with ``httpx.MockTransport``.
    """
    async with httpx.AsyncClient(timeout=STRAVA_TIMEOUT, transport=transport) as client:
        resp = await client.post(STRAVA_DEAUTHORIZE_URL, data={"access_token": access_token})
        raise_for_token_status(resp)


async def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Trade a refresh token for a new access token.

    Returns Strava's token response: ``access_token``, ``expires_at`` (a Unix
    timestamp) and, when Strava rotates it, ``refresh_token``. A refresh token
    Strava rejects raises ``StravaUnauthorizedError``. ``transport`` replaces the
    network, e.g. with ``httpx.MockTransport``.
    """
    async with httpx.AsyncClient(timeout=STRAVA_TIMEOUT, transport=transport) as client:
        resp = await client.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        raise_for_token_status(resp)
        return resp.json()


class StravaOAuth(ProviderOAuth):
    """``ProviderOAuth`` for Strava: OAuth 2 authorization codes, without PKCE.

    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    def default_redirect_uri(self) -> str:
        return settings.STRAVA.redirect_uri

    async def start_authorization(self, state: str, redirect_uri: str) -> AuthorizationStart:
        url = build_authorize_url(
            client_id=settings.STRAVA.client_id, redirect_uri=redirect_uri, state=state
        )
        return AuthorizationStart(url=url, secrets={})

    async def exchange(
        self,
        params: Mapping[str, str],
        secrets: dict[str, str],  # noqa: ARG002 - Strava's authorization needs none
    ) -> LinkResult:
        """The athlete and tokens for the callback's ``code``.

        An ``error`` parameter (e.g. ``access_denied``), a missing code or a code Strava
        rejects raises ``ProviderAuthorizationError``; a response without the athlete or
        the tokens ``ProviderResponseError``; another error status, a timeout or a
        connection error ``ProviderUnavailableError``.
        """
        if "error" in params:
            raise ProviderAuthorizationError(f"Strava authorization failed: {params['error']}")
        code = params.get("code")
        if not code:
            raise ProviderAuthorizationError("Strava sent no authorization code")
        try:
            token_data = await exchange_code(
                client_id=settings.STRAVA.client_id,
                client_secret=settings.STRAVA.client_secret,
                code=code,
                transport=self._transport,
            )
        except StravaUnauthorizedError as exc:
            raise ProviderAuthorizationError(describe_error(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc
        except ValueError as exc:
            raise ProviderResponseError("Strava's token response is not JSON") from exc

        if not isinstance(token_data, dict):
            raise ProviderResponseError("Strava's token response is not a JSON object")
        athlete = token_data.get("athlete")
        if not isinstance(athlete, dict) or "id" not in athlete:
            raise ProviderResponseError("Strava did not return athlete information")
        try:
            credentials = ProviderCredentials(
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_at=token_data["expires_at"],
            )
        except KeyError as exc:
            raise ProviderResponseError(f"Strava did not return {exc.args[0]}") from exc
        return LinkResult(provider_user_id=str(athlete["id"]), credentials=credentials)

    async def revoke(self, credentials: ProviderCredentials) -> None:
        """Deauthorize the app. An access token Strava rejects means the authorization is
        already revoked; another error status, a timeout or a connection error raises
        ``ProviderUnavailableError``.
        """
        try:
            await deauthorize(access_token=credentials.access_token, transport=self._transport)
        except StravaUnauthorizedError:
            return
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc


class StravaTokenRefresher(TokenRefresher):
    """``TokenRefresher`` for Strava, whose refresh tokens may rotate on every refresh.

    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``; ``clock``
    gives the current time (timezone-aware).
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._transport = transport
        self._clock = clock

    async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
        """New tokens from ``refresh_access_token``. The refresh token is kept when Strava
        returns none.

        Credentials without a refresh token, or a refresh Strava rejects, raise
        ``ProviderAuthorizationError``; a 429 ``RateLimitedError`` until
        ``rate_limited_until``; another error status, a timeout or a connection error
        ``ProviderUnavailableError``.
        """
        if credentials.refresh_token is None:
            raise ProviderAuthorizationError("No Strava refresh token is stored")
        try:
            token_data = await refresh_access_token(
                client_id=settings.STRAVA.client_id,
                client_secret=settings.STRAVA.client_secret,
                refresh_token=credentials.refresh_token,
                transport=self._transport,
            )
        except StravaUnauthorizedError as exc:
            raise ProviderAuthorizationError(describe_error(exc)) from exc
        except StravaRateLimitedError as exc:
            until = rate_limited_until(exc.usage, self._clock())
            raise RateLimitedError(describe_error(exc), until=until) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc
        except ValueError as exc:
            raise ProviderUnavailableError("Strava's token response is not JSON") from exc
        if not isinstance(token_data, dict) or "access_token" not in token_data:
            raise ProviderUnavailableError("Strava returned no access token")
        return ProviderCredentials(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", credentials.refresh_token),
            expires_at=token_data.get("expires_at", 0),
        )
