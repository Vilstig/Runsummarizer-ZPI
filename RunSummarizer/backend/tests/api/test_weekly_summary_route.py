"""GET /api/v1/activities/weekly-summary: query params reach the service, the response
is each week's totals in order, and the route isn't captured by GET /activities/{id}."""

from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service, require_user
from app.domain.models import WeekTotals
from app.main import app

WEEKLY_SUMMARY = "/api/v1/activities/weekly-summary"
USER_ID = "user-1"


class FakeActivityService:
    """Stands in for ``ActivityService``: records each call and answers with ``weeks``."""

    def __init__(self):
        self.calls: list[dict] = []
        self.weeks: list[WeekTotals] = []

    async def weekly_summary(self, **kwargs) -> list[WeekTotals]:
        self.calls.append(kwargs)
        return self.weeks


@pytest.fixture(autouse=True)
def current_user():
    app.dependency_overrides[require_user] = lambda: USER_ID
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def service():
    fake = FakeActivityService()
    app.dependency_overrides[get_activity_service] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_activity_service, None)


def weekly_summary(**params) -> httpx.Response:
    return TestClient(app).get(WEEKLY_SUMMARY, params=params)


def test_defaults_are_12_weeks_ending_today(service):
    response = weekly_summary()

    assert response.status_code == 200
    assert service.calls == [{"weeks": 12, "as_of": None, "user_id": USER_ID}]


def test_weeks_and_date_are_passed_to_the_service(service):
    response = weekly_summary(weeks=4, date="2026-11-19")

    assert response.status_code == 200
    assert service.calls == [{"weeks": 4, "as_of": date(2026, 11, 19), "user_id": USER_ID}]


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"weeks": 0}, id="weeks too small"),
        pytest.param({"weeks": 53}, id="weeks too large"),
        pytest.param({"date": "2026-13-01"}, id="invalid date"),
    ],
)
def test_an_invalid_query_is_rejected(service, params):
    response = weekly_summary(**params)

    assert response.status_code == 422
    assert service.calls == []


def test_the_weeks_come_back_in_the_services_order(service):
    service.weeks = [
        WeekTotals(date(2026, 11, 2), distance=5000.0, duration=1800.0, elevation_gain=50.0),
        WeekTotals(date(2026, 11, 9), distance=0.0, duration=0.0, elevation_gain=0.0),
    ]

    response = weekly_summary()

    assert response.status_code == 200
    assert response.json() == {
        "weeks": [
            {
                "weekStart": "2026-11-02",
                "distance": 5000.0,
                "duration": 1800.0,
                "elevationGain": 50.0,
            },
            {
                "weekStart": "2026-11-09",
                "distance": 0.0,
                "duration": 0.0,
                "elevationGain": 0.0,
            },
        ]
    }


def test_the_route_is_not_captured_by_the_single_activity_route(service):
    """'weekly-summary' must not be read as an {activity_id} path parameter."""
    response = weekly_summary()

    assert response.status_code == 200
    assert service.calls  # the weekly-summary route's service was called, not get_activity's
