"""activity hr zone bounds

Revision ID: b6f1d3a8e2c7
Revises: 854c278dfe71
Create Date: 2026-10-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6f1d3a8e2c7"
down_revision: str | None = "854c278dfe71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# lower bounds of HR zones 2-5 for a max HR of 199 bpm, rounded up to whole bpm
_DEFAULT_BOUNDS = {2: 120, 3: 140, 4: 160, 5: 180}


def upgrade() -> None:
    for zone, bound in _DEFAULT_BOUNDS.items():
        op.add_column(
            "activities",
            sa.Column(
                f"hr_zone{zone}_bpm",
                sa.SmallInteger(),
                server_default=sa.text(str(bound)),
                nullable=False,
            ),
        )
        op.alter_column("activities", f"hr_zone{zone}_bpm", server_default=None)
        op.create_check_constraint(
            op.f(f"ck_activities_hr_zone{zone}_bpm"),
            "activities",
            f"hr_zone{zone}_bpm BETWEEN 0 AND 256",
        )
    op.create_check_constraint(
        op.f("ck_activities_hr_zone_bounds_increasing"),
        "activities",
        "hr_zone2_bpm < hr_zone3_bpm AND hr_zone3_bpm < hr_zone4_bpm "
        "AND hr_zone4_bpm < hr_zone5_bpm",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_activities_hr_zone_bounds_increasing"), "activities", type_="check")
    for zone in _DEFAULT_BOUNDS:
        op.drop_constraint(op.f(f"ck_activities_hr_zone{zone}_bpm"), "activities", type_="check")
        op.drop_column("activities", f"hr_zone{zone}_bpm")
