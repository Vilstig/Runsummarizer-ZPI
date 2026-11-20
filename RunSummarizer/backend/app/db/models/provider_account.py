from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.encryption import EncryptedText
from app.db.models.base import Base, _enum_in
from app.domain.enums import Provider

if TYPE_CHECKING:
    from app.db.models.user import User

CONNECTED_USER_INDEX = "uq_provider_accounts_connected_user_id"  # one connected provider per user


class ProviderAccount(Base):
    """Per-provider OAuth credentials, one row per (user, provider)."""

    __tablename__ = "provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_provider_accounts_provider_provider_user_id",
        ),
        CheckConstraint(_enum_in("provider", Provider), name="provider"),
        Index(
            CONNECTED_USER_INDEX,
            "user_id",
            unique=True,
            postgresql_where=text("connected_at IS NOT NULL"),
        ),
    )

    user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 'strava' | 'garmin' | 'intervals'
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_user_id: Mapped[str] = mapped_column(Text, nullable=False)  # provider user id, as text

    refresh_token: Mapped[str | None] = mapped_column(EncryptedText)
    access_token: Mapped[str | None] = mapped_column(EncryptedText)
    expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )  # access-token expiry
    scopes: Mapped[str | None] = mapped_column(Text)  # granted OAuth scopes
    synced_through: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )  # activities are listed without gaps up to this time
    sync_requested_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )  # when the provider was last asked to send activities by webhook; NULL once some arrive
    connected_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )  # when the user last connected the provider; NULL while disconnected

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="provider_accounts")
