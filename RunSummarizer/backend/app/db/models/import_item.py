from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, _enum_in
from app.domain.enums import ImportSource, ImportStatus, Provider


class ImportItem(Base):
    """One unfinished import of a provider activity, keyed (user_id, provider, activity_key)."""

    __tablename__ = "import_items"
    __table_args__ = (
        CheckConstraint(_enum_in("provider", Provider), name="provider"),
        CheckConstraint(_enum_in("source", ImportSource), name="source"),
        CheckConstraint(_enum_in("status", ImportStatus), name="status"),
        Index(
            "import_items_claim_idx",
            "provider",
            "priority",
            "sort_key",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "import_items_lease_idx",
            "lease_until",
            postgresql_where=text("status = 'running'"),
        ),
    )

    user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(
        Text, primary_key=True
    )  # 'strava' | 'garmin' | 'intervals'
    activity_key: Mapped[str] = mapped_column(Text, primary_key=True)  # provider activity id

    source: Mapped[str] = mapped_column(Text, nullable=False)  # 'webhook' | 'sync'
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # ImportPriority
    sort_key: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    # 'queued' | 'running' | 'dead' | 'blocked'
    status: Mapped[str] = mapped_column(Text, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    run_after: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    raw_payload: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True)
    )  # provider data fetched for the item; None is stored as SQL NULL
    # what the provider sent with the webhook that last queued the item; never logged or
    # returned by the API, since it may hold a download token
    sent_data: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    # 'unavailable' | 'not_found' | 'authorization_revoked' | 'processing_failed' | 'worker_lost'
    error_code: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
