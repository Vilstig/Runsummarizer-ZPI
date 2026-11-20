"""Startup checks for the settings the process cannot serve without."""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config.validation import validate_required_settings

_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = (
    _PRIVATE.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)

_COMPLETE = {
    "CLERK_SECRET_KEY": "sk_test",
    "CLERK_AUTHORIZED_PARTIES": ["http://localhost:3000"],
    "OAUTH_STATE_SECRET": "state-secret",
    "TOKEN_ENCRYPTION_KEY": "encryption-key",
    "CLERK_WEBHOOK_SECRET": "whsec_test",
    "CLERK_JWT_KEY": PEM,
}

_PROBLEMS = {
    "CLERK_SECRET_KEY": "CLERK_SECRET_KEY is not configured",
    "CLERK_AUTHORIZED_PARTIES": "CLERK_AUTHORIZED_PARTIES is not configured",
    "OAUTH_STATE_SECRET": "OAUTH_STATE_SECRET is not configured",
    "TOKEN_ENCRYPTION_KEY": "TOKEN_ENCRYPTION_KEY is not configured",
    "CLERK_WEBHOOK_SECRET": "CLERK_WEBHOOK_SECRET is not configured",
    "CLERK_JWT_KEY": "CLERK_JWT_KEY is not a valid PEM public key",
}


def _configure(monkeypatch, **overrides) -> None:
    values = {**_COMPLETE, **overrides}
    for name, value in values.items():
        monkeypatch.setattr(f"app.config.validation.{name}", value)


def test_a_complete_configuration_passes(monkeypatch):
    _configure(monkeypatch)

    validate_required_settings()


@pytest.mark.parametrize(
    ("field", "empty"),
    [
        ("CLERK_SECRET_KEY", ""),
        ("CLERK_AUTHORIZED_PARTIES", []),
        ("OAUTH_STATE_SECRET", ""),
        ("TOKEN_ENCRYPTION_KEY", ""),
        ("CLERK_WEBHOOK_SECRET", ""),
        ("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----"),
        ("CLERK_JWT_KEY", "not-a-key"),
    ],
)
def test_each_missing_setting_is_reported(monkeypatch, field, empty):
    _configure(monkeypatch, **{field: empty})

    with pytest.raises(RuntimeError) as raised:
        validate_required_settings()

    assert str(raised.value) == _PROBLEMS[field]


def test_every_problem_is_reported_together(monkeypatch):
    _configure(
        monkeypatch,
        CLERK_SECRET_KEY="",
        CLERK_AUTHORIZED_PARTIES=[],
        OAUTH_STATE_SECRET="",
        TOKEN_ENCRYPTION_KEY="",
        CLERK_WEBHOOK_SECRET="",
        CLERK_JWT_KEY="not-a-key",
    )

    with pytest.raises(RuntimeError) as raised:
        validate_required_settings()

    assert str(raised.value) == "\n".join(_PROBLEMS.values())
