"""Garmin's OAuth 2 endpoints with PKCE, and the app's authorization, token refresh and
deregistration built on them.
"""

import base64
import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from urllib.parse import urlencode, urlsplit

import anyio
import httpx

from app.config import settings
from app.core.clock import utc_now
from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderError,
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
from app.providers.garmin.budget import rate_limited_until
from app.providers.garmin.constants import (
    ACTIVITY_EXPORT_PERMISSION,
    GARMIN_AUTHORIZE_URL,
    GARMIN_TIMEOUT,
    GARMIN_TOKEN_URL,
    GARMIN_USER_ID_URL,
    GARMIN_USER_PERMISSIONS_URL,
    GARMIN_USER_REGISTRATION_URL,
    USER_CALL_RETRY_DELAYS_S,
)
from app.providers.garmin.errors import (
    INVALID_GRANT,
    TOKEN_ERROR_MAX_BYTES,
    GarminRateLimitedError,
    GarminTokenRejectedError,
    GarminUnauthorizedError,
    raise_for_api_status,
    raise_for_token_status,
)

logger = logging.getLogger(__name__)

# seconds taken off a token's lifetime, so it is refreshed before Garmin expires it
EXPIRY_MARGIN_S = 300

CODE_VERIFIER = "code_verifier"  # the key of the PKCE verifier in the secrets
REDIRECT_URI = "redirect_uri"  # the key of the authorization's redirect URI in the secrets


def pkce_pair() -> tuple[str, str]:
    """A new PKCE ``(verifier, challenge)``: the challenge is the unpadded base64url
    SHA-256 of the verifier (``S256``).
    """
    verifier = secrets.token_urlsafe(64)
    return verifier, code_challenge(verifier)


