"""laps without warm-up and cool-down types

Revision ID: 5b1e7c2d9a40
Revises: 9d4f2b7e1a63
Create Date: 2026-10-17 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b1e7c2d9a40"
down_revision: str | None = "9d4f2b7e1a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LapType ids: 3 (warm-up) and 4 (cool-down) become 0 (run)
    op.execute("UPDATE laps SET lap_type_id = 0 WHERE lap_type_id IN (3, 4)")


def downgrade() -> None:
    # Which run laps were warm-up or cool-down laps is not recorded, so they stay runs.
    pass
