"""Suite-wide pytest configuration."""

import os

import pytest

# Fixed values rather than whatever .env or the shell holds, so the suite runs
# without a .env and never touches production key material. Set before
# app.config.settings is imported; load_dotenv() leaves an existing value alone.
# The webhook secret is whsec_ + base64("runsummarizer-contract-tests").
os.environ["TOKEN_ENCRYPTION_KEY"] = "runsummarizer-contract-tests"
os.environ["CLERK_WEBHOOK_SECRET"] = "whsec_cnVuc3VtbWFyaXplci1jb250cmFjdC10ZXN0cw=="


@pytest.fixture
def fake_clerk(monkeypatch):
    """Install local Clerk verification. Pass ``{token: user_id}`` for signed-in tokens."""
    from tests.helpers import install_fake_clerk

    def install(users: dict[str, str] | None = None) -> None:
        install_fake_clerk(monkeypatch, users)

    return install