def code_challenge(verifier: str) -> str:
    """The ``S256`` challenge of the PKCE ``verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorize_url(*, client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    params = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{GARMIN_AUTHORIZE_URL}?{params}"


def _credentials(token_data: object, now: datetime) -> ProviderCredentials:
    """The credentials in a token response received at ``now``.

    Raises ``ProviderResponseError`` when it lacks the tokens or their lifetime.
    """
    if not isinstance(token_data, dict):
        raise ProviderResponseError("Garmin's token response is not a JSON object")
    try:
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = int(token_data["expires_in"])  # seconds
    except KeyError as exc:
        raise ProviderResponseError(f"Garmin did not return {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise ProviderResponseError("Garmin returned an invalid expires_in") from exc
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise ProviderResponseError("Garmin returned tokens that aren't strings")
    return ProviderCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=int(now.timestamp()) + expires_in - EXPIRY_MARGIN_S,
    )


class GarminOAuth(ProviderOAuth):
    """``ProviderOAuth`` for Garmin: OAuth 2 authorization codes with PKCE.

    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``; ``clock``
    gives the current time (timezone-aware); ``sleep`` waits the given seconds between
    retries.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ):
        self._transport = transport
        self._clock = clock
        self._sleep = sleep

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=GARMIN_TIMEOUT, transport=self._transport)

    def default_redirect_uri(self) -> str:
        return settings.GARMIN.redirect_uri

    async def start_authorization(self, state: str, redirect_uri: str) -> AuthorizationStart:
        """The consent URL with a new PKCE challenge. The secrets hold its verifier and
        the redirect URI, which the token request repeats.
        """
        verifier, challenge = pkce_pair()
        url = build_authorize_url(
            client_id=settings.GARMIN.client_id,
            redirect_uri=redirect_uri,
            state=state,
            challenge=challenge,
        )
        return AuthorizationStart(
            url=url, secrets={CODE_VERIFIER: verifier, REDIRECT_URI: redirect_uri}
        )

    async def exchange(self, params: Mapping[str, str], secrets: dict[str, str]) -> LinkResult:
        """The Garmin user and tokens for the callback's ``code``.

        An ``error`` parameter, a missing code or verifier, a code Garmin rejects with
        ``invalid_grant``, or a user who didn't grant ``ACTIVITY_EXPORT`` raises
        ``ProviderAuthorizationError``; the last is deregistered first, as far as Garmin
        answers. The user id and permissions calls are retried after each of
        ``USER_CALL_RETRY_DELAYS_S`` while they answer 403. A response without the tokens
        or the user id raises ``ProviderResponseError``; a token rejection with another
        OAuth error code or none, another error status, a timeout or a connection error
        ``ProviderUnavailableError``.
        """
        if "error" in params:
            raise ProviderAuthorizationError(f"Garmin authorization failed: {params['error']}")
        code = params.get("code")
        if not code:
            raise ProviderAuthorizationError("Garmin sent no authorization code")
        verifier = secrets.get(CODE_VERIFIER)
        if not verifier:
            raise ProviderAuthorizationError("The PKCE verifier of the authorization is missing")
        redirect_uri = secrets.get(REDIRECT_URI) or self.default_redirect_uri()

        async with self._client() as client:
            credentials = await self._token_request(
                client,
                {
                    "grant_type": "authorization_code",
                    "client_id": settings.GARMIN.client_id,
                    "client_secret": settings.GARMIN.client_secret,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                },
            )
            user_id = await self._user_id(client, credentials)
            permissions = await self._permissions(client, credentials)
            if ACTIVITY_EXPORT_PERMISSION not in permissions:
                await self._deregister_quietly(client, credentials)
                raise ProviderAuthorizationError(
                    f"The Garmin user did not grant {ACTIVITY_EXPORT_PERMISSION}"
                )
        return LinkResult(provider_user_id=user_id, credentials=credentials)

    async def revoke(self, credentials: ProviderCredentials) -> None:
        """Deregister the user. A 401, 403 or 412 means Garmin no longer knows the
        registration; another error status, a timeout or a connection error raises
        ``ProviderUnavailableError``.
        """
        try:
            async with self._client() as client:
                await self._deregister(client, credentials)
        except GarminUnauthorizedError:
            return
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc

    async def _token_request(self, client: httpx.AsyncClient, data: dict) -> ProviderCredentials:
        now = self._clock()
        try:
            response = await post_token_request(client, data)
            token_data = response.json()
        except GarminTokenRejectedError as exc:
            raise token_rejection(exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc
        except ValueError as exc:
            raise ProviderResponseError("Garmin's token response is not JSON") from exc
        return _credentials(token_data, now)

    async def _get_json(
        self, client: httpx.AsyncClient, url: str, credentials: ProviderCredentials
    ) -> object:
        """The JSON body of a user call, retried after each of
        ``USER_CALL_RETRY_DELAYS_S`` while it answers 403.
        """
        for delay in USER_CALL_RETRY_DELAYS_S:
            response = await self._get(client, url, credentials)
            if response.status_code != 403:
                break
            logger.info("garmin: %s answered 403; retrying in %ss", urlsplit(url).path, delay)
            await self._sleep(delay)
        else:
            response = await self._get(client, url, credentials)
        try:
            raise_for_api_status(response)
            return response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc
        except ValueError as exc:
            raise ProviderResponseError(f"Garmin's {url} response is not JSON") from exc

    async def _get(
        self, client: httpx.AsyncClient, url: str, credentials: ProviderCredentials
    ) -> httpx.Response:
        try:
            return await client.get(url, headers=_bearer(credentials))
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc

    async def _user_id(self, client: httpx.AsyncClient, credentials: ProviderCredentials) -> str:
        data = await self._get_json(client, GARMIN_USER_ID_URL, credentials)
        user_id = data.get("userId") if isinstance(data, dict) else None
        if not isinstance(user_id, str | int) or isinstance(user_id, bool) or user_id == "":
            raise ProviderResponseError("Garmin did not return the user id")
        return str(user_id)

    async def _permissions(
        self, client: httpx.AsyncClient, credentials: ProviderCredentials
    ) -> list[str]:
        data = await self._get_json(client, GARMIN_USER_PERMISSIONS_URL, credentials)
        # an object whose "permissions" key lists the granted permission names
        permissions = data.get("permissions") if isinstance(data, dict) else None
        if not isinstance(permissions, list):
            raise ProviderResponseError("Garmin's permissions response has no permissions list")
        return [permission for permission in permissions if isinstance(permission, str)]

    async def _deregister(
        self, client: httpx.AsyncClient, credentials: ProviderCredentials
    ) -> None:
        response = await client.delete(GARMIN_USER_REGISTRATION_URL, headers=_bearer(credentials))
        raise_for_api_status(response)

    async def _deregister_quietly(
        self, client: httpx.AsyncClient, credentials: ProviderCredentials
    ) -> None:
        try:
            await self._deregister(client, credentials)
        except httpx.HTTPError as exc:
            logger.warning("garmin: deregistering a user without activity access failed: %s", exc)


class GarminTokenRefresher(TokenRefresher):
    """``TokenRefresher`` for Garmin, which replaces the refresh token on every refresh.

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
        """New tokens, the refresh token included.

        Credentials without a refresh token, or a refresh token Garmin rejects as
        ``invalid_grant``, raise ``ProviderAuthorizationError``; a 429 ``RateLimitedError``
        until ``rate_limited_until``; a request Garmin rejects otherwise
        (``token_rejection``), another error status, a timeout, a connection error or a
        response without the tokens ``ProviderUnavailableError``.
        """
        if credentials.refresh_token is None:
            raise ProviderAuthorizationError("No Garmin refresh token is stored")
        now = self._clock()
        try:
            async with httpx.AsyncClient(
                timeout=GARMIN_TIMEOUT, transport=self._transport
            ) as client:
                response = await post_token_request(
                    client,
                    {
                        "grant_type": "refresh_token",
                        "client_id": settings.GARMIN.client_id,
                        "client_secret": settings.GARMIN.client_secret,
                        "refresh_token": credentials.refresh_token,
                    },
                )
                token_data = response.json()
        except GarminTokenRejectedError as exc:
            raise token_rejection(exc) from exc
        except GarminRateLimitedError as exc:
            until = rate_limited_until(self._clock(), exc.retry_after)
            raise RateLimitedError(describe_error(exc), until=until) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc
        except ValueError as exc:
            raise ProviderUnavailableError("Garmin's token response is not JSON") from exc
        try:
            return _credentials(token_data, now)
        except ProviderResponseError as exc:
            raise ProviderUnavailableError(str(exc)) from exc


async def post_token_request(client: httpx.AsyncClient, data: dict) -> httpx.Response:
    """POST ``data`` to Garmin's token endpoint; the response, read in full once it
    succeeded. An error status raises as ``raise_for_token_status`` does, after reading
    no more of the body than its OAuth error code needs.
    """
    async with client.stream("POST", GARMIN_TOKEN_URL, data=data) as response:
        if not response.is_success:
            error_body = await _read_prefix(response, TOKEN_ERROR_MAX_BYTES + 1)
            raise_for_token_status(response, error_body)
        await response.aread()
    return response


async def _read_prefix(response: httpx.Response, max_bytes: int) -> bytes:
    """The body's first ``max_bytes`` bytes, or all of it when it is shorter."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= max_bytes:
            break
    return b"".join(chunks)[:max_bytes]


def token_rejection(exc: GarminTokenRejectedError) -> ProviderError:
    """The error for a token request Garmin rejected with a 400 or 401.

    ``invalid_grant`` means the user's authorization code or refresh token no longer
    works: ``ProviderAuthorizationError``. Any other OAuth error code, or none, means
    Garmin refused the app's own request or credentials (e.g. ``invalid_client``): an
    error is logged, and the user's authorization is not in question
    (``ProviderUnavailableError``).
    """
    if exc.error_code == INVALID_GRANT:
        return ProviderAuthorizationError(describe_error(exc))
    logger.error(
        "garmin: the token endpoint refused the app's request with %d (%s)",
        exc.response.status_code,
        exc.error_code or "no error code",
    )
    return ProviderUnavailableError(describe_error(exc))


def _bearer(credentials: ProviderCredentials) -> dict[str, str]:
    return {"Authorization": f"Bearer {credentials.access_token}"}
