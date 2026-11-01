"""Explicitly consented catalog discovery publications."""
from alembic import op
import sqlalchemy as sa

revision = "0019_catalog_federation"
down_revision = "0018_sandbox_tour"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("rn_catalog_publications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("authority_claim_id", sa.String(), sa.ForeignKey("rn_authority_claims.id"), nullable=False, unique=True),
        sa.Column("public_payload", sa.JSON(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("basis_hash", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(), nullable=True))
    op.create_index("ix_rn_catalog_publications_org_id", "rn_catalog_publications", ["org_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM rn_catalog_publications")).scalar_one():
        raise RuntimeError("Downgrade blocked: revision 0018 cannot preserve catalog publication consent")
    op.drop_table("rn_catalog_publications")
