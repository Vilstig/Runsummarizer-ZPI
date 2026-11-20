from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, _enum_in
from app.domain.enums import Provider, SegmentRole

if TYPE_CHECKING:
    from app.db.models.user import User


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("user_id", "activity_key", name="uq_activities_user_activity_key"),
        CheckConstraint(_enum_in("source", Provider), name="source"),
        *(
            CheckConstraint(f"hr_zone{zone}_bpm BETWEEN 0 AND 256", name=f"hr_zone{zone}_bpm")
            for zone in range(2, 6)
        ),
        CheckConstraint(
            "hr_zone2_bpm < hr_zone3_bpm AND hr_zone3_bpm < hr_zone4_bpm "
            "AND hr_zone4_bpm < hr_zone5_bpm",
            name="hr_zone_bounds_increasing",
        ),
        Index(
            "activities_user_time_idx",
            "user_id",
            text("start_time_local DESC"),
        ),
        Index(
            "activities_user_source_time_idx",
            "user_id",
            "source",
            text("start_time_local DESC"),
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
    source: Mapped[str] = mapped_column(Text, nullable=False)  # 'strava' | 'garmin' | 'intervals'
    activity_key: Mapped[str] = mapped_column(Text, nullable=False)  # provider activity id

    start_time_utc: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )  # true instant (UTC)
    start_time_local: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False
    )  # wall-clock local time
    utc_offset_s: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # e.g. '(GMT+01:00) Europe/Warsaw' (Strava) or 'Europe/Warsaw', an IANA name (Intervals.icu)
    timezone: Mapped[str | None] = mapped_column(Text)
    # the device that recorded the activity, e.g. 'Forerunner 965'; NULL: unknown
    device_name: Mapped[str | None] = mapped_column(Text)

    distance_m: Mapped[float | None] = mapped_column(Double)
    duration_s: Mapped[float | None] = mapped_column(Double)
    speed_mps: Mapped[float | None] = mapped_column(Double)
    avg_hr: Mapped[float | None] = mapped_column(Double)
    max_hr: Mapped[float | None] = mapped_column(Double)
    elevation_gain_m: Mapped[float | None] = mapped_column(Double)

    # seconds spent in each HR zone
    hr_zone1_s: Mapped[float] = mapped_column(Double, nullable=False, server_default=text("0"))
    hr_zone2_s: Mapped[float] = mapped_column(Double, nullable=False, server_default=text("0"))
    hr_zone3_s: Mapped[float] = mapped_column(Double, nullable=False, server_default=text("0"))
    hr_zone4_s: Mapped[float] = mapped_column(Double, nullable=False, server_default=text("0"))
    hr_zone5_s: Mapped[float] = mapped_column(Double, nullable=False, server_default=text("0"))
    # lower bound of each HR zone the hr_zone*_s times are counted in, in bpm; zone 1 is
    # everything below hr_zone2_bpm
    hr_zone2_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hr_zone3_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hr_zone4_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hr_zone5_bpm: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    training_type_id: Mapped[int | None] = mapped_column(SmallInteger)  # RunType id
    name: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # when the user last edited the summary text; NULL: not edited
    summary_text_edited_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # the user's split of the laps into segments; NULL: segments are worked out automatically
    user_segments: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="activities")
    laps: Mapped[list[Lap]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Lap.lap_index",
    )
    segments: Mapped[list[ActivitySegment]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ActivitySegment.position",
    )
    raw_payloads: Mapped[list[ActivityRawPayload]] = relationship(
        back_populates="activity", cascade="all, delete-orphan", passive_deletes=True
    )
    streams: Mapped[ActivityStream | None] = relationship(
        back_populates="activity", cascade="all, delete-orphan", passive_deletes=True
    )


class Lap(Base):
    """A version of a single lap within an activity, keyed (activity_id, lap_index, version)."""

    __tablename__ = "laps"
    __table_args__ = (
        CheckConstraint("version IN (0, 1)", name="version"),
        Index("laps_type_distance_idx", "lap_type_id", "distance_m"),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    lap_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 0: as imported, 1: edited by the user
    version: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("0"))
    lap_type_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # LapType id
    distance_m: Mapped[float | None] = mapped_column(Double)
    duration_s: Mapped[float | None] = mapped_column(Double)
    speed_mps: Mapped[float | None] = mapped_column(Double)
    avg_hr: Mapped[float | None] = mapped_column(Double)
    max_hr: Mapped[float | None] = mapped_column(Double)
    elevation_gain_m: Mapped[float | None] = mapped_column(Double)

    activity: Mapped[Activity] = relationship(back_populates="laps")


class ActivitySegment(Base):
    """A segment of an activity's laps, keyed (activity_id, position), with its figures from
    the params its part of the summary is written from; a figure is NULL where the segment
    has none."""

    __tablename__ = "activity_segments"
    __table_args__ = (
        CheckConstraint(_enum_in("role", SegmentRole), name="role"),
        CheckConstraint("start_lap_index <= end_lap_index", name="lap_order"),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)  # 0-based, in lap order
    start_lap_index: Mapped[int] = mapped_column(Integer, nullable=False)  # Lap.index, inclusive
    end_lap_index: Mapped[int] = mapped_column(Integer, nullable=False)  # Lap.index, inclusive
    role: Mapped[str] = mapped_column(Text, nullable=False)  # SegmentRole value
    run_type_id: Mapped[int] = mapped_column(
        SmallInteger, nullable=False
    )  # RunType id; 0 (easy) for a break
    label: Mapped[str | None] = mapped_column(Text)

    distance_m: Mapped[float | None] = mapped_column(Double)  # for intervals, the reps together
    duration_s: Mapped[float | None] = mapped_column(Double)  # for intervals, the reps together
    avg_hr: Mapped[float | None] = mapped_column(Double)  # bpm
    pace_s_per_km: Mapped[float | None] = mapped_column(Double)  # for intervals, of the reps
    rep_count: Mapped[int | None] = mapped_column(SmallInteger)
    rep_distance_m: Mapped[float | None] = mapped_column(Double)  # average
    avg_rep_s: Mapped[float | None] = mapped_column(Double)
    avg_recovery_s: Mapped[float | None] = mapped_column(Double)

    activity: Mapped[Activity] = relationship(back_populates="segments")


class ActivityRawPayload(Base):
    """Raw provider payloads, one row per (activity, payload_kind)."""

    __tablename__ = "activity_raw_payloads"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 'strava_detail' | 'strava_laps' | 'garmin_activity' | 'garmin_splits' | 'intervals_activity'
    payload_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    activity: Mapped[Activity] = relationship(back_populates="raw_payloads")


class ActivityStream(Base):
    """An activity's sample streams, one array per stream, aligned by sample index.

    Each array is NULL when the activity has no such stream.
    """

    __tablename__ = "activity_streams"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    time_s: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))  # seconds since the start
    distance_dm: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))  # decimetres
    heartrate_bpm: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    velocity_cms: Mapped[list[int] | None] = mapped_column(
        ARRAY(SmallInteger)
    )  # centimetres per second
    altitude_dm: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))  # decimetres

    activity: Mapped[Activity] = relationship(back_populates="streams")
