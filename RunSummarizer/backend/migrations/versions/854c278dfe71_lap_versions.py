"""lap versions

Revision ID: 854c278dfe71
Revises: c9a9cc9ad7ae
Create Date: 2026-10-24 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "854c278dfe71"
down_revision: str | None = "c9a9cc9ad7ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "laps",
        sa.Column("version", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(op.f("ck_laps_version"), "laps", "version IN (0, 1)")
    op.drop_constraint(op.f("pk_laps"), "laps", type_="primary")
    op.create_primary_key(op.f("pk_laps"), "laps", ["activity_id", "lap_index", "version"])


def downgrade() -> None:
    op.execute("DELETE FROM laps WHERE version = 1")
    op.drop_constraint(op.f("pk_laps"), "laps", type_="primary")
    op.create_primary_key(op.f("pk_laps"), "laps", ["activity_id", "lap_index"])
    op.drop_constraint(op.f("ck_laps_version"), "laps", type_="check")
    op.drop_column("laps", "version")
