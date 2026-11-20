"""user profile

Revision ID: c4e8a1b27f90
Revises: f3b8c1a04e56
Create Date: 2026-10-15 13:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a1b27f90"
down_revision: str | None = "f3b8c1a04e56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE_COLUMNS = (
    "age",
    "sex",
    "height_cm",
    "max_hr",
    "hr_zone1_bpm",
    "hr_zone2_bpm",
    "hr_zone3_bpm",
    "hr_zone4_bpm",
    "hr_zone5_bpm",
)


def upgrade() -> None:
    op.add_column("users", sa.Column("age", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("sex", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("height_cm", sa.Double(), nullable=True))
    op.add_column("users", sa.Column("max_hr", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("hr_zone1_bpm", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("hr_zone2_bpm", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("hr_zone3_bpm", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("hr_zone4_bpm", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("hr_zone5_bpm", sa.SmallInteger(), nullable=True))

    op.create_check_constraint(op.f("ck_users_sex"), "users", "sex IN ('male', 'female')")
    op.create_check_constraint(op.f("ck_users_age"), "users", "age BETWEEN 5 AND 99")
    op.create_check_constraint(op.f("ck_users_height_cm"), "users", "height_cm BETWEEN 50 AND 240")
    op.create_check_constraint(op.f("ck_users_max_hr"), "users", "max_hr BETWEEN 0 AND 256")
    op.create_check_constraint(
        op.f("ck_users_hr_zone1_bpm"), "users", "hr_zone1_bpm BETWEEN 0 AND 256"
    )
    op.create_check_constraint(
        op.f("ck_users_hr_zone2_bpm"), "users", "hr_zone2_bpm BETWEEN 0 AND 256"
    )
    op.create_check_constraint(
        op.f("ck_users_hr_zone3_bpm"), "users", "hr_zone3_bpm BETWEEN 0 AND 256"
    )
    op.create_check_constraint(
        op.f("ck_users_hr_zone4_bpm"), "users", "hr_zone4_bpm BETWEEN 0 AND 256"
    )
    op.create_check_constraint(
        op.f("ck_users_hr_zone5_bpm"), "users", "hr_zone5_bpm BETWEEN 0 AND 256"
    )
    op.create_check_constraint(
        op.f("ck_users_max_hr_above_zone5"),
        "users",
        "max_hr IS NULL OR hr_zone5_bpm IS NULL OR max_hr > hr_zone5_bpm",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_max_hr_above_zone5"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_hr_zone5_bpm"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_hr_zone4_bpm"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_hr_zone3_bpm"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_hr_zone2_bpm"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_hr_zone1_bpm"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_max_hr"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_height_cm"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_age"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_sex"), "users", type_="check")

    for column in reversed(_PROFILE_COLUMNS):
        op.drop_column("users", column)
