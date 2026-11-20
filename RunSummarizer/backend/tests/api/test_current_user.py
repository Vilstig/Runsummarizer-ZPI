"""``require_user``: Clerk session tokens, and requests with none."""

import asyncio
import inspect

import pytest
from clerk_backend_api.security.types import (
    AuthStatus,
    RequestState,
    TokenVerificationErrorReason,
)
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service, require_user
from app.main import app
from tests.helpers import EmptyActivityService, make_request

_CREDS = HTTPAuthorizationCredentials(scheme="Bearer", credentials="session")
ACTIVITIES = "/api/v1/activities"


def _configure(monkeypatch, *, jwt_key: str = ""):
    monkeypatch.setattr("app.core.clerk_auth.CLERK_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr("app.core.clerk_auth.CLERK_JWT_KEY", jwt_key)
    monkeypatch.setattr("app.core.clerk_auth.CLERK_AUTHORIZED_PARTIES", ["http://localhost:3000"])


def _session_request():
    return make_request(headers=[(b"authorization", b"Bearer session")])


@pytest.fixture
def client():
    app.dependency_overrides[get_activity_service] = lambda: EmptyActivityService()
    yield TestClient(app)
    app.dependency_overrides.pop(get_activity_service, None)


def test_missing_bearer_is_401():
    parameter = inspect.signature(require_user).parameters["_creds"]
    bearer = parameter.default.dependency

    with pytest.raises(HTTPException) as raised:
        asyncio.run(bearer(make_request()))

    exc = raised.value
    assert exc.status_code == 401
    assert exc.detail == "Not authenticated"
    assert exc.headers == {"WWW-Authenticate": "Bearer"}


def test_missing_authorization_header_is_401(client):
    response = client.get(ACTIVITIES)

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_returns_clerk_subject(monkeypatch):
    captured = {}

    def fake_authenticate(request, options):
        captured["options"] = options
        return RequestState(
            status=AuthStatus.SIGNED_IN,
            token="session",
            payload={"sub": "user_abc"},
        )

    _configure(
        monkeypatch,
        jwt_key="-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----",
    )
    monkeypatch.setattr("app.core.clerk_auth.authenticate_request", fake_authenticate)

    user_id = require_user(_session_request(), _CREDS)

    assert user_id == "user_abc"
    assert captured["options"].accepts_token == ["session_token"]
    assert captured["options"].authorized_parties == ["http://localhost:3000"]
    assert captured["options"].secret_key == "sk_test_x"
    assert captured["options"].jwt_key.startswith("-----BEGIN PUBLIC KEY-----")


def test_rejected_session_is_401(monkeypatch):
    def fake_authenticate(request, options):
        return RequestState(
            status=AuthStatus.SIGNED_OUT,
            reason=TokenVerificationErrorReason.TOKEN_EXPIRED,
        )

    _configure(monkeypatch)
    monkeypatch.setattr("app.core.clerk_auth.authenticate_request", fake_authenticate)

    with pytest.raises(HTTPException) as raised:
        require_user(_session_request(), _CREDS)

    exc = raised.value
    assert exc.status_code == 401
    assert exc.detail == TokenVerificationErrorReason.TOKEN_EXPIRED.value[1]
    assert exc.headers == {"WWW-Authenticate": "Bearer"}


def test_signed_out_without_a_message_is_401(monkeypatch):
    def fake_authenticate(request, options):
        return RequestState(status=AuthStatus.SIGNED_OUT)

    monkeypatch.setattr("app.core.clerk_auth.authenticate_request", fake_authenticate)

    with pytest.raises(HTTPException) as raised:
        require_user(_session_request(), _CREDS)

    exc = raised.value
    assert exc.status_code == 401
    assert exc.detail == "Not authenticated"
    assert exc.headers == {"WWW-Authenticate": "Bearer"}


def test_rejected_token_is_401(client, fake_clerk):
    fake_clerk()

    response = client.get(ACTIVITIES, headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401
    assert response.json()["detail"] == TokenVerificationErrorReason.TOKEN_INVALID.value[1]
    assert response.headers["www-authenticate"] == "Bearer"
