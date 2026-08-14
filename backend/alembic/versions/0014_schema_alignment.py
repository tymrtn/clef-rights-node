"""Align query indexes with the production Rights Node ORM."""

from alembic import op


revision = "0014_schema_alignment"
down_revision = "0013_ddex_acknowledgements"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "ix_rn_authority_claims_rights_contract_id",
        "rn_authority_claims",
        ["rights_contract_id"],
    ),
    (
        "ix_rn_authority_claims_right_type",
        "rn_authority_claims",
        ["right_type"],
    ),
    (
        "ix_rn_permission_requests_intended_usage",
        "rn_permission_requests",
        ["intended_usage"],
    ),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
