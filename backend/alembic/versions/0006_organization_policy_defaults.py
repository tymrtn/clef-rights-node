"""Store organization onboarding and policy defaults."""

from alembic import op
import sqlalchemy as sa


revision = "0006_org_policy_defaults"
down_revision = "0005_authority_review_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rn_organizations") as batch:
        batch.add_column(sa.Column("profile", sa.JSON(), nullable=True))
    op.execute("UPDATE rn_organizations SET profile = '{}' WHERE profile IS NULL")
    with op.batch_alter_table("rn_organizations") as batch:
        batch.alter_column("profile", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("rn_organizations") as batch:
        batch.drop_column("profile")
