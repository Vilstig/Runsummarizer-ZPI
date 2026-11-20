"""GET and PUT /api/v1/users/me/hr-zones."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_user_service, require_user
from app.domain.errors import HeartRateZonesConflictError
from app.domain.models import HeartRateZones
from app.main import app

HR_ZONES = "/api/v1/users/me/hr-zones"
USER_ID = "user-1"

ZONES = {"zone1_bpm": 100, "zone2_bpm": 120, "zone3_bpm": 140, "zone4_bpm": 160, "zone5_bpm": 175}
ZONES_MODEL = HeartRateZones(
    zone1_bpm=100, zone2_bpm=120, zone3_bpm=140, zone4_bpm=160, zone5_bpm=175
)


class FakeUserService:
    """Stands in for ``UserService``: records each call and answers with ``zones``,
    or raises ``error``."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.zones: HeartRateZones | None = None
        self.error: Exception | None = None

    async def get_hr_zones(self, *args, **kwargs) -> HeartRateZones | None:
        self.calls.append(("get_hr_zones", args, kwargs))
        if self.error is not None:
            raise self.error
        return self.zones

    async def replace_hr_zones(self, *args, **kwargs) -> None:
        self.calls.append(("replace_hr_zones", args, kwargs))
        if self.error is not None:
            raise self.error


@pytest.fixture(autouse=True)
def current_user():
    app.dependency_overrides[require_user] = lambda: USER_ID
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def service():
    fake = FakeUserService()
    app.dependency_overrides[get_user_service] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_user_service, None)


def get_hr_zones() -> httpx.Response:
    return TestClient(app).get(HR_ZONES)


def put_hr_zones(body: dict) -> httpx.Response:
    return TestClient(app).put(HR_ZONES, json=body)


# ---------- GET /me/hr-zones ----------


def test_missing_zones_come_back_as_null(service):
    response = get_hr_zones()

    assert response.status_code == 200
    assert response.json() is None
    assert service.calls == [("get_hr_zones", (USER_ID,), {})]


def test_the_zones_come_back(service):
    service.zones = ZONES_MODEL

    response = get_hr_zones()

    assert response.status_code == 200
    assert response.json() == ZONES
    assert service.calls == [("get_hr_zones", (USER_ID,), {})]


# ---------- PUT /me/hr-zones ----------


def test_the_zones_are_passed_to_the_service(service):
    response = put_hr_zones(ZONES)

    assert response.status_code == 200
    assert response.json() == ZONES
    assert service.calls == [("replace_hr_zones", (USER_ID, ZONES_MODEL), {})]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**ZONES, "zone2_bpm": 90}, id="bounds out of order"),
        pytest.param({**ZONES, "zone3_bpm": 120}, id="equal bounds"),
        pytest.param(
            {key: value for key, value in ZONES.items() if key != "zone4_bpm"},
            id="missing bound",
        ),
        pytest.param({**ZONES, "zone1_bpm": -1}, id="negative bound"),
        pytest.param({**ZONES, "zone5_bpm": 300}, id="bound above 256"),
    ],
)
def test_a_malformed_body_is_rejected(service, body):
    response = put_hr_zones(body)

    assert response.status_code == 422
    assert service.calls == []


def test_a_zone5_conflict_is_a_409(service):
    service.error = HeartRateZonesConflictError(
        "max heart rate must be greater than the zone 5 lower bound"
    )

    response = put_hr_zones(ZONES)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "max heart rate must be greater than the zone 5 lower bound",
        "code": "hr_zones_conflict",
    }
    assert service.calls == [("replace_hr_zones", (USER_ID, ZONES_MODEL), {})]
