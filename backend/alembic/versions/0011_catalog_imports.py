"""Add staged organization catalog imports, clients, versions, and assignments."""

from alembic import op
import sqlalchemy as sa


revision = "0011_catalog_imports"
down_revision = "0010_settlement_ledger"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = ("rn_catalog_assets", "rn_catalog_assignments")


def _create_immutability_guards(dialect: str) -> None:
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION rn_reject_catalog_record_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Rights Node catalog assets and assignments are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION rn_reject_catalog_record_mutation()"
            )
            op.execute(
                f"CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION rn_reject_catalog_record_mutation()"
            )
    elif dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'Rights Node catalog assets and assignments are append-only'); END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'Rights Node catalog assets and assignments are append-only'); END
                """
            )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "rn_catalog_clients",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("external_reference", sa.String(), nullable=False),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("created_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "external_reference", name="uq_rn_catalog_client_reference"),
        sa.CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) OR "
            "(created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_catalog_client_single_creator",
        ),
    )
    op.create_index("ix_rn_catalog_clients_org_id", "rn_catalog_clients", ["org_id"])

    op.create_table(
        "rn_catalog_import_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_sha256", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("created_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("committed_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("committed_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("org_id", "file_sha256", name="uq_rn_catalog_import_file"),
        sa.CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) OR "
            "(created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_catalog_import_single_creator",
        ),
        sa.CheckConstraint(
            "NOT (committed_by_user_id IS NOT NULL AND committed_by_api_credential_id IS NOT NULL)",
            name="ck_rn_catalog_import_single_committer",
        ),
    )
    for column in ("org_id", "file_sha256", "status"):
        op.create_index(f"ix_rn_catalog_import_batches_{column}", "rn_catalog_import_batches", [column])

    op.create_table(
        "rn_catalog_assets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("work_key", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("artist", sa.String(), nullable=True),
        sa.Column("iswc", sa.String(), nullable=True),
        sa.Column("isrc", sa.String(), nullable=True),
        sa.Column("mlc_song_code", sa.String(), nullable=True),
        sa.Column("territory", sa.String(), nullable=False),
        sa.Column("source_reference", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("import_batch_id", sa.String(), sa.ForeignKey("rn_catalog_import_batches.id"), nullable=True),
        sa.Column("import_row_number", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("created_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "work_key", "version", name="uq_rn_catalog_asset_version"),
        sa.CheckConstraint("version > 0", name="ck_rn_catalog_asset_version_positive"),
        sa.CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) OR "
            "(created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_catalog_asset_single_creator",
        ),
    )
    for column in ("org_id", "work_key", "item_type", "title", "artist", "iswc", "isrc", "mlc_song_code", "import_batch_id"):
        op.create_index(f"ix_rn_catalog_assets_{column}", "rn_catalog_assets", [column])

    op.create_table(
        "rn_catalog_import_rows",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("batch_id", sa.String(), sa.ForeignKey("rn_catalog_import_batches.id"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("existing_item_id", sa.String(), sa.ForeignKey("rn_catalog_assets.id"), nullable=True),
        sa.Column("resolution", sa.String(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("resolved_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("imported_item_id", sa.String(), sa.ForeignKey("rn_catalog_assets.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_rn_catalog_import_row_number"),
        sa.CheckConstraint(
            "NOT (resolved_by_user_id IS NOT NULL AND resolved_by_api_credential_id IS NOT NULL)",
            name="ck_rn_catalog_import_row_single_resolver",
        ),
    )
    for column in ("batch_id", "status", "existing_item_id", "imported_item_id"):
        op.create_index(f"ix_rn_catalog_import_rows_{column}", "rn_catalog_import_rows", [column])

    op.create_table(
        "rn_catalog_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("catalog_asset_id", sa.String(), sa.ForeignKey("rn_catalog_assets.id"), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("rn_catalog_clients.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("created_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) OR "
            "(created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_catalog_assignment_single_creator",
        ),
    )
    for column in ("catalog_asset_id", "client_id", "created_at"):
        op.create_index(f"ix_rn_catalog_assignments_{column}", "rn_catalog_assignments", [column])
    _create_immutability_guards(dialect)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete ON {table}")
        op.execute("DROP FUNCTION IF EXISTS rn_reject_catalog_record_mutation()")
    elif dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete")
    for table in (
        "rn_catalog_assignments",
        "rn_catalog_import_rows",
        "rn_catalog_assets",
        "rn_catalog_import_batches",
        "rn_catalog_clients",
    ):
        op.drop_table(table)
