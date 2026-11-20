"""merge conflicting heads

Revision ID: 8a296bf4a4b3
Revises: 5b1e7c2d9a40, a7d2e5f91c3b
Create Date: 2026-10-19 20:43:21.668376

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a296bf4a4b3'
down_revision: Union[str, None] = ('5b1e7c2d9a40', 'a7d2e5f91c3b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
