"""clerk user ids

Revision ID: f3b8c1a04e56
Revises: 728b327f5152
Create Date: 2026-10-06 20:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b8c1a04e56"
down_revision: str | None = "728b327f5152"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("refresh_tokens_user_idx", table_name="refresh_tokens")
    op.drop_index("refresh_tokens_gc_idx", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_constraint("fk_activities_user_id_users", "activities", type_="foreignkey")
    op.drop_constraint(
        "fk_provider_accounts_user_id_users", "provider_accounts", type_="foreignkey"
    )
    op.drop_constraint("fk_import_items_user_id_users", "import_items", type_="foreignkey")

    op.execute("ALTER TABLE users ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN id TYPE text USING id::text")
    op.execute("ALTER TABLE activities ALTER COLUMN user_id TYPE text USING user_id::text")
    op.execute(
        "ALTER TABLE provider_accounts ALTER COLUMN user_id TYPE text USING user_id::text"
    )
    op.execute("ALTER TABLE import_items ALTER COLUMN user_id TYPE text USING user_id::text")

    op.drop_column("users", "username")
    op.drop_column("users", "first_name")
    op.drop_column("users", "last_name")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "created_at")
    op.drop_column("users", "updated_at")

    op.execute("ALTER TABLE provider_accounts RENAME COLUMN external_id TO provider_user_id")
    op.execute(
        "ALTER TABLE provider_accounts RENAME CONSTRAINT "
        "uq_provider_accounts_provider_external_id TO "
        "uq_provider_accounts_provider_provider_user_id"
    )

    op.create_foreign_key(
        "fk_activities_user_id_users",
        "activities",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_provider_accounts_user_id_users",
        "provider_accounts",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_import_items_user_id_users",
        "import_items",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_activities_user_id_users", "activities", type_="foreignkey")
    op.drop_constraint(
        "fk_provider_accounts_user_id_users", "provider_accounts", type_="foreignkey"
    )
    op.drop_constraint("fk_import_items_user_id_users", "import_items", type_="foreignkey")

    op.execute(
        "ALTER TABLE provider_accounts RENAME CONSTRAINT "
        "uq_provider_accounts_provider_provider_user_id TO "
        "uq_provider_accounts_provider_external_id"
    )
    op.execute("ALTER TABLE provider_accounts RENAME COLUMN provider_user_id TO external_id")

    op.add_column("users", sa.Column("username", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("first_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.execute("ALTER TABLE users ALTER COLUMN id TYPE uuid USING id::uuid")
    op.execute("ALTER TABLE users ALTER COLUMN id SET DEFAULT uuidv7()")
    op.execute("ALTER TABLE activities ALTER COLUMN user_id TYPE uuid USING user_id::uuid")
    op.execute(
        "ALTER TABLE provider_accounts ALTER COLUMN user_id TYPE uuid USING user_id::uuid"
    )
    op.execute("ALTER TABLE import_items ALTER COLUMN user_id TYPE uuid USING user_id::uuid")

    op.create_foreign_key(
        "fk_activities_user_id_users",
        "activities",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_provider_accounts_user_id_users",
        "provider_accounts",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_import_items_user_id_users",
        "import_items",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_refresh_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name="pk_refresh_tokens"),
    )
    op.create_index("refresh_tokens_gc_idx", "refresh_tokens", ["expires_at"], unique=False)
    op.create_index("refresh_tokens_user_idx", "refresh_tokens", ["user_id"], unique=False)
