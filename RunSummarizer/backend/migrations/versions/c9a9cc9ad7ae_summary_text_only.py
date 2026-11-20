"""summary text only

Revision ID: c9a9cc9ad7ae
Revises: e3bbf8101ce8
Create Date: 2026-10-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c9a9cc9ad7ae"
down_revision: str | None = "e3bbf8101ce8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A summary text rendered from params the user edited is kept as text the user edited.
    op.execute(
        "UPDATE activities SET summary_text_edited_at = summary_params_edited_at "
        "WHERE summary_params_edited_at IS NOT NULL AND summary_text_edited_at IS NULL"
    )
    op.drop_column("activities", "summary_params_edited_at")
    op.drop_column("activities", "summary_params_version")
    op.drop_column("activities", "summary_params")


def downgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("summary_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "activities", sa.Column("summary_params_version", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "activities",
        sa.Column("summary_params_edited_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
