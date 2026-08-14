"""Persist validated DDEX interchange artifacts."""

from alembic import op
import sqlalchemy as sa


revision = "0003_ddex_exchanges"
down_revision = "0002_rights_node_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rn_ddex_exchanges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "permission_request_id",
            sa.String(),
            sa.ForeignKey("rn_permission_requests.id"),
            nullable=False,
        ),
        sa.Column("message_id", sa.String(), nullable=False, unique=True),
        sa.Column("standard", sa.String(), nullable=False, server_default="MWL"),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False, server_default="outbound"),
        sa.Column("payload_sha256", sa.String(), nullable=False, unique=True),
        sa.Column("payload_xml", sa.Text(), nullable=False),
        sa.Column("validation_status", sa.String(), nullable=False, server_default="schema_valid"),
        sa.Column("generated_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_rn_ddex_exchanges_permission_request_id",
        "rn_ddex_exchanges",
        ["permission_request_id"],
    )
    op.create_index(
        "ix_rn_ddex_exchanges_message_id",
        "rn_ddex_exchanges",
        ["message_id"],
        unique=True,
    )
    op.create_index(
        "ix_rn_ddex_exchanges_message_type",
        "rn_ddex_exchanges",
        ["message_type"],
    )
    op.create_index(
        "ix_rn_ddex_exchanges_payload_sha256",
        "rn_ddex_exchanges",
        ["payload_sha256"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("rn_ddex_exchanges")
