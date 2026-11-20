"""GET and PUT /api/v1/users/me/profile."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_user_service, require_user
from app.domain.enums import Sex
from app.domain.errors import HeartRateZonesConflictError
from app.domain.models import UserProfile
from app.main import app

PROFILE = "/api/v1/users/me/profile"
USER_ID = "user-1"

EMPTY = {
    "age": None,
    "sex": None,
    "height_cm": None,
    "max_hr": None,
}

STORED = {
    "age": 32,
    "sex": "male",
    "height_cm": 180.5,
    "max_hr": 190,
}

STORED_PROFILE = UserProfile(age=32, sex=Sex.MALE, height_cm=180.5, max_hr=190)


class FakeUserService:
    """Stands in for ``UserService``: records each call and answers with ``profile``,
    or raises ``error``."""

    def __init__(self):
        self.calls: list[tuple] = []  # (method name, positional args, keyword args)
        self.profile = UserProfile()
        self.error: Exception | None = None

    async def get_profile(self, *args, **kwargs) -> UserProfile:
        self.calls.append(("get_profile", args, kwargs))
        if self.error is not None:
            raise self.error
        return self.profile

    async def replace_profile(self, *args, **kwargs) -> None:
        self.calls.append(("replace_profile", args, kwargs))
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


def get_profile() -> httpx.Response:
    return TestClient(app).get(PROFILE)


def put_profile(body: dict) -> httpx.Response:
    return TestClient(app).put(PROFILE, json=body)


# ---------- GET /me/profile ----------


def test_an_empty_profile_comes_back(service):
    response = get_profile()

    assert response.status_code == 200
    assert response.json() == EMPTY
    assert service.calls == [("get_profile", (USER_ID,), {})]


def test_a_stored_profile_comes_back(service):
    service.profile = STORED_PROFILE

    response = get_profile()

    assert response.status_code == 200
    assert response.json() == STORED
    assert service.calls == [("get_profile", (USER_ID,), {})]


# ---------- PUT /me/profile ----------


def test_a_profile_is_passed_to_the_service(service):
    response = put_profile(STORED)

    assert response.status_code == 200
    assert response.json() == STORED
    assert service.calls == [("replace_profile", (USER_ID, STORED_PROFILE), {})]


def test_omitted_fields_are_passed_as_null(service):
    response = put_profile({"age": 40})

    assert response.status_code == 200
    assert response.json() == {**EMPTY, "age": 40}
    assert service.calls == [("replace_profile", (USER_ID, UserProfile(age=40)), {})]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"age": 100}, id="age above 99"),
        pytest.param({"age": 4}, id="age below 5"),
        pytest.param({"height_cm": 241}, id="height above 240"),
        pytest.param({"height_cm": 49.9}, id="height below 50"),
        pytest.param({"max_hr": -1}, id="negative max hr"),
        pytest.param({"max_hr": 300}, id="max hr above 256"),
        pytest.param({"sex": "other"}, id="invalid sex"),
    ],
)
def test_a_malformed_body_is_rejected(service, body):
    response = put_profile(body)

    assert response.status_code == 422
    assert service.calls == []


def test_a_zone5_conflict_is_a_409(service):
    service.error = HeartRateZonesConflictError(
        "max heart rate must be greater than the zone 5 lower bound"
    )

    response = put_profile({"max_hr": 175})

    assert response.status_code == 409
    assert response.json() == {
        "detail": "max heart rate must be greater than the zone 5 lower bound",
        "code": "hr_zones_conflict",
    }
    assert service.calls == [("replace_profile", (USER_ID, UserProfile(max_hr=175)), {})]
