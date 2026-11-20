from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.enums import Provider, SyncState


class OAuthCallbackError(StrEnum):
    """The ``error`` query parameter of the frontend's OAuth callback page."""

    DECLINED = "declined"  # the user cancelled on the provider's consent page
    AUTHORIZATION_FAILED = "authorization_failed"  # the provider rejected the grant
    STATE_MISMATCH = "state_mismatch"  # OAuth cookies missing, expired or not matching
    ANOTHER_PROVIDER_CONNECTED = "another_provider_connected"
    ACCOUNT_TAKEN = "account_taken"  # the provider account is linked to another user
    PROVIDER_UNAVAILABLE = "provider_unavailable"  # provider error, timeout or rate limit
    FAILED = "failed"  # anything else


class ConnectResponse(BaseModel):
    authorize_url: str = Field(
        description="Open this URL in the browser to start the provider's OAuth flow."
    )


class ProviderStatusResponse(BaseModel):
    provider: Provider
    configured: bool = Field(description="Whether the app has the provider's settings.")
    can_sync: bool = Field(
        description=(
            "Whether a sync can be started. When false, the provider sends new activities "
            "on its own and POST /sync answers 409."
        )
    )
    connected: bool = Field(description="Whether the user is connected to the provider.")
    sync_state: SyncState = Field(description="The user's sync status with the provider.")
