from enum import IntEnum, StrEnum


class ImportSource(StrEnum):
    WEBHOOK = "webhook"
    SYNC = "sync"


class ImportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DEAD = "dead"
    BLOCKED = "blocked"


class ImportPriority(IntEnum):
    """Claim order: lower values are claimed first."""

    WEBHOOK = 0
    SYNC = 1


class WindowKind(StrEnum):
    """How a rate-limit window moves."""

    FIXED = "fixed"  # resets at every multiple of its length from the Unix epoch
    ROLLING = "rolling"  # covers the last ``length`` before now


class ImportErrorCode(StrEnum):
    """Why an item failed, as shown to the user."""

    UNAVAILABLE = "unavailable"  # 5xx, timeout or connection error
    NOT_FOUND = "not_found"  # 404
    AUTHORIZATION_REVOKED = "authorization_revoked"  # 401, 403 or a rejected token refresh
    PROCESSING_FAILED = "processing_failed"  # an exception while processing the payload
    WORKER_LOST = "worker_lost"  # the lease expired


class SyncState(StrEnum):
    """Whether a user's items for one provider are being imported."""

    NEEDS_RECONNECT = "needs_reconnect"  # some item is blocked
    SYNCING = "syncing"  # some item is queued or running, and none is blocked
    IDLE = "idle"  # no item is blocked, queued or running
