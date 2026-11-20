import hmac
import json
from datetime import UTC, datetime, timedelta

import jwt

from app.config.settings import OAUTH_STATE_SECRET
from app.db.encryption import (
    ENCRYPTED_PREFIX,
    SecretDecryptionError,
    decrypt_secret,
    encrypt_secret,
)
from app.domain.enums import Provider
from app.domain.errors import OAuthStateMismatchError

ALGORITHM = "HS256"
OAUTH_STATE_EXPIRE_MINUTES = 10
OAUTH_STATE_COOKIE = "oauth_state"
OAUTH_SECRETS_COOKIE = "oauth_secrets"


def _require_oauth_state_secret() -> str:
    if not OAUTH_STATE_SECRET:
        raise RuntimeError("OAUTH_STATE_SECRET is not configured")
    return OAUTH_STATE_SECRET


def create_oauth_state(user_id: str, *, provider: Provider) -> str:
    """Return a signed CSRF ``state`` that carries ``user_id`` and the provider.

    The same value is stored in the HttpOnly ``oauth_state`` cookie and must
    match on callback. Expiry is the JWT ``exp`` and the cookie ``max_age``.
    """
    secret = _require_oauth_state_secret()
    expire = datetime.now(UTC) + timedelta(minutes=OAUTH_STATE_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": "oauth_state",
        "provider": provider.value,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_oauth_state(state: str, *, cookie_state: str | None, provider: Provider) -> str:
    """Return the Clerk user id bound to a state that matches the cookie and provider."""
    if not state or not cookie_state or not hmac.compare_digest(str(state), str(cookie_state)):
        raise OAuthStateMismatchError("OAuth state does not match browser session")

    secret = _require_oauth_state_secret()
    try:
        payload = jwt.decode(state, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise OAuthStateMismatchError("OAuth state does not match browser session") from exc

    if payload.get("type") != "oauth_state":
        raise OAuthStateMismatchError("OAuth state does not match browser session")

    user_id = payload.get("sub")
    if not user_id:
        raise OAuthStateMismatchError("OAuth state does not match browser session")

    if payload.get("provider") != provider.value:
        raise OAuthStateMismatchError("OAuth state does not match browser session")
    return user_id


def seal_oauth_secrets(secrets: dict[str, str], *, state: str) -> str:
    """The ``oauth_secrets`` cookie value for ``secrets``: encrypted, and bound to ``state``."""
    return encrypt_secret(json.dumps({"state": state, "secrets": secrets}))


def open_oauth_secrets(cookie: str | None, *, state: str) -> dict[str, str]:
    """The secrets sealed into ``cookie`` by ``seal_oauth_secrets`` for ``state``; empty
    without a cookie. A cookie that isn't sealed, or was sealed for another state, raises
    ``OAuthStateMismatchError``.
    """
    if not cookie:
        return {}
    if not cookie.startswith(ENCRYPTED_PREFIX):
        raise OAuthStateMismatchError("OAuth secrets do not match browser session")
    try:
        sealed = json.loads(decrypt_secret(cookie))
    except SecretDecryptionError as exc:
        raise OAuthStateMismatchError("OAuth secrets do not match browser session") from exc
    except ValueError as exc:
        raise OAuthStateMismatchError("OAuth secrets do not match browser session") from exc
    if (
        not isinstance(sealed, dict)
        or not isinstance(sealed.get("secrets"), dict)
        or not hmac.compare_digest(str(sealed.get("state")), str(state))
    ):
        raise OAuthStateMismatchError("OAuth secrets do not match browser session")
    return sealed["secrets"]
