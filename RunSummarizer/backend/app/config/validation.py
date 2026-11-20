"""Required process settings checked before the app serves traffic."""

from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.config.settings import (
    CLERK_AUTHORIZED_PARTIES,
    CLERK_JWT_KEY,
    CLERK_SECRET_KEY,
    CLERK_WEBHOOK_SECRET,
    OAUTH_STATE_SECRET,
    TOKEN_ENCRYPTION_KEY,
)


def validate_required_settings() -> None:
    problems: list[str] = []
    if not CLERK_SECRET_KEY:
        problems.append("CLERK_SECRET_KEY is not configured")
    if not CLERK_AUTHORIZED_PARTIES:
        problems.append("CLERK_AUTHORIZED_PARTIES is not configured")
    if not OAUTH_STATE_SECRET:
        problems.append("OAUTH_STATE_SECRET is not configured")
    if not TOKEN_ENCRYPTION_KEY:
        problems.append("TOKEN_ENCRYPTION_KEY is not configured")
    if not CLERK_WEBHOOK_SECRET:
        problems.append("CLERK_WEBHOOK_SECRET is not configured")
    try:
        load_pem_public_key(CLERK_JWT_KEY.encode("utf-8"))
    except (ValueError, TypeError):
        problems.append("CLERK_JWT_KEY is not a valid PEM public key")
    if problems:
        raise RuntimeError("\n".join(problems))
