"""summary edit flags

Revision ID: 45f66bc994a7
Revises: e92e8b0a584c
Create Date: 2026-10-20 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "45f66bc994a7"
down_revision: str | None = "e92e8b0a584c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("summary_text_edited_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column("summary_params_edited_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activities", "summary_params_edited_at")
    op.drop_column("activities", "summary_text_edited_at")
