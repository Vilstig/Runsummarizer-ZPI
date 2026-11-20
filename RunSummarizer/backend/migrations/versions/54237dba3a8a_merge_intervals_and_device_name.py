"""merge intervals provider and activity device name

Revision ID: 54237dba3a8a
Revises: b038989787e1, b8e4d1f6a2c9
Create Date: 2026-11-20 11:58:46.846688

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "54237dba3a8a"
down_revision: str | Sequence[str] | None = ("b038989787e1", "b8e4d1f6a2c9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
