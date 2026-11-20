"""intervals.icu provider

Revision ID: b038989787e1
Revises: a3f9c2d7e104
Create Date: 2026-11-15 20:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b038989787e1"
down_revision: str | None = "a3f9c2d7e104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES_AND_COLUMNS = (
    ("activities", "source", "ck_activities_source"),
    ("import_items", "provider", "ck_import_items_provider"),
    ("provider_accounts", "provider", "ck_provider_accounts_provider"),
)


def upgrade() -> None:
    for table, column, constraint in _TABLES_AND_COLUMNS:
        op.drop_constraint(op.f(constraint), table, type_="check")
        op.create_check_constraint(
            op.f(constraint), table, f"{column} IN ('strava', 'garmin', 'intervals')"
        )


def downgrade() -> None:
    for table, column, constraint in _TABLES_AND_COLUMNS:
        op.drop_constraint(op.f(constraint), table, type_="check")
        op.create_check_constraint(op.f(constraint), table, f"{column} IN ('strava', 'garmin')")
