"""Intervals.icu's part in importing queued activities."""

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
from app.providers.intervals.activity_keys import intervals_activity_id
from app.providers.intervals.budget import rate_limited_until
from app.providers.intervals.client import IntervalsClient
from app.providers.intervals.errors import (
    IntervalsNotFoundError,
    IntervalsRateLimitedError,
    IntervalsUnauthorizedError,
)
from app.providers.intervals.fetch import fetch_intervals_payload
from app.providers.intervals.normalizer import PAYLOAD_FORMAT, normalize_intervals_payload

ITEM_COST = 2  # Intervals.icu calls that fetching an item takes: the activity and the file


class IntervalsImporter(ProviderImporter):
    """``ProviderImporter`` for Intervals.icu. Strava stubs, non-runs and activities
    whose FIT file has no running session are skipped.

    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``; ``clock``
    gives the current time.
    """

    provider = Provider.INTERVALS
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

    def cost(self, item: QueuedItem) -> int:  # noqa: ARG002 - every item costs the same
        return ITEM_COST

    async def fetch(
        self, claim: Claim, credentials: ProviderCredentials, on_response: ResponseObserver
    ) -> dict | None:
        """``fetch_intervals_payload`` for the claimed activity, with the user's
        ``credentials``.

        A 429 raises ``RateLimitedError`` until ``rate_limited_until``; a 401 or 403
        ``ProviderAuthorizationError``; a 404 on the activity
        ``ProviderActivityNotFoundError``; another error status, a timeout or a
        connection error ``ProviderUnavailableError``.
        """
        activity_id = intervals_activity_id(claim.activity_key)
        try:
            client = IntervalsClient(
                credentials, on_response=on_response, transport=self._transport, clock=self._clock
            )
            async with client:
                return await fetch_intervals_payload(client, activity_id)
        except IntervalsRateLimitedError as exc:
            until = rate_limited_until(exc.response, self._clock())
            raise RateLimitedError(describe_error(exc), until=until) from exc
        except IntervalsUnauthorizedError as exc:
            raise ProviderAuthorizationError(describe_error(exc)) from exc
        except IntervalsNotFoundError as exc:
            raise ProviderActivityNotFoundError(describe_error(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc

    def normalize(self, payload: dict) -> NormalizedActivity | None:
        """The activity of a ``fetch_intervals_payload`` payload. An unknown ``format``
        raises ``ValueError``.
        """
        payload_format = payload.get("format", PAYLOAD_FORMAT)
        if payload_format != PAYLOAD_FORMAT:
            raise ValueError(f"unknown Intervals.icu payload format: {payload_format!r}")
        return normalize_intervals_payload(payload)
