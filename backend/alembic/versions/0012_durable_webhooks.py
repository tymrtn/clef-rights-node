"""Add encrypted endpoints and durable webhook delivery outbox."""

from alembic import op
import sqlalchemy as sa


revision = "0012_durable_webhooks"
down_revision = "0011_catalog_imports"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = ("rn_webhook_events", "rn_webhook_attempts")


def _create_immutability_guards(dialect: str) -> None:
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION rn_reject_webhook_evidence_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Rights Node webhook events and attempts are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION rn_reject_webhook_evidence_mutation()"
            )
            op.execute(
                f"CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION rn_reject_webhook_evidence_mutation()"
            )
    elif dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'Rights Node webhook events and attempts are append-only'); END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'Rights Node webhook events and attempts are append-only'); END
                """
            )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "rn_webhook_endpoints",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("created_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) OR "
            "(created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_webhook_endpoint_single_creator",
        ),
    )
    for column in ("org_id", "enabled"):
        op.create_index(f"ix_rn_webhook_endpoints_{column}", "rn_webhook_endpoints", [column])

    op.create_table(
        "rn_webhook_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    for column in ("org_id", "event", "occurred_at"):
        op.create_index(f"ix_rn_webhook_events_{column}", "rn_webhook_events", [column])

    op.create_table(
        "rn_webhook_deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("endpoint_id", sa.String(), sa.ForeignKey("rn_webhook_endpoints.id"), nullable=False),
        sa.Column("event_id", sa.String(), sa.ForeignKey("rn_webhook_events.id"), nullable=False),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("endpoint_id", "event_id", name="uq_rn_webhook_endpoint_event"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_rn_webhook_attempt_count_nonnegative"),
    )
    for column in ("endpoint_id", "event_id", "org_id", "status", "next_attempt_at", "lease_until"):
        op.create_index(f"ix_rn_webhook_deliveries_{column}", "rn_webhook_deliveries", [column])

    op.create_table(
        "rn_webhook_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("delivery_id", sa.String(), sa.ForeignKey("rn_webhook_deliveries.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("request_timestamp", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("delivery_id", "attempt_number", name="uq_rn_webhook_delivery_attempt"),
        sa.CheckConstraint("attempt_number > 0", name="ck_rn_webhook_attempt_positive"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_rn_webhook_duration_nonnegative"),
    )
    for column in ("delivery_id", "outcome", "created_at"):
        op.create_index(f"ix_rn_webhook_attempts_{column}", "rn_webhook_attempts", [column])
    _create_immutability_guards(dialect)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete ON {table}")
        op.execute("DROP FUNCTION IF EXISTS rn_reject_webhook_evidence_mutation()")
    elif dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete")
    for table in (
        "rn_webhook_attempts",
        "rn_webhook_deliveries",
        "rn_webhook_events",
        "rn_webhook_endpoints",
    ):
        op.drop_table(table)
