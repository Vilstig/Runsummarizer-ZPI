from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Double, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, _enum_in
from app.domain.enums import Sex

if TYPE_CHECKING:
    from app.db.models.activity import Activity
    from app.db.models.hr_zones import HrZones
    from app.db.models.provider_account import ProviderAccount


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_enum_in("sex", Sex), name="sex"),
        CheckConstraint("age BETWEEN 5 AND 99", name="age"),  # years
        CheckConstraint("height_cm BETWEEN 50 AND 240", name="height_cm"),
        CheckConstraint("max_hr BETWEEN 0 AND 256", name="max_hr"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # Clerk user id

    age: Mapped[int | None] = mapped_column(SmallInteger)  # years
    sex: Mapped[str | None] = mapped_column(Text)  # 'male' | 'female'
    height_cm: Mapped[float | None] = mapped_column(Double)
    max_hr: Mapped[int | None] = mapped_column(SmallInteger)  # bpm

    provider_accounts: Mapped[list[ProviderAccount]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    hr_zones: Mapped[list[HrZones]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
