"""Add auditable permission routing, grant obligations, and compliance evidence."""

from alembic import op
import sqlalchemy as sa


revision = "0015_permission_administration"
down_revision = "0014_schema_alignment"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = (
    "rn_permission_review_assignments",
    "rn_permission_usage_reports",
    "rn_permission_compliance_reviews",
)


def _create_immutability_guards(dialect: str) -> None:
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION rn_reject_permission_administration_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Rights Node permission administration and compliance records are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION rn_reject_permission_administration_mutation()"
            )
            op.execute(
                f"CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION rn_reject_permission_administration_mutation()"
            )
    elif dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'Rights Node permission administration and compliance records are append-only'); END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'Rights Node permission administration and compliance records are append-only'); END
                """
            )


def _drop_immutability_guards(dialect: str) -> None:
    if dialect == "postgresql":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete ON {table}")
        op.execute("DROP FUNCTION IF EXISTS rn_reject_permission_administration_mutation()")
    else:
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete")


def upgrade() -> None:
    with op.batch_alter_table("rn_permission_requests") as batch:
        batch.add_column(
            sa.Column(
                "license_obligations",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    op.create_table(
        "rn_permission_review_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("permission_request_id", sa.String(), sa.ForeignKey("rn_permission_requests.id"), nullable=False),
        sa.Column("authority_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reviewer_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("assigned_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("assigned_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("action IN ('assigned', 'cleared')", name="ck_rn_permission_review_assignment_action"),
        sa.CheckConstraint(
            "((assigned_by_user_id IS NOT NULL AND assigned_by_api_credential_id IS NULL) "
            "OR (assigned_by_user_id IS NULL AND assigned_by_api_credential_id IS NOT NULL))",
            name="ck_rn_permission_review_assignment_single_actor",
        ),
        sa.CheckConstraint(
            "((action = 'assigned' AND reviewer_user_id IS NOT NULL) "
            "OR (action = 'cleared' AND reviewer_user_id IS NULL))",
            name="ck_rn_permission_review_assignment_reviewer",
        ),
    )
    op.create_index("ix_rn_permission_review_assignments_permission_request_id", "rn_permission_review_assignments", ["permission_request_id"])
    op.create_index("ix_rn_permission_review_assignments_authority_org_id", "rn_permission_review_assignments", ["authority_org_id"])
    op.create_index("ix_rn_permission_review_assignments_action", "rn_permission_review_assignments", ["action"])
    op.create_index("ix_rn_permission_review_assignments_reviewer_user_id", "rn_permission_review_assignments", ["reviewer_user_id"])
    op.create_index("ix_rn_permission_review_assignments_created_at", "rn_permission_review_assignments", ["created_at"])

    op.create_table(
        "rn_permission_usage_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("permission_request_id", sa.String(), sa.ForeignKey("rn_permission_requests.id"), nullable=False),
        sa.Column("requester_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("publication_url", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("declared_credit_text", sa.Text(), nullable=True),
        sa.Column("declared_backlink_url", sa.String(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("submitted_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("submitted_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("permission_request_id", "idempotency_key", name="uq_rn_permission_usage_report_idempotency"),
        sa.CheckConstraint(
            "((submitted_by_user_id IS NOT NULL AND submitted_by_api_credential_id IS NULL) "
            "OR (submitted_by_user_id IS NULL AND submitted_by_api_credential_id IS NOT NULL))",
            name="ck_rn_permission_usage_report_single_actor",
        ),
    )
    op.create_index("ix_rn_permission_usage_reports_permission_request_id", "rn_permission_usage_reports", ["permission_request_id"])
    op.create_index("ix_rn_permission_usage_reports_requester_org_id", "rn_permission_usage_reports", ["requester_org_id"])
    op.create_index("ix_rn_permission_usage_reports_published_at", "rn_permission_usage_reports", ["published_at"])
    op.create_index("ix_rn_permission_usage_reports_created_at", "rn_permission_usage_reports", ["created_at"])

    op.create_table(
        "rn_permission_compliance_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("usage_report_id", sa.String(), sa.ForeignKey("rn_permission_usage_reports.id"), nullable=False),
        sa.Column("permission_request_id", sa.String(), sa.ForeignKey("rn_permission_requests.id"), nullable=False),
        sa.Column("authority_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("reviewed_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("usage_report_id", "idempotency_key", name="uq_rn_permission_compliance_review_idempotency"),
        sa.CheckConstraint("outcome IN ('compliant', 'noncompliant', 'inconclusive')", name="ck_rn_permission_compliance_review_outcome"),
        sa.CheckConstraint(
            "((reviewed_by_user_id IS NOT NULL AND reviewed_by_api_credential_id IS NULL) "
            "OR (reviewed_by_user_id IS NULL AND reviewed_by_api_credential_id IS NOT NULL))",
            name="ck_rn_permission_compliance_review_single_actor",
        ),
    )
    op.create_index("ix_rn_permission_compliance_reviews_usage_report_id", "rn_permission_compliance_reviews", ["usage_report_id"])
    op.create_index("ix_rn_permission_compliance_reviews_permission_request_id", "rn_permission_compliance_reviews", ["permission_request_id"])
    op.create_index("ix_rn_permission_compliance_reviews_authority_org_id", "rn_permission_compliance_reviews", ["authority_org_id"])
    op.create_index("ix_rn_permission_compliance_reviews_outcome", "rn_permission_compliance_reviews", ["outcome"])
    op.create_index("ix_rn_permission_compliance_reviews_created_at", "rn_permission_compliance_reviews", ["created_at"])

    _create_immutability_guards(op.get_bind().dialect.name)


def downgrade() -> None:
    bind = op.get_bind()
    evidence_count = sum(
        bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        for table in IMMUTABLE_TABLES
    )
    obligation_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM rn_permission_requests "
            "WHERE license_obligations IS NOT NULL "
            "AND CAST(license_obligations AS TEXT) NOT IN ('{}', 'null')"
        )
    ).scalar_one()
    if evidence_count or obligation_count:
        raise RuntimeError(
            "Downgrade blocked: revision 0014 cannot preserve permission assignments, "
            "license obligations, or compliance evidence"
        )
    dialect = bind.dialect.name
    _drop_immutability_guards(dialect)
    op.drop_table("rn_permission_compliance_reviews")
    op.drop_table("rn_permission_usage_reports")
    op.drop_table("rn_permission_review_assignments")
    with op.batch_alter_table("rn_permission_requests") as batch:
        batch.drop_column("license_obligations")
