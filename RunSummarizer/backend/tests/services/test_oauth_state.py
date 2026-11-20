"""OAuth state: the signed CSRF token bound to a Clerk user and a provider."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.domain.enums import Provider
from app.domain.errors import OAuthStateMismatchError
from app.services.accounts.oauth_state import (
    ALGORITHM,
    create_oauth_state,
    open_oauth_secrets,
    seal_oauth_secrets,
    verify_oauth_state,
)

USER_ID = "user_abc"
SECRET = "test-secret"
DETAIL = "OAuth state does not match browser session"


@pytest.fixture(autouse=True)
def oauth_secret(monkeypatch):
    monkeypatch.setattr("app.services.accounts.oauth_state.OAUTH_STATE_SECRET", SECRET)


def _assert_rejected(
    state: str, cookie: str | None, *, provider: Provider = Provider.STRAVA
) -> None:
    with pytest.raises(OAuthStateMismatchError, match=DETAIL):
        verify_oauth_state(state, cookie_state=cookie, provider=provider)


def _encode(**overrides) -> str:
    payload = {
        "sub": USER_ID,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "type": "oauth_state",
        "provider": Provider.STRAVA.value,
    }
    payload.update(overrides)
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def test_a_state_round_trips_to_the_user():
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    assert verify_oauth_state(state, cookie_state=state, provider=Provider.STRAVA) == USER_ID


@pytest.mark.parametrize("cookie", [None, "other-state"])
def test_verify_rejects_a_cookie_that_does_not_match(cookie):
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)

    _assert_rejected(state, cookie)


def test_verify_rejects_a_tampered_state():
    header, payload, signature = create_oauth_state(USER_ID, provider=Provider.STRAVA).split(".")
    # The signature's first character: all six of its bits are signature bits, while
    # the last character carries two padding bits a change can land in.
    signature = ("a" if signature[0] != "a" else "b") + signature[1:]
    tampered = f"{header}.{payload}.{signature}"

    _assert_rejected(tampered, tampered)


def test_verify_rejects_an_expired_state():
    state = _encode(exp=datetime.now(UTC) - timedelta(minutes=1))

    _assert_rejected(state, state)


def test_verify_rejects_a_state_of_the_wrong_type():
    state = _encode(type="access")

    _assert_rejected(state, state)


@pytest.mark.parametrize("sub", [{}, {"sub": ""}])
def test_verify_rejects_a_state_without_a_user(sub):
    payload = {
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "type": "oauth_state",
        "provider": Provider.STRAVA.value,
        **sub,
    }
    state = jwt.encode(payload, SECRET, algorithm=ALGORITHM)

    _assert_rejected(state, state)


def test_verify_rejects_a_state_issued_for_another_provider():
    state = create_oauth_state(USER_ID, provider=Provider.GARMIN)

    _assert_rejected(state, state, provider=Provider.STRAVA)


def test_create_refuses_an_empty_secret(monkeypatch):
    monkeypatch.setattr("app.services.accounts.oauth_state.OAUTH_STATE_SECRET", "")

    with pytest.raises(RuntimeError, match="OAUTH_STATE_SECRET is not configured"):
        create_oauth_state(USER_ID, provider=Provider.STRAVA)


def test_verify_refuses_an_empty_secret(monkeypatch):
    state = create_oauth_state(USER_ID, provider=Provider.STRAVA)
    monkeypatch.setattr("app.services.accounts.oauth_state.OAUTH_STATE_SECRET", "")

    with pytest.raises(RuntimeError, match="OAUTH_STATE_SECRET is not configured"):
        verify_oauth_state(state, cookie_state=state, provider=Provider.STRAVA)


# ---------- sealed secrets ----------


def test_sealed_secrets_open_for_their_state(monkeypatch):
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "test-key")
    sealed = seal_oauth_secrets({"code_verifier": "v-1"}, state="state-1")

    assert open_oauth_secrets(sealed, state="state-1") == {"code_verifier": "v-1"}
    assert open_oauth_secrets(None, state="state-1") == {}


def test_sealed_secrets_need_the_encryption_key_to_open(monkeypatch):
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "test-key")
    sealed = seal_oauth_secrets({"code_verifier": "v-1"}, state="state-1")
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "")

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
        open_oauth_secrets(sealed, state="state-1")


def test_secrets_sealed_with_another_key_do_not_match(monkeypatch):
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "test-key")
    sealed = seal_oauth_secrets({"code_verifier": "v-1"}, state="state-1")
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "other-key")

    with pytest.raises(OAuthStateMismatchError, match="OAuth secrets do not match browser session"):
        open_oauth_secrets(sealed, state="state-1")
