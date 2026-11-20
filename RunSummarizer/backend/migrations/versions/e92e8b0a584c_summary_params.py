"""summary params

Revision ID: e92e8b0a584c
Revises: 8a296bf4a4b3
Create Date: 2026-10-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e92e8b0a584c"
down_revision: str | None = "8a296bf4a4b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE activities SET summary = '' WHERE summary IS NULL")
    op.alter_column("activities", "summary", existing_type=sa.Text(), nullable=False)
    op.add_column(
        "activities",
        sa.Column("summary_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "activities", sa.Column("summary_params_version", sa.SmallInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("activities", "summary_params_version")
    op.drop_column("activities", "summary_params")
    op.alter_column("activities", "summary", existing_type=sa.Text(), nullable=True)
