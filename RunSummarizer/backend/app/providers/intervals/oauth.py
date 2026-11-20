"""Intervals.icu's OAuth endpoints, and the app's authorization built on them.

Intervals.icu issues tokens that never expire and carries no refresh token, so there is
no token refresher: ``ProviderDefinition.token_refresher`` is ``None`` for this provider.
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import AuthorizationStart, LinkResult, ProviderOAuth, describe_error
from app.providers.intervals.errors import (
    IntervalsUnauthorizedError,
    raise_for_api_status,
    raise_for_token_status,
)

INTERVALS_API_BASE = "https://intervals.icu/api/v1"
# Unlike the rest of the API, the token endpoint sits outside /api/v1.
INTERVALS_TOKEN_URL = "https://intervals.icu/api/oauth/token"  # noqa: S105
INTERVALS_AUTHORIZE_URL = "https://intervals.icu/oauth/authorize"
INTERVALS_DISCONNECT_URL = f"{INTERVALS_API_BASE}/disconnect-app"
INTERVALS_TIMEOUT = 30  # seconds, for each phase of an Intervals.icu HTTP request

DEFAULT_SCOPE = "ACTIVITY:READ"
# The scopes that let the app read activities; the user may untick ACTIVITY on the
# consent page and still grant another one.
ACTIVITY_SCOPES = {"ACTIVITY:READ", "ACTIVITY:WRITE"}


def generate_pkce() -> tuple[str, str]:
    """A fresh ``(code_verifier, code_challenge)`` pair, the challenge method being S256,
    the only one Intervals.icu accepts.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str = DEFAULT_SCOPE,
) -> str:
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{INTERVALS_AUTHORIZE_URL}?{params}"


async def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    code_verifier: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Trade an authorization code and its PKCE verifier for an Intervals.icu token and
    the athlete it was granted for.

    A code Intervals.icu rejects raises ``IntervalsUnauthorizedError``. ``transport``
    replaces the network, e.g. with ``httpx.MockTransport``.
    """
    async with httpx.AsyncClient(timeout=INTERVALS_TIMEOUT, transport=transport) as client:
        resp = await client.post(
            INTERVALS_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "code_verifier": code_verifier,
            },
        )
        raise_for_token_status(resp)
        return resp.json()


async def disconnect(
    *, access_token: str, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """Revoke the athlete's authorization of the app, invalidating every token issued for
    it and stopping webhook delivery.

    An access token Intervals.icu rejects raises ``IntervalsUnauthorizedError``.
    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``.
    """
    async with httpx.AsyncClient(timeout=INTERVALS_TIMEOUT, transport=transport) as client:
        resp = await client.delete(
            INTERVALS_DISCONNECT_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        raise_for_api_status(resp)


def _grants_activity_scope(scope: str) -> bool:
    return bool({part.strip() for part in scope.split(",")} & ACTIVITY_SCOPES)


class IntervalsOAuth(ProviderOAuth):
    """``ProviderOAuth`` for Intervals.icu: OAuth 2 with PKCE (S256), no refresh tokens.

    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    def default_redirect_uri(self) -> str:
        return settings.INTERVALS.redirect_uri

    async def start_authorization(self, state: str, redirect_uri: str) -> AuthorizationStart:
        verifier, challenge = generate_pkce()
        url = build_authorize_url(
            client_id=settings.INTERVALS.client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=challenge,
        )
        return AuthorizationStart(url=url, secrets={"code_verifier": verifier})

    async def exchange(self, params, secrets: dict[str, str]) -> LinkResult:
        """The athlete and token for the callback's ``code``, verified with the PKCE
        verifier from ``secrets``.

        An ``error`` parameter, a missing code or verifier, a code Intervals.icu rejects,
        or a granted scope with neither ``ACTIVITY:READ`` nor ``ACTIVITY:WRITE`` raises
        ``ProviderAuthorizationError``; a response without the athlete or the access token
        ``ProviderResponseError``; another error status, a timeout or a connection error
        ``ProviderUnavailableError``.
        """
        if "error" in params:
            raise ProviderAuthorizationError(
                f"Intervals.icu authorization failed: {params['error']}"
            )
        code = params.get("code")
        if not code:
            raise ProviderAuthorizationError("Intervals.icu sent no authorization code")
        code_verifier = secrets.get("code_verifier")
        if not code_verifier:
            raise ProviderAuthorizationError("No PKCE verifier stored for this authorization")
        try:
            token_data = await exchange_code(
                client_id=settings.INTERVALS.client_id,
                client_secret=settings.INTERVALS.client_secret,
                code=code,
                code_verifier=code_verifier,
                transport=self._transport,
            )
        except IntervalsUnauthorizedError as exc:
            raise ProviderAuthorizationError(describe_error(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc
        except ValueError as exc:
            raise ProviderResponseError("Intervals.icu's token response is not JSON") from exc

        if not isinstance(token_data, dict):
            raise ProviderResponseError("Intervals.icu's token response is not a JSON object")
        athlete = token_data.get("athlete")
        if not isinstance(athlete, dict) or "id" not in athlete:
            raise ProviderResponseError("Intervals.icu did not return athlete information")
        access_token = token_data.get("access_token")
        if not access_token:
            raise ProviderResponseError("Intervals.icu did not return an access token")
        if not _grants_activity_scope(token_data.get("scope", "")):
            raise ProviderAuthorizationError(
                f"Intervals.icu granted no activity scope: {token_data.get('scope')!r}"
            )
        return LinkResult(
            provider_user_id=str(athlete["id"]),
            credentials=ProviderCredentials(
                access_token=access_token, refresh_token=None, expires_at=None
            ),
        )

    async def revoke(self, credentials: ProviderCredentials) -> None:
        """Disconnect the app. An access token Intervals.icu rejects means the
        authorization is already revoked; another error status, a timeout or a connection
        error raises ``ProviderUnavailableError``.
        """
        try:
            await disconnect(access_token=credentials.access_token, transport=self._transport)
        except IntervalsUnauthorizedError:
            return
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc
