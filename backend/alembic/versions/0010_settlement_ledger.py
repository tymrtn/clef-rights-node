"""Add the immutable settlement, royalty, payment, payout, and reconciliation ledger."""

from alembic import op
import sqlalchemy as sa


revision = "0010_settlement_ledger"
down_revision = "0009_api_credentials_audit"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = (
    "rn_settlements",
    "rn_settlement_beneficiaries",
    "rn_settlement_entries",
    "rn_settlement_reconciliations",
)


def _create_immutability_guards(dialect: str) -> None:
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION rn_reject_settlement_ledger_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Rights Node settlement ledger records are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_update
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION rn_reject_settlement_ledger_mutation()
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_delete
                BEFORE DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION rn_reject_settlement_ledger_mutation()
                """
            )
        return
    if dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_update
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'Rights Node settlement ledger records are append-only');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_delete
                BEFORE DELETE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'Rights Node settlement ledger records are append-only');
                END
                """
            )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "rn_settlements",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "permission_request_id",
            sa.String(),
            sa.ForeignKey("rn_permission_requests.id"),
            nullable=False,
        ),
        sa.Column("requester_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("authority_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("minimum_commitment_minor", sa.BigInteger(), nullable=False),
        sa.Column("minimum_recoupable", sa.Boolean(), nullable=False),
        sa.Column("royalty_rate_bps", sa.Integer(), nullable=False),
        sa.Column("royalty_basis", sa.String(), nullable=False),
        sa.Column("terms", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column(
            "created_by_api_credential_id",
            sa.String(),
            sa.ForeignKey("rn_api_credentials.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("permission_request_id", name="uq_rn_settlement_permission_request"),
        sa.CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) "
            "OR (created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_settlement_single_creator",
        ),
        sa.CheckConstraint(
            "minimum_commitment_minor >= 0",
            name="ck_rn_settlement_minimum_nonnegative",
        ),
        sa.CheckConstraint(
            "royalty_rate_bps >= 0 AND royalty_rate_bps <= 10000",
            name="ck_rn_settlement_rate_bps",
        ),
    )
    for column in ("permission_request_id", "requester_org_id", "authority_org_id"):
        op.create_index(f"ix_rn_settlements_{column}", "rn_settlements", [column])

    op.create_table(
        "rn_settlement_beneficiaries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("settlement_id", sa.String(), sa.ForeignKey("rn_settlements.id"), nullable=False),
        sa.Column(
            "beneficiary_org_id",
            sa.String(),
            sa.ForeignKey("rn_organizations.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("identifier", sa.String(), nullable=False),
        sa.Column("share_bps", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "settlement_id",
            "identifier",
            name="uq_rn_settlement_beneficiary_identifier",
        ),
        sa.CheckConstraint(
            "share_bps > 0 AND share_bps <= 10000",
            name="ck_rn_settlement_beneficiary_share",
        ),
    )
    op.create_index(
        "ix_rn_settlement_beneficiaries_settlement_id",
        "rn_settlement_beneficiaries",
        ["settlement_id"],
    )
    op.create_index(
        "ix_rn_settlement_beneficiaries_beneficiary_org_id",
        "rn_settlement_beneficiaries",
        ["beneficiary_org_id"],
    )

    op.create_table(
        "rn_settlement_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("settlement_id", sa.String(), sa.ForeignKey("rn_settlements.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "beneficiary_id",
            sa.String(),
            sa.ForeignKey("rn_settlement_beneficiaries.id"),
            nullable=True,
        ),
        sa.Column("period_start", sa.String(), nullable=True),
        sa.Column("period_end", sa.String(), nullable=True),
        sa.Column("external_reference", sa.String(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("calculation", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("recorded_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column(
            "recorded_by_api_credential_id",
            sa.String(),
            sa.ForeignKey("rn_api_credentials.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "settlement_id",
            "idempotency_key",
            name="uq_rn_settlement_entry_idempotency",
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_rn_settlement_entry_amount_positive"),
        sa.CheckConstraint(
            "((recorded_by_user_id IS NOT NULL AND recorded_by_api_credential_id IS NULL) "
            "OR (recorded_by_user_id IS NULL AND recorded_by_api_credential_id IS NOT NULL))",
            name="ck_rn_settlement_entry_single_actor",
        ),
    )
    for column in ("settlement_id", "kind", "beneficiary_id", "created_at"):
        op.create_index(f"ix_rn_settlement_entries_{column}", "rn_settlement_entries", [column])

    op.create_table(
        "rn_settlement_reconciliations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("settlement_id", sa.String(), sa.ForeignKey("rn_settlements.id"), nullable=False),
        sa.Column(
            "receipt_id",
            sa.String(),
            sa.ForeignKey("rn_permission_receipts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("assertion_type", sa.String(), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("ledger_digest", sa.String(), nullable=False),
        sa.Column("totals", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("recorded_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column(
            "recorded_by_api_credential_id",
            sa.String(),
            sa.ForeignKey("rn_api_credentials.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "settlement_id",
            "idempotency_key",
            name="uq_rn_reconciliation_idempotency",
        ),
        sa.CheckConstraint(
            "((recorded_by_user_id IS NOT NULL AND recorded_by_api_credential_id IS NULL) "
            "OR (recorded_by_user_id IS NULL AND recorded_by_api_credential_id IS NOT NULL))",
            name="ck_rn_reconciliation_single_actor",
        ),
    )
    for column in ("settlement_id", "receipt_id", "status", "ledger_digest", "created_at"):
        op.create_index(
            f"ix_rn_settlement_reconciliations_{column}",
            "rn_settlement_reconciliations",
            [column],
        )
    _create_immutability_guards(dialect)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete ON {table}")
        op.execute("DROP FUNCTION IF EXISTS rn_reject_settlement_ledger_mutation()")
    elif dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete")

    for table in (
        "rn_settlement_reconciliations",
        "rn_settlement_entries",
        "rn_settlement_beneficiaries",
        "rn_settlements",
    ):
        op.drop_table(table)
