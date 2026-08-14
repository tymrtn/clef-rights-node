"""Add machine DDEX actors and append-only partner acknowledgements."""

from alembic import op
import sqlalchemy as sa


revision = "0013_ddex_acknowledgements"
down_revision = "0012_durable_webhooks"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = ("rn_ddex_exchanges", "rn_ddex_acknowledgements")


def _create_immutability_guards(dialect: str) -> None:
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION rn_reject_ddex_evidence_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Rights Node DDEX exchanges and acknowledgements are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION rn_reject_ddex_evidence_mutation()"
            )
            op.execute(
                f"CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION rn_reject_ddex_evidence_mutation()"
            )
    elif dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'Rights Node DDEX exchanges and acknowledgements are append-only'); END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'Rights Node DDEX exchanges and acknowledgements are append-only'); END
                """
            )


def _drop_immutability_guards(dialect: str) -> None:
    if dialect == "postgresql":
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"DROP TRIGGER IF EXISTS {table}_reject_update ON {table}"
            )
            op.execute(
                f"DROP TRIGGER IF EXISTS {table}_reject_delete ON {table}"
            )
        op.execute("DROP FUNCTION IF EXISTS rn_reject_ddex_evidence_mutation()")
    else:
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete")


def upgrade() -> None:
    with op.batch_alter_table("rn_ddex_exchanges") as batch:
        batch.alter_column(
            "generated_by_user_id",
            existing_type=sa.String(),
            nullable=True,
        )
        batch.add_column(
            sa.Column("generated_by_api_credential_id", sa.String(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_rn_ddex_exchange_api_credential",
            "rn_api_credentials",
            ["generated_by_api_credential_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "ck_rn_ddex_exchange_single_generator",
            "((generated_by_user_id IS NOT NULL AND generated_by_api_credential_id IS NULL) "
            "OR (generated_by_user_id IS NULL AND generated_by_api_credential_id IS NOT NULL))",
        )

    op.create_table(
        "rn_ddex_acknowledgements",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "exchange_id",
            sa.String(),
            sa.ForeignKey("rn_ddex_exchanges.id"),
            nullable=False,
        ),
        sa.Column("acknowledgement_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("partner_message_id", sa.String(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=True),
        sa.Column("payload_sha256", sa.String(), nullable=True),
        sa.Column("payload_text", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column(
            "recorded_by_user_id",
            sa.String(),
            sa.ForeignKey("rc_users.id"),
            nullable=True,
        ),
        sa.Column(
            "recorded_by_api_credential_id",
            sa.String(),
            sa.ForeignKey("rn_api_credentials.id"),
            nullable=True,
        ),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "exchange_id",
            "idempotency_key",
            name="uq_rn_ddex_ack_exchange_idempotency",
        ),
        sa.CheckConstraint(
            "status IN ('received', 'processing', 'accepted', 'rejected', 'error')",
            name="ck_rn_ddex_ack_status",
        ),
        sa.CheckConstraint(
            "acknowledgement_type IN ('transport', 'business')",
            name="ck_rn_ddex_ack_type",
        ),
        sa.CheckConstraint(
            "((recorded_by_user_id IS NOT NULL AND recorded_by_api_credential_id IS NULL) "
            "OR (recorded_by_user_id IS NULL AND recorded_by_api_credential_id IS NOT NULL))",
            name="ck_rn_ddex_ack_single_recorder",
        ),
    )
    op.create_index(
        "ix_rn_ddex_acknowledgements_exchange_id",
        "rn_ddex_acknowledgements",
        ["exchange_id"],
    )
    op.create_index(
        "ix_rn_ddex_acknowledgements_acknowledgement_type",
        "rn_ddex_acknowledgements",
        ["acknowledgement_type"],
    )
    op.create_index(
        "ix_rn_ddex_acknowledgements_status",
        "rn_ddex_acknowledgements",
        ["status"],
    )
    op.create_index(
        "ix_rn_ddex_acknowledgements_partner_message_id",
        "rn_ddex_acknowledgements",
        ["partner_message_id"],
    )
    op.create_index(
        "ix_rn_ddex_acknowledgements_payload_sha256",
        "rn_ddex_acknowledgements",
        ["payload_sha256"],
    )
    op.create_index(
        "ix_rn_ddex_acknowledgements_received_at",
        "rn_ddex_acknowledgements",
        ["received_at"],
    )
    _create_immutability_guards(op.get_bind().dialect.name)


def downgrade() -> None:
    bind = op.get_bind()
    acknowledgement_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM rn_ddex_acknowledgements")
    ).scalar_one()
    machine_exchange_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM rn_ddex_exchanges "
            "WHERE generated_by_api_credential_id IS NOT NULL"
        )
    ).scalar_one()
    if acknowledgement_count or machine_exchange_count:
        raise RuntimeError(
            "Downgrade blocked: revision 0012 cannot preserve DDEX acknowledgements "
            "or machine actor provenance"
        )
    dialect = bind.dialect.name
    _drop_immutability_guards(dialect)
    op.drop_table("rn_ddex_acknowledgements")
    with op.batch_alter_table("rn_ddex_exchanges") as batch:
        batch.drop_constraint("ck_rn_ddex_exchange_single_generator", type_="check")
        batch.drop_constraint("fk_rn_ddex_exchange_api_credential", type_="foreignkey")
        batch.drop_column("generated_by_api_credential_id")
        batch.alter_column(
            "generated_by_user_id",
            existing_type=sa.String(),
            nullable=False,
        )
