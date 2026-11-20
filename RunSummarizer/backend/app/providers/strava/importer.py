"""Strava's part in importing queued activities."""

from collections.abc import Callable
from datetime import datetime

import httpx

from app.core.clock import utc_now
from app.db.protocols.import_queue import Claim, QueuedItem
from app.domain.enums import Provider
from app.domain.errors import (
    ProviderActivityNotFoundError,
    ProviderAuthorizationError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import (
    IMPORT_MAX_ATTEMPTS,
    NormalizedActivity,
    ProviderImporter,
    ResponseObserver,
    describe_error,
)
from app.providers.strava.activity_keys import strava_activity_id
from app.providers.strava.budget import rate_limited_until
from app.providers.strava.client import StravaClient
from app.providers.strava.errors import (
    StravaNotFoundError,
    StravaRateLimitedError,
    StravaUnauthorizedError,
)
from app.providers.strava.fetch import fetch_strava_payload
from app.providers.strava.normalizer import (
    PAYLOAD_FORMAT,
    PAYLOAD_KIND,
    normalize_strava_activity,
    normalize_strava_streams,
)

ITEM_COST = 1  # Strava calls that fetching an item takes: detail and streams
# It should be 2 as we fetch details and streams, but for some reason strava counts it as 1


class StravaImporter(ProviderImporter):
    """``ProviderImporter`` for Strava. Activities that are not Runs are skipped.

    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``; ``clock``
    gives the current time.
    """

    provider = Provider.STRAVA
    single_use_fetch = False
    max_attempts = IMPORT_MAX_ATTEMPTS

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._transport = transport
        self._clock = clock

    def cost(self, item: QueuedItem) -> int:  # noqa: ARG002 - every Strava item costs the same
        return ITEM_COST

    async def fetch(
        self, claim: Claim, credentials: ProviderCredentials, on_response: ResponseObserver
    ) -> dict | None:
        """``fetch_strava_payload`` for the claimed activity, with the user's ``credentials``.

        A 429 raises ``RateLimitedError`` until ``rate_limited_until``; a 401 or 403
        ``ProviderAuthorizationError``; a 404 on the detail ``ProviderActivityNotFoundError``;
        another error status, a timeout or a connection error ``ProviderUnavailableError``.
        """
        try:
            client = StravaClient(
                credentials,
                on_response=on_response,
                transport=self._transport,
                clock=self._clock,
            )
            async with client:
                return await fetch_strava_payload(client, strava_activity_id(claim.activity_key))
        except StravaRateLimitedError as exc:
            until = rate_limited_until(exc.usage, self._clock())
            raise RateLimitedError(describe_error(exc), until=until) from exc
        except StravaUnauthorizedError as exc:
            raise ProviderAuthorizationError(describe_error(exc)) from exc
        except StravaNotFoundError as exc:
            raise ProviderActivityNotFoundError(describe_error(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc

    def normalize(self, payload: dict) -> NormalizedActivity:
        """The activity of a ``fetch_strava_payload`` payload. An untagged payload is
        read as ``PAYLOAD_FORMAT``; any other format raises ``ValueError``.

        The detail is kept as the stored payload, under ``PAYLOAD_KIND``.
        """
        payload_format = payload.get("format", PAYLOAD_FORMAT)
        if payload_format != PAYLOAD_FORMAT:
            raise ValueError(f"unknown Strava payload format: {payload_format!r}")
        detail = payload["detail"]
        return NormalizedActivity(
            activity=normalize_strava_activity(detail, detail.get("laps", [])),
            streams=normalize_strava_streams(payload["streams"]),
            payload_kind=PAYLOAD_KIND,
            stored_payload=detail,
        )
