"""Intervals.icu's part in syncing a user's runs: listing them."""

from collections.abc import Callable
from datetime import datetime, timedelta

import httpx

from app.core.clock import utc_now
from app.domain.errors import ProviderAuthorizationError, ProviderUnavailableError, RateLimitedError
from app.domain.models import ProviderCredentials
from app.providers.base import (
    Listed,
    ListedActivity,
    ProviderSyncer,
    ResponseObserver,
    SyncWindow,
    describe_error,
)
from app.providers.intervals.activity_keys import intervals_activity_key
from app.providers.intervals.budget import rate_limited_until
from app.providers.intervals.client import IntervalsClient
from app.providers.intervals.errors import IntervalsRateLimitedError, IntervalsUnauthorizedError
from app.providers.intervals.normalizer import RUN_TYPES

FIELDS = "id,type,start_date,start_date_local,source"
PAGE_SIZE = 200
EARLIEST = "2000-01-01"
# The largest UTC offset, used to widen a window of UTC instants into one of local
# date-times that is sure to cover it, whatever the athlete's own offset is.
WIDEN = timedelta(hours=14)


def _is_run(activity: dict) -> bool:
    return activity.get("type") in RUN_TYPES


def _local_param(at: datetime) -> str:
    """``at``, a UTC instant, as the naive local-looking date-time Intervals.icu's
    ``oldest``/``newest`` query parameters take."""
    return at.replace(tzinfo=None).isoformat()


def _before(local_iso: str) -> str:
    """A local date-time one second before ``local_iso`` (an activity's
    ``start_date_local``), to page strictly past it."""
    return (datetime.fromisoformat(local_iso) - timedelta(seconds=1)).isoformat()


class IntervalsSyncer(ProviderSyncer):
    """``ProviderSyncer`` for Intervals.icu: lists the user's runs.

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

        Raises ``RateLimitedError`` until ``rate_limited_until``; ``ProviderAuthorizationError``
        for a 401 or 403; and ``ProviderUnavailableError`` for another error status, a
        timeout or a connection error.
        """
        try:
            client = IntervalsClient(
                credentials, on_response=on_response, transport=self._transport, clock=self._clock
            )
            async with client:
                activities = (
                    await self._list_window(client, window)
                    if window is not None
                    else await self._list_newest(client, limit)
                )
        except IntervalsRateLimitedError as exc:
            until = rate_limited_until(exc.response, self._clock())
            raise RateLimitedError(describe_error(exc), until=until) from exc
        except IntervalsUnauthorizedError as exc:
            raise ProviderAuthorizationError(describe_error(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc

        runs = [
            ListedActivity(intervals_activity_key(a["id"]), datetime.fromisoformat(a["start_date"]))
            for a in activities
            if _is_run(a)
            and (
                window is None
                or window.start <= datetime.fromisoformat(a["start_date"]) < window.end
            )
        ]
        if window is None and limit is not None:
            runs = runs[:limit]
        return Listed(runs)

    async def _list_window(self, client: IntervalsClient, window: SyncWindow) -> list[dict]:
        return await client.list_activities(
            oldest=_local_param(window.start - WIDEN),
            newest=_local_param(window.end + WIDEN),
            fields=FIELDS,
        )

    async def _list_newest(self, client: IntervalsClient, limit: int | None) -> list[dict]:
        activities: list[dict] = []
        newest = None
        while True:
            page = await client.list_activities(
                oldest=EARLIEST, newest=newest, limit=PAGE_SIZE, fields=FIELDS
            )
            if not page:
                break
            activities.extend(page)
            runs_found = sum(1 for a in activities if _is_run(a))
            if len(page) < PAGE_SIZE or (limit is not None and runs_found >= limit):
                break
            newest = _before(min(a["start_date_local"] for a in page))
        return activities
