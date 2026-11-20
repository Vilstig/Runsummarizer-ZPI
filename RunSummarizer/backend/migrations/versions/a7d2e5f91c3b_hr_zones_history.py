"""hr zones history

Revision ID: a7d2e5f91c3b
Revises: c4e8a1b27f90
Create Date: 2026-10-17 17:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d2e5f91c3b"
down_revision: str | None = "c4e8a1b27f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ZONES = range(1, 6)


def upgrade() -> None:
    op.create_table(
        "hr_zones",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.TIMESTAMP(timezone=True), nullable=False),
        *(sa.Column(f"zone{zone}_bpm", sa.SmallInteger(), nullable=False) for zone in _ZONES),
        *(
            sa.CheckConstraint(
                f"zone{zone}_bpm BETWEEN 0 AND 256", name=op.f(f"ck_hr_zones_zone{zone}_bpm")
            )
            for zone in _ZONES
        ),
        sa.CheckConstraint(
            "zone1_bpm < zone2_bpm AND zone2_bpm < zone3_bpm "
            "AND zone3_bpm < zone4_bpm AND zone4_bpm < zone5_bpm",
            name=op.f("ck_hr_zones_zones_increasing"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_hr_zones_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hr_zones")),
        sa.UniqueConstraint("user_id", "valid_from", name=op.f("uq_hr_zones_user_id_valid_from")),
    )

    op.execute(
        "INSERT INTO hr_zones (user_id, valid_from, zone1_bpm, zone2_bpm, zone3_bpm, "
        "zone4_bpm, zone5_bpm) "
        "SELECT id, now(), hr_zone1_bpm, hr_zone2_bpm, hr_zone3_bpm, hr_zone4_bpm, hr_zone5_bpm "
        "FROM users "
        "WHERE hr_zone1_bpm IS NOT NULL AND hr_zone2_bpm IS NOT NULL "
        "AND hr_zone3_bpm IS NOT NULL AND hr_zone4_bpm IS NOT NULL "
        "AND hr_zone5_bpm IS NOT NULL"
    )

    op.drop_constraint(op.f("ck_users_max_hr_above_zone5"), "users", type_="check")
    for zone in _ZONES:
        op.drop_constraint(op.f(f"ck_users_hr_zone{zone}_bpm"), "users", type_="check")
        op.drop_column("users", f"hr_zone{zone}_bpm")


def downgrade() -> None:
    for zone in _ZONES:
        op.add_column("users", sa.Column(f"hr_zone{zone}_bpm", sa.SmallInteger(), nullable=True))
        op.create_check_constraint(
            op.f(f"ck_users_hr_zone{zone}_bpm"), "users", f"hr_zone{zone}_bpm BETWEEN 0 AND 256"
        )

    op.execute(
        "UPDATE users SET hr_zone1_bpm = latest.zone1_bpm, hr_zone2_bpm = latest.zone2_bpm, "
        "hr_zone3_bpm = latest.zone3_bpm, hr_zone4_bpm = latest.zone4_bpm, "
        "hr_zone5_bpm = latest.zone5_bpm "
        "FROM (SELECT DISTINCT ON (user_id) * FROM hr_zones "
        "ORDER BY user_id, valid_from DESC) AS latest "
        "WHERE users.id = latest.user_id"
    )
    # zone bounds above max_hr would violate the restored check
    op.execute(
        "UPDATE users SET max_hr = NULL "
        "WHERE max_hr IS NOT NULL AND hr_zone5_bpm IS NOT NULL AND max_hr <= hr_zone5_bpm"
    )
    op.create_check_constraint(
        op.f("ck_users_max_hr_above_zone5"),
        "users",
        "max_hr IS NULL OR hr_zone5_bpm IS NULL OR max_hr > hr_zone5_bpm",
    )

    op.drop_table("hr_zones")
