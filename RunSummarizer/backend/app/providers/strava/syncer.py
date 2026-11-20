"""Strava's part in syncing a user's runs: listing them."""

from collections.abc import Callable
from datetime import datetime

import httpx

from app.core.clock import utc_now
from app.domain.errors import (
    ProviderAuthorizationError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import (
    Listed,
    ListedActivity,
    ProviderSyncer,
    ResponseObserver,
    SyncWindow,
    describe_error,
)
from app.providers.strava.activity_keys import strava_activity_key
from app.providers.strava.budget import rate_limited_until
from app.providers.strava.client import StravaClient
from app.providers.strava.errors import StravaRateLimitedError, StravaUnauthorizedError


class StravaSyncer(ProviderSyncer):
    """``ProviderSyncer`` for Strava: lists the user's runs.

    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``; ``clock``
    gives the current time.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._transport = transport
        self._clock = clock

    async def start(
        self,
        credentials: ProviderCredentials,
        window: SyncWindow | None,
        limit: int | None,
        on_response: ResponseObserver,
    ) -> Listed:
        """The user's runs in ``window``, or without a window the newest ``limit`` runs.

        Raises ``RateLimitedError`` until ``rate_limited_until`` for a 429;
        ``ProviderAuthorizationError`` for a 401 or 403; and
        ``ProviderUnavailableError`` for another error status, a timeout or a
        connection error.
        """
        try:
            client = StravaClient(
                credentials,
                on_response=on_response,
                transport=self._transport,
                clock=self._clock,
            )
            async with client:
                runs = await client.get_running_activities(
                    after_epoch=int(window.start.timestamp()) if window else None,
                    before_epoch=int(window.end.timestamp()) if window else None,
                    limit=limit,
                )
        except StravaRateLimitedError as exc:
            until = rate_limited_until(exc.usage, self._clock())
            raise RateLimitedError(describe_error(exc), until=until) from exc
        except StravaUnauthorizedError as exc:
            raise ProviderAuthorizationError(describe_error(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc

        return Listed(
            [
                # start_date: ISO 8601 in UTC, e.g. "2026-05-01T06:00:00Z"
                ListedActivity(
                    strava_activity_key(run["id"]), datetime.fromisoformat(run["start_date"])
                )
                for run in runs
            ]
        )
