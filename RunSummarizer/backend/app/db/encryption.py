"""Field-level encryption for secrets stored in the database."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config.settings import TOKEN_ENCRYPTION_KEY

ENCRYPTED_PREFIX = "enc:v1:"  # marks Fernet ciphertext


class SecretDecryptionError(RuntimeError):
    """Stored ciphertext could not be decrypted with the configured key."""


def _fernet() -> Fernet:
    if not TOKEN_ENCRYPTION_KEY:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
    digest = hashlib.sha256(TOKEN_ENCRYPTION_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    """Encrypt a secret for at-rest storage. Idempotent for already-encrypted values."""
    if value.startswith(ENCRYPTED_PREFIX):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTED_PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    """Decrypt a secret. Legacy plaintext values pass through unchanged."""
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    token = value[len(ENCRYPTED_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError("Failed to decrypt stored secret") from exc


class EncryptedText(TypeDecorator[str]):
    """``TEXT`` column holding Fernet ciphertext (``enc:v1:...``).

    Values are encrypted when bound and decrypted when read; ``None`` is stored as NULL.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, _dialect) -> str | None:
        return None if value is None else encrypt_secret(value)

    def process_result_value(self, value: str | None, _dialect) -> str | None:
        return None if value is None else decrypt_secret(value)
