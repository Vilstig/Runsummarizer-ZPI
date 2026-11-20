"""activity streams

Revision ID: 9d4f2b7e1a63
Revises: c4e8a1b27f90
Create Date: 2026-10-16 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9d4f2b7e1a63"
down_revision: str | None = "c4e8a1b27f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _activity_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["activity_id"],
        ["activities.id"],
        name=op.f("fk_activity_streams_activity_id_activities"),
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.drop_table("activity_streams")
    op.create_table(
        "activity_streams",
        sa.Column("activity_id", sa.UUID(), nullable=False),
        sa.Column("time_s", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("distance_dm", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("heartrate_bpm", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("velocity_cms", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("altitude_dm", postgresql.ARRAY(sa.Integer()), nullable=True),
        _activity_fk(),
        sa.PrimaryKeyConstraint("activity_id", name=op.f("pk_activity_streams")),
    )
    # Saved Strava payloads holding 'hr_stream' and 'distance_stream' instead of 'streams'
    op.execute(
        "UPDATE import_items SET raw_payload = NULL WHERE raw_payload -> 'hr_stream' IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_table("activity_streams")
    op.create_table(
        "activity_streams",
        sa.Column("activity_id", sa.UUID(), nullable=False),
        sa.Column("stream_type", sa.Text(), nullable=False),
        sa.Column("samples", postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("sample_rate_hz", sa.REAL(), nullable=True),
        _activity_fk(),
        sa.PrimaryKeyConstraint("activity_id", "stream_type", name=op.f("pk_activity_streams")),
    )
