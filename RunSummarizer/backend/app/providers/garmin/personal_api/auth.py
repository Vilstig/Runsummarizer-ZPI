"""Signing Garmin API requests with an access token traded for a Personal API key."""

import base64
import binascii
import json
import time
from collections.abc import Callable, Generator

import httpx

from app.providers.garmin.errors import GarminInvalidResponseError
from app.providers.garmin.personal_api.constants import GARMIN_PERSONAL_API_BASE, TOKEN_PATH
from app.providers.garmin.personal_api.errors import raise_for_token_status

RENEW_MARGIN_S = 3600  # seconds before expiry at which the key is traded for a new token


class PersonalApiKeyAuth(httpx.Auth):
    """``httpx.Auth`` that sends requests with a bearer token traded for a Personal API key.

    The key is traded at Garmin's token endpoint for a JWT access token, valid for up to
    24 hours and without a refresh token. The token is kept in memory and traded for
    again once it expires within ``RENEW_MARGIN_S``. A request answered with 401 is sent
    once more with a newly traded token, unless its token was just traded. A key Garmin
    rejects raises ``GarminUnauthorizedError``; a token response that isn't a JWT with an
    ``exp`` claim raises ``GarminInvalidResponseError``. Concurrent requests may each
    trade the key when the token is due. ``clock`` gives the current Unix time.
    """

    requires_response_body = True

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = GARMIN_PERSONAL_API_BASE,
        clock: Callable[[], float] = time.time,
    ):
        if not api_key:
            raise ValueError("A Garmin Personal API key is required")
        self._api_key = api_key
        self._token_url = f"{base_url.rstrip('/')}{TOKEN_PATH}"
        self._clock = clock
        self._access_token: str | None = None
        self._expires_at: float = 0  # Unix timestamp

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        traded = False
        if self._access_token is None or self._expires_at - self._clock() < RENEW_MARGIN_S:
            yield from self._trade_key()
            traded = True

        request.headers["Authorization"] = f"Bearer {self._access_token}"
        response = yield request

        if response.status_code == 401 and not traded:
            yield from self._trade_key()
            request.headers["Authorization"] = f"Bearer {self._access_token}"
            yield request

    def _trade_key(self) -> Generator[httpx.Request, httpx.Response]:
        response = yield httpx.Request(
            "POST",
            self._token_url,
            headers={"Accept": "*/*", "Authorization": f"ApiKey {self._api_key}"},
        )
        raise_for_token_status(response)
        access_token = response.text.strip()
        self._expires_at = jwt_expiry(access_token)
        self._access_token = access_token


def jwt_expiry(token: str) -> float:
    """The ``exp`` claim of the JWT ``token``, a Unix timestamp; the signature isn't checked.

    Raises ``GarminInvalidResponseError`` when ``token`` isn't a JWT with an ``exp`` claim.
    """
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return float(claims["exp"])
    except (IndexError, KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise GarminInvalidResponseError(
            "Garmin's token endpoint did not return a JWT with an exp claim"
        ) from exc
