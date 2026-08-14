"""Track consumed magic links to prevent replay."""

from alembic import op
import sqlalchemy as sa


revision = "0004_auth_hardening"
down_revision = "0003_ddex_exchanges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rn_consumed_magic_links",
        sa.Column("token_sha256", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_rn_consumed_magic_links_email",
        "rn_consumed_magic_links",
        ["email"],
    )


def downgrade() -> None:
    op.drop_table("rn_consumed_magic_links")
