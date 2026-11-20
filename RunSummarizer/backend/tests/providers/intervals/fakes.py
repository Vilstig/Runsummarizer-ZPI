"""Intervals.icu API stand-in and sample data for the provider tests."""

import re

import httpx

from app.domain.models import RateLimitUsage, WindowUsage


def intervals_usage(used_15m: int, used_day: int, limit_15m: int, limit_day: int) -> RateLimitUsage:
    """Intervals.icu's rolling 15-minute and daily usage."""
    return RateLimitUsage(
        {
            "15m": WindowUsage(used=used_15m, limit=limit_15m),
            "day": WindowUsage(used=used_day, limit=limit_day),
        }
    )


def intervals_activity(
    activity_id: str = "i7",
    *,
    activity_type: str = "Run",
    start_date: str = "2026-05-01T06:00:00Z",
    start_date_local: str = "2026-05-01T08:00:00",
    timezone: str = "Europe/Warsaw",
    name: str = "Morning Run",
    source: str = "GARMIN_CONNECT",
    file_type: str | None = "fit",
) -> dict:
    """An Intervals.icu activity detail, as ``GET /activity/{id}`` returns it."""
    activity = {
        "id": activity_id,
        "type": activity_type,
        "name": name,
        "start_date": start_date,
        "start_date_local": start_date_local,
        "timezone": timezone,
        "source": source,
    }
    if file_type is not None:
        activity["file_type"] = file_type
    return activity


def strava_stub(activity_id: str = "i9", *, start_date_local: str = "2026-05-01T08:00:00") -> dict:
    """A Strava-sourced activity, as Intervals.icu hands it out: a stub without a type."""
    return {
        "id": activity_id,
        "icu_athlete_id": "2049151",
        "start_date_local": start_date_local,
        "source": "STRAVA",
        "_note": "Strava activities are not available through the API",
    }


class FakeIntervals:
    """Intervals.icu API stand-in serving the activities ``add`` is given."""

    _ACTIVITY_PATH = re.compile(r"/api/v1/activity/([^/]+)(/file|/fit-file)?")

    def __init__(self):
        self.activities: dict[str, dict] = {}  # activity id -> detail
        self.files: dict[str, bytes] = {}  # activity id -> original file bytes
        self.fit_files: dict[str, bytes] = {}  # activity id -> generated FIT file bytes
        # URL path -> HTTP status to answer with, or an exception to raise
        self.failures: dict[str, int | BaseException] = {}
        self.usage: RateLimitUsage | None = None  # reported with every API response
        self.retry_after: int | None = None  # Retry-After seconds on a 429
        self.requests: list[httpx.Request] = []

    def add(
        self, activity: dict, *, file: bytes | None = None, fit_file: bytes | None = None
    ) -> None:
        """Serve ``activity``, with its original ``file`` and/or ``fit_file`` fallback."""
        activity_id = str(activity["id"])
        self.activities[activity_id] = activity
        if file is not None:
            self.files[activity_id] = file
        if fit_file is not None:
            self.fit_files[activity_id] = fit_file

    def fail(self, path: str, outcome: int | BaseException) -> None:
        self.failures[path] = outcome

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self._respond(request)
        if self.usage is not None and request.url.path.startswith("/api/v1/"):
            fifteen, day = self.usage.windows["15m"], self.usage.windows["day"]
            response.headers["X-RateLimit-Limit"] = f"{fifteen.limit},{day.limit}"
            response.headers["X-RateLimit-Remaining"] = (
                f"{fifteen.limit - fifteen.used},{day.limit - day.used}"
            )
        if response.status_code == 429 and self.retry_after is not None:
            response.headers["Retry-After"] = str(self.retry_after)
        return response

    def _respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self.failures:
            outcome = self.failures[path]
            if isinstance(outcome, BaseException):
                raise outcome
            return httpx.Response(outcome)
        if path == "/api/v1/disconnect-app":
            return httpx.Response(200, json={})
        if path == "/api/v1/athlete/0/activities":
            return httpx.Response(200, json=self._list(dict(request.url.params)))
        match = self._ACTIVITY_PATH.fullmatch(path)
        if match:
            activity_id, suffix = match[1], match[2]
            if activity_id not in self.activities:
                return httpx.Response(404)
            if suffix == "/file":
                if activity_id not in self.files:
                    return httpx.Response(404)
                return httpx.Response(200, content=self.files[activity_id])
            if suffix == "/fit-file":
                if activity_id not in self.fit_files:
                    return httpx.Response(404)
                return httpx.Response(200, content=self.fit_files[activity_id])
            return httpx.Response(200, json=self.activities[activity_id])
        return httpx.Response(404)

    def _list(self, params: dict) -> list[dict]:
        """Filter and page ``self.activities`` the way Intervals.icu's listing does: by
        ``start_date_local``, newest first, bounded to ``limit`` entries.
        """
        oldest, newest, limit = params.get("oldest"), params.get("newest"), params.get("limit")
        activities = [
            a
            for a in self.activities.values()
            if (oldest is None or a.get("start_date_local", "") >= oldest)
            and (newest is None or a.get("start_date_local", "") <= newest)
        ]
        activities.sort(key=lambda a: a.get("start_date_local", ""), reverse=True)
        return activities[: int(limit)] if limit is not None else activities
