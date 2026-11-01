"""Recoverable, guest-scoped sandbox walkthrough."""
from alembic import op
import sqlalchemy as sa

revision = "0018_sandbox_tour"
down_revision = "0017_receipt_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("rn_sandbox_tours",
        sa.Column("user_id", sa.String(), sa.ForeignKey("rc_users.id"), primary_key=True),
        sa.Column("lease_token", sa.String(), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM rn_sandbox_tours")).scalar_one():
        raise RuntimeError("Downgrade blocked: revision 0017 cannot preserve saved walkthroughs and preparation leases")
    op.drop_table("rn_sandbox_tours")
