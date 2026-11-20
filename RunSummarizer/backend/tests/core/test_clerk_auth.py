"""Clerk session verification: options forwarded to the SDK, and the per-request cache."""

from clerk_backend_api.security.types import AuthStatus, RequestState
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service
from app.core.clerk_auth import authenticate_clerk_request
from app.main import app
from tests.helpers import EmptyActivityService, make_request

JWT_KEY = "-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----"


def _install(monkeypatch, calls: list) -> None:
    monkeypatch.setattr("app.core.clerk_auth.CLERK_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr("app.core.clerk_auth.CLERK_JWT_KEY", JWT_KEY)
    monkeypatch.setattr("app.core.clerk_auth.CLERK_AUTHORIZED_PARTIES", ["http://localhost:3000"])

    def fake_authenticate(request, options):
        calls.append(options)
        return RequestState(
            status=AuthStatus.SIGNED_IN,
            token="session",
            payload={"sub": "user_abc"},
        )

    monkeypatch.setattr("app.core.clerk_auth.authenticate_request", fake_authenticate)


def test_passes_clerk_options_to_the_sdk(monkeypatch):
    calls = []
    _install(monkeypatch, calls)
    request = make_request(headers=[(b"authorization", b"Bearer session")])

    state = authenticate_clerk_request(request)

    assert state.payload["sub"] == "user_abc"
    assert len(calls) == 1
    assert calls[0].secret_key == "sk_test_x"
    assert calls[0].jwt_key == JWT_KEY
    assert calls[0].authorized_parties == ["http://localhost:3000"]
    assert calls[0].accepts_token == ["session_token"]


def test_verification_is_cached_on_the_request(monkeypatch):
    calls = []
    _install(monkeypatch, calls)
    request = make_request(headers=[(b"authorization", b"Bearer session")])

    first = authenticate_clerk_request(request)
    second = authenticate_clerk_request(request)

    assert first.payload["sub"] == second.payload["sub"] == "user_abc"
    assert len(calls) == 1


def test_an_authenticated_request_verifies_the_session_once(monkeypatch):
    calls = []
    _install(monkeypatch, calls)
    app.dependency_overrides[get_activity_service] = lambda: EmptyActivityService()
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/activities",
            headers={"Authorization": "Bearer session"},
        )
    finally:
        app.dependency_overrides.pop(get_activity_service, None)

    assert response.status_code == 200
    assert len(calls) == 1
