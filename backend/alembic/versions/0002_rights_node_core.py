"""Rights Node organizations, authority, permissions, and receipts."""

from alembic import op
import sqlalchemy as sa


revision = "0002_rights_node_core"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rights_contracts", sa.Column("owner_org_id", sa.String(), nullable=True))
    op.create_index("ix_rights_contracts_owner_org_id", "rights_contracts", ["owner_org_id"])
    op.add_column("rights_history", sa.Column("owner_org_id", sa.String(), nullable=True))
    op.create_index("ix_rights_history_owner_org_id", "rights_history", ["owner_org_id"])

    op.create_table(
        "rn_organizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rn_organizations_slug", "rn_organizations", ["slug"], unique=True)

    op.create_table(
        "rn_organization_memberships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "user_id", name="uq_rn_org_membership"),
    )
    op.create_index("ix_rn_memberships_org_id", "rn_organization_memberships", ["org_id"])
    op.create_index("ix_rn_memberships_user_id", "rn_organization_memberships", ["user_id"])

    op.create_table(
        "rn_authority_claims",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("rights_contract_id", sa.String(), sa.ForeignKey("rights_contracts.id"), nullable=False),
        sa.Column("work_key", sa.String(), nullable=False),
        sa.Column("right_type", sa.String(), nullable=False),
        sa.Column("territory", sa.String(), nullable=False, server_default="worldwide"),
        sa.Column("status", sa.String(), nullable=False, server_default="self_asserted"),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("asserted_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=False),
        sa.Column("verified_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_rn_authority_claims_org_id", "rn_authority_claims", ["org_id"])
    op.create_index("ix_rn_authority_claims_work_key", "rn_authority_claims", ["work_key"])
    op.create_index("ix_rn_authority_claims_status", "rn_authority_claims", ["status"])

    op.create_table(
        "rn_permission_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("requester_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("authority_claim_id", sa.String(), sa.ForeignKey("rn_authority_claims.id"), nullable=False),
        sa.Column("work_key", sa.String(), nullable=False),
        sa.Column("intended_usage", sa.String(), nullable=False),
        sa.Column("territory", sa.String(), nullable=False, server_default="worldwide"),
        sa.Column("term_start", sa.String(), nullable=True),
        sa.Column("term_end", sa.String(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("requested_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=False),
        sa.Column("decided_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_rn_permission_requests_requester_org_id", "rn_permission_requests", ["requester_org_id"])
    op.create_index("ix_rn_permission_requests_authority_claim_id", "rn_permission_requests", ["authority_claim_id"])
    op.create_index("ix_rn_permission_requests_work_key", "rn_permission_requests", ["work_key"])
    op.create_index("ix_rn_permission_requests_status", "rn_permission_requests", ["status"])

    op.create_table(
        "rn_permission_receipts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("permission_request_id", sa.String(), sa.ForeignKey("rn_permission_requests.id"), nullable=False, unique=True),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False, unique=True),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("transparency_sequence", sa.Integer(), nullable=False, unique=True),
        sa.Column("previous_entry_hash", sa.String(), nullable=True),
        sa.Column("entry_hash", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rn_receipts_permission_request_id", "rn_permission_receipts", ["permission_request_id"], unique=True)
    op.create_index("ix_rn_receipts_payload_hash", "rn_permission_receipts", ["payload_hash"], unique=True)
    op.create_index("ix_rn_receipts_node_id", "rn_permission_receipts", ["node_id"])
    op.create_index("ix_rn_receipts_key_id", "rn_permission_receipts", ["key_id"])
    op.create_index("ix_rn_receipts_transparency_sequence", "rn_permission_receipts", ["transparency_sequence"], unique=True)
    op.create_index("ix_rn_receipts_entry_hash", "rn_permission_receipts", ["entry_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("rn_permission_receipts")
    op.drop_table("rn_permission_requests")
    op.drop_table("rn_authority_claims")
    op.drop_table("rn_organization_memberships")
    op.drop_table("rn_organizations")
    op.drop_index("ix_rights_history_owner_org_id", table_name="rights_history")
    op.drop_column("rights_history", "owner_org_id")
    op.drop_index("ix_rights_contracts_owner_org_id", table_name="rights_contracts")
    op.drop_column("rights_contracts", "owner_org_id")
