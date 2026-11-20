from pydantic import BaseModel

from app.domain.enums import SyncState


class SyncStartedResponse(BaseModel):
    queued: int  # items the sync queued: new ones, and dead ones queued again
    requested: bool  # the provider was asked to send the activities later, by webhook


class SyncStatusResponse(BaseModel):
    state: SyncState
