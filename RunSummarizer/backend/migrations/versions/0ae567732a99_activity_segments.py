"""activity segments

Revision ID: 0ae567732a99
Revises: b6f1d3a8e2c7
Create Date: 2026-10-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0ae567732a99"
down_revision: str | None = "b6f1d3a8e2c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_segments",
        sa.Column("activity_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("start_lap_index", sa.Integer(), nullable=False),
        sa.Column("end_lap_index", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("run_type_id", sa.SmallInteger(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("distance_m", sa.Double(), nullable=True),
        sa.Column("duration_s", sa.Double(), nullable=True),
        sa.Column("avg_hr", sa.Double(), nullable=True),
        sa.Column("pace_s_per_km", sa.Double(), nullable=True),
        sa.Column("rep_count", sa.SmallInteger(), nullable=True),
        sa.Column("rep_distance_m", sa.Double(), nullable=True),
        sa.Column("avg_rep_s", sa.Double(), nullable=True),
        sa.Column("avg_recovery_s", sa.Double(), nullable=True),
        sa.CheckConstraint(
            "role IN ('preamble', 'work', 'epilogue', 'break')",
            name=op.f("ck_activity_segments_role"),
        ),
        sa.CheckConstraint(
            "start_lap_index <= end_lap_index", name=op.f("ck_activity_segments_lap_order")
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name=op.f("fk_activity_segments_activity_id_activities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("activity_id", "position", name=op.f("pk_activity_segments")),
    )
    # Each activity's derived segments, without figures; a missing role is work and a
    # missing run type easy (RunType id 0).
    op.execute(
        """
        INSERT INTO activity_segments
            (activity_id, position, start_lap_index, end_lap_index, role, run_type_id, label)
        SELECT a.id,
               s.ordinality - 1,
               (s.segment ->> 'startLapIndex')::integer,
               (s.segment ->> 'endLapIndex')::integer,
               coalesce(s.segment ->> 'role', 'work'),
               coalesce((s.segment ->> 'runTypeId')::smallint, 0),
               s.segment ->> 'label'
        FROM activities a
        CROSS JOIN LATERAL jsonb_array_elements(a.derived -> 'segments')
            WITH ORDINALITY AS s(segment, ordinality)
        WHERE jsonb_typeof(a.derived -> 'segments') = 'array'
        """
    )
    op.drop_column("activities", "derived")


def downgrade() -> None:
    op.add_column(
        "activities",
        sa.Column(
            "derived",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    # runTypeDisplay is left out: it follows from runTypeId.
    op.execute(
        """
        UPDATE activities a
        SET derived = jsonb_build_object('segments', s.segments)
        FROM (
            SELECT activity_id,
                   jsonb_agg(
                       jsonb_build_object(
                           'startLapIndex', start_lap_index,
                           'endLapIndex', end_lap_index,
                           'runTypeId', run_type_id,
                           'label', label,
                           'role', role
                       )
                       ORDER BY position
                   ) AS segments
            FROM activity_segments
            GROUP BY activity_id
        ) s
        WHERE a.id = s.activity_id
        """
    )
    op.drop_table("activity_segments")
