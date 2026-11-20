from collections.abc import Mapping

from app.domain.enums import ImportStatus, SyncState


def sync_state(counts: Mapping[ImportStatus, int]) -> SyncState:
    """The ``SyncState`` of a user's items for one provider, from the number of them in
    each status. A status left out counts as 0.
    """
    if counts.get(ImportStatus.BLOCKED, 0) > 0:
        return SyncState.NEEDS_RECONNECT
    if counts.get(ImportStatus.QUEUED, 0) > 0 or counts.get(ImportStatus.RUNNING, 0) > 0:
        return SyncState.SYNCING
    return SyncState.IDLE
