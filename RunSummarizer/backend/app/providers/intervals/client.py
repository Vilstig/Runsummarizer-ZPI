from collections.abc import Callable
from datetime import datetime

import httpx

from app.core.clock import utc_now
from app.domain.models import ProviderCredentials
from app.providers.base import ResponseObserver
from app.providers.intervals.errors import raise_for_api_status
from app.providers.intervals.oauth import INTERVALS_API_BASE, INTERVALS_TIMEOUT

# Intervals.icu sits behind Cloudflare, which may challenge requests using a default
# client user agent.
USER_AGENT = "RunSummarizer/1.0"


class IntervalsClient:
    """Thin async wrapper around the Intervals.icu v1 API, calling it with the access
    token of ``credentials`` as given: it never refreshes the token.

    Use as ``async with IntervalsClient(...) as client:``; leaving closes the HTTP
    connections. Every API response is passed to ``on_response``, with the time its
    request was sent. ``transport`` replaces the network, e.g. with
    ``httpx.MockTransport``; ``clock`` gives the current time (timezone-aware).
    """

    def __init__(
        self,
        credentials: ProviderCredentials,
        *,
        on_response: ResponseObserver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.access_token = credentials.access_token
        self._on_response = on_response
        self._clock = clock
        self._http = httpx.AsyncClient(timeout=INTERVALS_TIMEOUT, transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._http.aclose()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "User-Agent": USER_AGENT}

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        """GET ``url``, pass the response to ``on_response``, then raise if Intervals.icu
        returned an error."""
        sent_at = self._clock()
        resp = await self._http.get(url, headers=self._headers(), params=params)
        if self._on_response is not None:
            await self._on_response(resp, sent_at)
        raise_for_api_status(resp)
        return resp

    async def list_activities(
        self,
        *,
        oldest: str,
        newest: str | None = None,
        limit: int | None = None,
        fields: str = "id,type,start_date,source",
    ) -> list[dict]:
        """``GET /athlete/0/activities``, descending by date. ``oldest`` and ``newest`` are
        local ISO date or date-time strings.
        """
        params: dict = {"oldest": oldest, "fields": fields}
        if newest is not None:
            params["newest"] = newest
        if limit is not None:
            params["limit"] = limit
        resp = await self._get(f"{INTERVALS_API_BASE}/athlete/0/activities", params=params)
        return resp.json()

    async def get_activity(self, activity_id: str) -> dict:
        resp = await self._get(f"{INTERVALS_API_BASE}/activity/{activity_id}")
        return resp.json()

    async def get_activity_file(self, activity_id: str) -> bytes:
        """The athlete's original uploaded file (FIT, GPX or TCX), gzip-compressed.

        Raises ``IntervalsNotFoundError`` when the activity has no file.
        """
        resp = await self._get(f"{INTERVALS_API_BASE}/activity/{activity_id}/file")
        return resp.content

    async def get_activity_fit_file(self, activity_id: str) -> bytes:
        """A FIT file Intervals.icu generated from the activity, laps replaced by its own
        detected intervals.
        """
        resp = await self._get(f"{INTERVALS_API_BASE}/activity/{activity_id}/fit-file")
        return resp.content
