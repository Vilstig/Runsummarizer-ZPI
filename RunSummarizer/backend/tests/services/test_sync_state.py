import pytest

from app.domain.enums import ImportStatus, SyncState
from app.services.sync_state import sync_state


def counts(*, queued=0, running=0, dead=0, blocked=0) -> dict[ImportStatus, int]:
    return {
        ImportStatus.QUEUED: queued,
        ImportStatus.RUNNING: running,
        ImportStatus.DEAD: dead,
        ImportStatus.BLOCKED: blocked,
    }


@pytest.mark.parametrize(
    ("statuses", "state"),
    [
        (counts(queued=3), SyncState.SYNCING),
        (counts(running=1), SyncState.SYNCING),
        (counts(dead=2), SyncState.IDLE),
        (counts(blocked=1), SyncState.NEEDS_RECONNECT),
        (counts(queued=3, blocked=1), SyncState.NEEDS_RECONNECT),
        (counts(running=1, blocked=1), SyncState.NEEDS_RECONNECT),
        (counts(), SyncState.IDLE),
        ({}, SyncState.IDLE),
    ],
    ids=[
        "queued",
        "running",
        "only-dead",
        "blocked",
        "blocked-and-queued",
        "blocked-and-running",
        "no-items",
        "no-statuses",
    ],
)
def test_sync_state(statuses, state):
    assert sync_state(statuses) == state
