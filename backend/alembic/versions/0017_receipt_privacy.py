"""Separate public receipt statements and reviewed data lifecycle controls."""
from alembic import op
import sqlalchemy as sa

revision = "0017_receipt_privacy"
down_revision = "0016_service_heartbeats"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("rn_organization_privacy",
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), primary_key=True),
        sa.Column("publish_public_receipts", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("receipt_retention_days", sa.Integer(), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("receipt_retention_days IS NULL OR receipt_retention_days BETWEEN 1 AND 36500", name="ck_rn_privacy_retention"))
    op.create_table("rn_receipt_disclosures",
        sa.Column("receipt_id", sa.String(), sa.ForeignKey("rn_permission_receipts.id"), primary_key=True),
        sa.Column("public_id", sa.String(), nullable=False, unique=True),
        sa.Column("authority_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("requester_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("commitment_nonce", sa.String(), nullable=True),
        sa.Column("private_commitment", sa.String(), nullable=False),
        sa.Column("public_receipt", sa.JSON(), nullable=True),
        sa.Column("public_sequence", sa.Integer(), nullable=True, unique=True),
        sa.Column("public_entry_hash", sa.String(), nullable=True, unique=True),
        sa.Column("retain_until", sa.DateTime(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
        sa.Column("erased_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    for col in ("authority_org_id", "requester_org_id"):
        op.create_index(f"ix_rn_receipt_disclosures_{col}", "rn_receipt_disclosures", [col])
    op.create_table("rn_privacy_erasure_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("resource_hash", sa.String(), nullable=False),
        sa.Column("required_org_ids", sa.JSON(), nullable=False),
        sa.Column("approved_org_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="requested"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True))
    for col in ("org_id", "resource_id"):
        op.create_index(f"ix_rn_privacy_erasure_requests_{col}", "rn_privacy_erasure_requests", [col])


def downgrade():
    bind = op.get_bind()
    for table in ("rn_privacy_erasure_requests", "rn_receipt_disclosures", "rn_organization_privacy"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(
                "Downgrade blocked: revision 0016 cannot preserve disclosure consent, "
                "private evidence commitments, retention decisions or erasure records"
            )
    op.drop_table("rn_privacy_erasure_requests")
    op.drop_table("rn_receipt_disclosures")
    op.drop_table("rn_organization_privacy")
