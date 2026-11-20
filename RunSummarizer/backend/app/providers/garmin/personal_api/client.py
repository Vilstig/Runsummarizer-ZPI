from datetime import date
from typing import Self

import httpx

from app.providers.garmin.archive import fit_from_zip
from app.providers.garmin.errors import GarminInvalidResponseError
from app.providers.garmin.personal_api.constants import (
    ACTIVITY_FILE_PATH,
    ACTIVITY_PATH,
    ACTIVITY_SEARCH_PATH,
    GARMIN_PERSONAL_API_BASE,
    GARMIN_TIMEOUT,
)
from app.providers.garmin.personal_api.errors import raise_for_api_status

ZIP_ACCEPT = "application/zip, application/x-zip-compressed, application/octet-stream"


class GarminClient:
    """Thin async wrapper around the Garmin API's activity endpoints.

    Use as ``async with GarminClient(auth) as client:``; leaving closes the HTTP
    connections. ``auth`` signs every request, e.g. ``PersonalApiKeyAuth``. Error
    responses raise as ``raise_for_api_status`` says. ``transport`` replaces the network,
    e.g. with ``httpx.MockTransport``.
    """

    def __init__(
        self,
        auth: httpx.Auth,
        *,
        base_url: str = GARMIN_PERSONAL_API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url, auth=auth, timeout=GARMIN_TIMEOUT, transport=transport
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._http.aclose()

    async def _get(
        self, path: str, *, params: dict | None = None, accept: str = "application/json"
    ) -> httpx.Response:
        resp = await self._http.get(path, params=params, headers={"Accept": accept})
        raise_for_api_status(resp)
        return resp

    async def list_activities(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        *,
        activity_type: str | None = "running",
        limit: int | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        """The account's activity summaries, in the order Garmin lists them.

        ``start_date`` and ``end_date`` bound the activities' calendar dates, both
        inclusive. ``activity_type`` is a Garmin activity type key, None for every type.
        With ``limit``, at most that many are returned.
        """
        if limit is not None:
            page_size = min(page_size, limit)
        params: dict = {"limit": page_size}
        if start_date is not None:
            params["startDate"] = start_date.isoformat()
        if end_date is not None:
            params["endDate"] = end_date.isoformat()
        if activity_type is not None:
            params["activityType"] = activity_type

        activities: list[dict] = []
        while limit is None or len(activities) < limit:
            params["start"] = len(activities)
            resp = await self._get(ACTIVITY_SEARCH_PATH, params=params)
            batch = resp.json() if resp.content else []
            activities.extend(batch)
            if len(batch) < page_size:
                break

        return activities if limit is None else activities[:limit]

    async def get_activity(self, activity_id: int) -> dict:
        """Garmin's JSON for the activity ``activity_id``, as it sends it."""
        resp = await self._get(ACTIVITY_PATH.format(activity_id=activity_id))
        return resp.json()

    async def download_activity_file(self, activity_id: int) -> bytes:
        """The original file of the activity ``activity_id``: a ZIP holding its FIT file.

        An empty response raises ``GarminInvalidResponseError``.
        """
        resp = await self._get(
            ACTIVITY_FILE_PATH.format(activity_id=activity_id), accept=ZIP_ACCEPT
        )
        if not resp.content:
            raise GarminInvalidResponseError(
                f"Garmin sent an empty file for activity {activity_id}"
            )
        return resp.content

    async def download_fit(self, activity_id: int) -> bytes:
        """The FIT file of the activity ``activity_id``, taken out of its download.

        Raises ``GarminUnsupportedFileError`` when the activity's original file isn't a
        FIT file, and ``GarminInvalidResponseError`` when the download is empty, isn't a
        ZIP or holds several FIT files.
        """
        return fit_from_zip(await self.download_activity_file(activity_id))
