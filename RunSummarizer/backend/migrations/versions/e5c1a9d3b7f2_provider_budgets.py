"""provider_budgets and provider_budget_usage in place of strava_budget

Revision ID: e5c1a9d3b7f2
Revises: d7a3c5e81f24
Create Date: 2026-11-11 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5c1a9d3b7f2"
down_revision: str | None = "d7a3c5e81f24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_budgets",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("paused_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("provider", name=op.f("pk_provider_budgets")),
    )
    op.create_table(
        "provider_budget_usage",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("window", sa.Text(), nullable=False),
        sa.Column("bucket_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider"],
            ["provider_budgets.provider"],
            name=op.f("fk_provider_budget_usage_provider_provider_budgets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "provider", "window", "bucket_start", name=op.f("pk_provider_budget_usage")
        ),
    )
    op.execute(
        """
        INSERT INTO provider_budgets (provider, paused_until, limits, updated_at)
        SELECT 'strava', paused_until,
               jsonb_build_object('15m', limit_15m, 'day', limit_day), updated_at
        FROM strava_budget
        WHERE id = 1
        """
    )
    op.execute(
        """
        INSERT INTO provider_budget_usage (provider, "window", bucket_start, used)
        SELECT 'strava', '15m', window_start, used_15m
        FROM strava_budget
        WHERE id = 1 AND used_15m > 0
        UNION ALL
        SELECT 'strava', 'day', day::timestamp AT TIME ZONE 'UTC', used_day
        FROM strava_budget
        WHERE id = 1 AND used_day > 0
        """
    )
    op.drop_table("strava_budget")


def downgrade() -> None:
    op.create_table(
        "strava_budget",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("window_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_15m", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("used_day", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("limit_15m", sa.Integer(), nullable=False),
        sa.Column("limit_day", sa.Integer(), nullable=False),
        sa.Column("paused_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_strava_budget_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strava_budget")),
    )
    # The newest 15-minute and daily buckets, or Strava's default limits and a window
    # and day in the past without a Strava budget.
    op.execute(
        """
        INSERT INTO strava_budget (
            id, window_start, used_15m, day, used_day,
            limit_15m, limit_day, paused_until, updated_at
        )
        SELECT 1,
               COALESCE(w.bucket_start, '2000-01-01 00:00:00+00'),
               COALESCE(w.used, 0),
               COALESCE((d.bucket_start AT TIME ZONE 'UTC')::date, '2000-01-01'),
               COALESCE(d.used, 0),
               COALESCE((b.limits ->> '15m')::int, 100),
               COALESCE((b.limits ->> 'day')::int, 1000),
               b.paused_until,
               COALESCE(b.updated_at, now())
        FROM (SELECT 1) AS one
        LEFT JOIN provider_budgets AS b ON b.provider = 'strava'
        LEFT JOIN LATERAL (
            SELECT bucket_start, used FROM provider_budget_usage
            WHERE provider = 'strava' AND "window" = '15m'
            ORDER BY bucket_start DESC LIMIT 1
        ) AS w ON true
        LEFT JOIN LATERAL (
            SELECT bucket_start, used FROM provider_budget_usage
            WHERE provider = 'strava' AND "window" = 'day'
            ORDER BY bucket_start DESC LIMIT 1
        ) AS d ON true
        """
    )
    op.drop_table("provider_budget_usage")
    op.drop_table("provider_budgets")
