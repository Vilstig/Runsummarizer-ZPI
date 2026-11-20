import pytest
from sqlalchemy.dialects import postgresql

from app.db.encryption import EncryptedText, decrypt_secret, encrypt_secret

DIALECT = postgresql.dialect()


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "test-key")


def test_a_bound_value_is_stored_as_ciphertext():
    stored = EncryptedText().process_bind_param("secret", DIALECT)

    assert stored.startswith("enc:v1:")
    assert "secret" not in stored


def test_a_stored_value_is_read_back_as_plaintext():
    column = EncryptedText()

    stored = column.process_bind_param("secret", DIALECT)

    assert column.process_result_value(stored, DIALECT) == "secret"


def test_null_stays_null():
    column = EncryptedText()

    assert column.process_bind_param(None, DIALECT) is None
    assert column.process_result_value(None, DIALECT) is None


def test_encrypting_ciphertext_again_leaves_it_unchanged():
    stored = encrypt_secret("secret")

    assert encrypt_secret(stored) == stored


def test_legacy_plaintext_is_read_unchanged():
    assert decrypt_secret("plaintext") == "plaintext"


def test_ciphertext_from_another_key_is_rejected(monkeypatch):
    stored = encrypt_secret("secret")
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "other-key")

    with pytest.raises(RuntimeError, match="decrypt"):
        decrypt_secret(stored)


def test_a_missing_key_is_rejected(monkeypatch):
    monkeypatch.setattr("app.db.encryption.TOKEN_ENCRYPTION_KEY", "")

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
        encrypt_secret("secret")
