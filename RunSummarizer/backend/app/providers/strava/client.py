from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Self

import httpx

from app.core.clock import utc_now
from app.domain.models import ProviderCredentials
from app.providers.base import ResponseObserver
from app.providers.strava.budget import rate_limit_usage
from app.providers.strava.errors import raise_for_api_status
from app.providers.strava.oauth import STRAVA_API_BASE, STRAVA_TIMEOUT


class StravaClient:
    """Thin async wrapper around the Strava v3 REST API, calling it with the access token
    of ``credentials`` as given: it never refreshes the token.

    Use as ``async with StravaClient(...) as client:``; leaving closes the HTTP
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
        self._http = httpx.AsyncClient(timeout=STRAVA_TIMEOUT, transport=transport)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._http.aclose()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        """GET ``url``, pass the response to ``on_response``, then raise if Strava
        returned an error."""
        sent_at = self._clock()
        resp = await self._http.get(url, headers=self._headers(), params=params)
        if self._on_response is not None:
            await self._on_response(resp, sent_at)
        raise_for_api_status(resp, rate_limit_usage(resp.headers))
        return resp

    async def get_running_activities(
        self,
        after_epoch: int | None = None,
        before_epoch: int | None = None,
        limit: int | None = None,
        per_page: int = 200,
    ) -> list:
        activities = []
        page = 1
        if limit is not None:
            per_page = min(per_page, limit * 2)
        params = {"per_page": per_page}
        if after_epoch:
            params["after"] = after_epoch
        if before_epoch:
            params["before"] = before_epoch

        while limit is None or len(activities) < limit:
            params["page"] = page
            resp = await self._get(f"{STRAVA_API_BASE}/athlete/activities", params=params)
            batch = resp.json()
            activities.extend(a for a in batch if a.get("type") == "Run")
            if len(batch) < per_page:
                break
            page += 1

        return activities if limit is None else activities[:limit]

    async def get_activity_detail(self, activity_id: int) -> dict:
        resp = await self._get(f"{STRAVA_API_BASE}/activities/{activity_id}")
        return resp.json()

    async def get_activity_streams(self, activity_id: int, keys: Iterable[str]) -> dict:
        """``{key: samples}`` for each of the stream ``keys`` the activity has, in one call.

        Strava leaves out streams the activity doesn't have, e.g. ``heartrate`` without
        a heart-rate sensor.
        """
        keys = list(keys)
        resp = await self._get(
            f"{STRAVA_API_BASE}/activities/{activity_id}/streams",
            params={"keys": ",".join(keys), "key_by_type": "true"},
        )
        data = resp.json()
        return {key: data[key]["data"] for key in keys if key in data}
