"""Domain errors raised by services and repositories. The API maps them to HTTP."""

from __future__ import annotations

from datetime import datetime

from app.domain.enums import Provider


class DomainError(Exception):
    """A domain failure whose message is safe to show the user."""


class ActivityNotFoundError(DomainError):
    """No activity matches the given id for the user."""


class UserNotFoundError(DomainError):
    """No user matches the given id."""


class ProviderNotSupportedError(DomainError):
    """The provider isn't registered, or lacks its settings."""


class UnknownLapError(DomainError):
    """A lap index the activity has no lap at."""


class InvalidSegmentationError(DomainError):
    """User segments that don't split an activity's laps."""


class InvalidSyncWindowError(DomainError):
    """The sync window doesn't start before it ends."""


class InvalidSyncLimitError(DomainError):
    """A limit was given together with 'after' or 'before'."""


class TextPolicyRequiredError(DomainError):
    """A change of the laps or segments of an activity whose summary text the user edited,
    without a ``TextPolicy``."""


class HeartRateZonesConflictError(DomainError):
    """Max heart rate is not above the zone 5 lower bound."""


class AnotherProviderConnectedError(DomainError):
    """The user is connected to another provider."""

    def __init__(self, message: str = "Disconnect the connected provider first"):
        super().__init__(message)


class ProviderAccountTakenError(DomainError):
    """The provider account is linked to another user."""


class OAuthStateMismatchError(DomainError):
    """The OAuth state or secrets cookie is missing, expired or not matching."""


class WebhookRejectedError(DomainError):
    """The webhook request doesn't come from the provider, e.g. a wrong verify token."""


class WebhookPayloadError(DomainError):
    """The webhook body isn't an event the provider sends."""


class SyncNotSupportedError(DomainError):
    """The provider has no syncer: it only sends activities by itself."""


class ProviderError(DomainError):
    """Anything about the user's provider that stops an action."""


class ProviderNotConnectedError(ProviderError):
    """The user holds no credentials for the provider."""


class ProviderPausedError(ProviderError):
    """The provider's calls are paused: none before ``until``."""

    def __init__(self, provider: Provider, until: datetime):
        super().__init__(f"{provider} calls are paused until {until.isoformat()}")
        self.provider = provider
        self.until = until


class FetchError(ProviderError):
    """A provider call failed. ``str()`` is the error text stored on an import item."""


class RateLimitedError(FetchError):
    """The provider's rate limit is used up: no calls before ``until``."""

    def __init__(self, message: str, *, until: datetime):
        super().__init__(message)
        self.until = until


class ProviderAuthorizationError(FetchError):
    """The user's authorization with the provider no longer works."""


class ProviderActivityNotFoundError(FetchError):
    """The provider has no such activity, or it is not visible to the user."""


class ProviderUnavailableError(FetchError):
    """The provider failed or couldn't be reached; a later attempt may succeed."""


class ProviderResponseError(FetchError):
    """The provider answered with a response the app can't use, e.g. without the user's id."""
