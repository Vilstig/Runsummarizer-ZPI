from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.user import User

_HR_BPM = "BETWEEN 0 AND 256"


class HrZones(Base):
    """A user's HR zone lower bounds, valid from ``valid_from`` until the next record."""

    __tablename__ = "hr_zones"
    __table_args__ = (
        UniqueConstraint("user_id", "valid_from"),
        CheckConstraint(f"zone1_bpm {_HR_BPM}", name="zone1_bpm"),
        CheckConstraint(f"zone2_bpm {_HR_BPM}", name="zone2_bpm"),
        CheckConstraint(f"zone3_bpm {_HR_BPM}", name="zone3_bpm"),
        CheckConstraint(f"zone4_bpm {_HR_BPM}", name="zone4_bpm"),
        CheckConstraint(f"zone5_bpm {_HR_BPM}", name="zone5_bpm"),
        CheckConstraint(
            "zone1_bpm < zone2_bpm AND zone2_bpm < zone3_bpm "
            "AND zone3_bpm < zone4_bpm AND zone4_bpm < zone5_bpm",
            name="zones_increasing",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),  # server-generated (Postgres 18)
    )
    user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    valid_from: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    # lower bound of each HR zone, in bpm
    zone1_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    zone2_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    zone3_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    zone4_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    zone5_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    user: Mapped[User] = relationship(back_populates="hr_zones")
