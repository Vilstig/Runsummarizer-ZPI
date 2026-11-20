"""activities.device_name

Revision ID: b8e4d1f6a2c9
Revises: a3f9c2d7e104
Create Date: 2026-11-15 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e4d1f6a2c9"
down_revision: str | None = "a3f9c2d7e104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("activities", sa.Column("device_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("activities", "device_name")
