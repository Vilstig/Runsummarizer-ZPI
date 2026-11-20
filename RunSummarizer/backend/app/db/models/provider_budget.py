from __future__ import annotations

from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class ProviderBudget(Base):
    """A provider's app-wide rate-limit budget: its pause and the limits it reported."""

    __tablename__ = "provider_budgets"

    provider: Mapped[str] = mapped_column(
        Text, primary_key=True
    )  # 'strava' | 'garmin' | 'intervals'
    paused_until: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )  # no calls to the provider before this time
    limits: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )  # {window name: calls per window}, as the provider reported them

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class ProviderBudgetUsage(Base):
    """The calls made or reserved in one bucket of one of a provider's windows."""

    __tablename__ = "provider_budget_usage"

    provider: Mapped[str] = mapped_column(
        Text,
        ForeignKey("provider_budgets.provider", ondelete="CASCADE"),
        primary_key=True,
    )
    window: Mapped[str] = mapped_column(Text, primary_key=True)  # BudgetWindow.name, e.g. '15m'
    bucket_start: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True
    )  # BudgetWindow.bucket_start of the calls
    used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
