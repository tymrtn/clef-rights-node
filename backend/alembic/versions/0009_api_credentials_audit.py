"""Add organization API credentials and immutable v1 audit events."""

from alembic import op
import sqlalchemy as sa


revision = "0009_api_credentials_audit"
down_revision = "0008_authority_conflicts"
branch_labels = None
depends_on = None


PERMISSION_TABLE = "rn_permission_requests"


def _create_audit_immutability_guards(dialect: str) -> None:
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION rn_reject_audit_event_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Rights Node audit events are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER rn_audit_events_reject_update
            BEFORE UPDATE ON rn_audit_events
            FOR EACH ROW EXECUTE FUNCTION rn_reject_audit_event_mutation()
            """
        )
        op.execute(
            """
            CREATE TRIGGER rn_audit_events_reject_delete
            BEFORE DELETE ON rn_audit_events
            FOR EACH ROW EXECUTE FUNCTION rn_reject_audit_event_mutation()
            """
        )
        return
    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER rn_audit_events_reject_update
            BEFORE UPDATE ON rn_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Rights Node audit events are append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER rn_audit_events_reject_delete
            BEFORE DELETE ON rn_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Rights Node audit events are append-only');
            END
            """
        )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "rn_api_credentials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("token_prefix", sa.String(), nullable=False, unique=True),
        sa.Column("token_sha256", sa.String(), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_rn_api_credentials_org_id", "rn_api_credentials", ["org_id"])
    op.create_index(
        "ix_rn_api_credentials_token_prefix",
        "rn_api_credentials",
        ["token_prefix"],
        unique=True,
    )
    op.create_index(
        "ix_rn_api_credentials_token_sha256",
        "rn_api_credentials",
        ["token_sha256"],
        unique=True,
    )

    op.create_table(
        "rn_audit_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=True),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column(
            "actor_api_credential_id",
            sa.String(),
            sa.ForeignKey("rn_api_credentials.id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "NOT (actor_user_id IS NOT NULL AND actor_api_credential_id IS NOT NULL)",
            name="ck_rn_audit_single_actor_identity",
        ),
    )
    for column in (
        "org_id",
        "actor_type",
        "actor_user_id",
        "actor_api_credential_id",
        "action",
        "resource_type",
        "resource_id",
        "created_at",
    ):
        op.create_index(f"ix_rn_audit_events_{column}", "rn_audit_events", [column])
    _create_audit_immutability_guards(dialect)

    if dialect == "sqlite":
        naming_convention = {
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        }
        with op.batch_alter_table(
            PERMISSION_TABLE,
            recreate="always",
            naming_convention=naming_convention,
        ) as batch:
            batch.alter_column(
                "requested_by_user_id",
                existing_type=sa.String(),
                nullable=True,
            )
            batch.add_column(sa.Column("requested_by_api_credential_id", sa.String(), nullable=True))
            batch.add_column(sa.Column("decided_by_api_credential_id", sa.String(), nullable=True))
            batch.create_foreign_key(
                "fk_rn_permission_requests_requested_by_api_credential_id",
                "rn_api_credentials",
                ["requested_by_api_credential_id"],
                ["id"],
            )
            batch.create_foreign_key(
                "fk_rn_permission_requests_decided_by_api_credential_id",
                "rn_api_credentials",
                ["decided_by_api_credential_id"],
                ["id"],
            )
            batch.create_check_constraint(
                "rn_permission_request_single_request_actor",
                "((requested_by_user_id IS NOT NULL AND requested_by_api_credential_id IS NULL) "
                "OR (requested_by_user_id IS NULL AND requested_by_api_credential_id IS NOT NULL))",
            )
            batch.create_check_constraint(
                "rn_permission_request_single_decision_actor",
                "NOT (decided_by_user_id IS NOT NULL AND decided_by_api_credential_id IS NOT NULL)",
            )
    else:
        op.alter_column(
            PERMISSION_TABLE,
            "requested_by_user_id",
            existing_type=sa.String(),
            nullable=True,
        )
        op.add_column(
            PERMISSION_TABLE,
            sa.Column("requested_by_api_credential_id", sa.String(), nullable=True),
        )
        op.add_column(
            PERMISSION_TABLE,
            sa.Column("decided_by_api_credential_id", sa.String(), nullable=True),
        )
        op.create_foreign_key(
            "fk_rn_permission_requests_requested_by_api_credential_id",
            PERMISSION_TABLE,
            "rn_api_credentials",
            ["requested_by_api_credential_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_rn_permission_requests_decided_by_api_credential_id",
            PERMISSION_TABLE,
            "rn_api_credentials",
            ["decided_by_api_credential_id"],
            ["id"],
        )
        op.create_check_constraint(
            "ck_rn_permission_request_single_request_actor",
            PERMISSION_TABLE,
            "((requested_by_user_id IS NOT NULL AND requested_by_api_credential_id IS NULL) "
            "OR (requested_by_user_id IS NULL AND requested_by_api_credential_id IS NOT NULL))",
        )
        op.create_check_constraint(
            "ck_rn_permission_request_single_decision_actor",
            PERMISSION_TABLE,
            "NOT (decided_by_user_id IS NOT NULL AND decided_by_api_credential_id IS NOT NULL)",
        )
    op.create_index(
        "ix_rn_permission_requests_requested_by_api_credential_id",
        PERMISSION_TABLE,
        ["requested_by_api_credential_id"],
    )
    op.create_index(
        "ix_rn_permission_requests_decided_by_api_credential_id",
        PERMISSION_TABLE,
        ["decided_by_api_credential_id"],
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.drop_index(
        "ix_rn_permission_requests_decided_by_api_credential_id",
        table_name=PERMISSION_TABLE,
    )
    op.drop_index(
        "ix_rn_permission_requests_requested_by_api_credential_id",
        table_name=PERMISSION_TABLE,
    )
    if dialect == "sqlite":
        naming_convention = {
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        }
        with op.batch_alter_table(
            PERMISSION_TABLE,
            recreate="always",
            naming_convention=naming_convention,
        ) as batch:
            batch.drop_constraint(
                "ck_rn_permission_requests_rn_permission_request_single_decision_actor",
                type_="check",
            )
            batch.drop_constraint(
                "ck_rn_permission_requests_rn_permission_request_single_request_actor",
                type_="check",
            )
            batch.drop_constraint(
                "fk_rn_permission_requests_decided_by_api_credential_id",
                type_="foreignkey",
            )
            batch.drop_constraint(
                "fk_rn_permission_requests_requested_by_api_credential_id",
                type_="foreignkey",
            )
            batch.drop_column("decided_by_api_credential_id")
            batch.drop_column("requested_by_api_credential_id")
            batch.alter_column(
                "requested_by_user_id",
                existing_type=sa.String(),
                nullable=False,
            )
    else:
        op.drop_constraint(
            "ck_rn_permission_request_single_decision_actor",
            PERMISSION_TABLE,
            type_="check",
        )
        op.drop_constraint(
            "ck_rn_permission_request_single_request_actor",
            PERMISSION_TABLE,
            type_="check",
        )
        op.drop_constraint(
            "fk_rn_permission_requests_decided_by_api_credential_id",
            PERMISSION_TABLE,
            type_="foreignkey",
        )
        op.drop_constraint(
            "fk_rn_permission_requests_requested_by_api_credential_id",
            PERMISSION_TABLE,
            type_="foreignkey",
        )
        op.drop_column(PERMISSION_TABLE, "decided_by_api_credential_id")
        op.drop_column(PERMISSION_TABLE, "requested_by_api_credential_id")
        op.alter_column(
            PERMISSION_TABLE,
            "requested_by_user_id",
            existing_type=sa.String(),
            nullable=False,
        )

    if dialect == "postgresql":
        op.execute("DROP TRIGGER rn_audit_events_reject_update ON rn_audit_events")
        op.execute("DROP TRIGGER rn_audit_events_reject_delete ON rn_audit_events")
        op.execute("DROP FUNCTION rn_reject_audit_event_mutation()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER rn_audit_events_reject_update")
        op.execute("DROP TRIGGER rn_audit_events_reject_delete")
    op.drop_table("rn_audit_events")
    op.drop_table("rn_api_credentials")
