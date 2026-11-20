from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCredentials:
    """A user's tokens for a provider."""

    access_token: str
    refresh_token: str | None  # None when the provider issues no refresh token
    expires_at: int | None  # access-token expiry, a Unix timestamp; None when it doesn't expire
