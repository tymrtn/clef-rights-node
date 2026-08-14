"""Separate authority review audit fields from successful verification fields."""

from alembic import op
import sqlalchemy as sa


revision = "0005_authority_review_audit"
down_revision = "0004_auth_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rn_authority_claims") as batch:
        batch.add_column(sa.Column("reviewed_by_user_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key(
            "fk_rn_authority_claims_reviewed_by_user_id",
            "rc_users",
            ["reviewed_by_user_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("rn_authority_claims") as batch:
        batch.drop_constraint(
            "fk_rn_authority_claims_reviewed_by_user_id", type_="foreignkey"
        )
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by_user_id")
