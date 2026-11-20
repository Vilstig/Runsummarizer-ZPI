"""provider_accounts.sync_requested_at

Revision ID: c4d2e7f9a1b3
Revises: 0ae567732a99
Create Date: 2026-11-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d2e7f9a1b3"
down_revision: str | None = "0ae567732a99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_accounts",
        sa.Column("sync_requested_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("provider_accounts", "sync_requested_at")
