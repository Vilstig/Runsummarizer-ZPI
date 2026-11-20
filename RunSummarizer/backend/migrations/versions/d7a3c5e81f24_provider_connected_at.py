"""provider_accounts.connected_at, one connected provider per user

Revision ID: d7a3c5e81f24
Revises: c4d2e7f9a1b3
Create Date: 2026-11-11 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a3c5e81f24"
down_revision: str | None = "c4d2e7f9a1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_accounts",
        sa.Column("connected_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # A user's most recently updated account holding an access token counts as connected.
    op.execute(
        """
        UPDATE provider_accounts AS account
        SET connected_at = account.updated_at
        FROM (
            SELECT DISTINCT ON (user_id) user_id, provider
            FROM provider_accounts
            WHERE access_token IS NOT NULL
            ORDER BY user_id, updated_at DESC, provider
        ) AS latest
        WHERE account.user_id = latest.user_id AND account.provider = latest.provider
        """
    )
    op.create_index(
        "uq_provider_accounts_connected_user_id",
        "provider_accounts",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("connected_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_provider_accounts_connected_user_id", table_name="provider_accounts")
    op.drop_column("provider_accounts", "connected_at")
