"""Add shared operational heartbeats for supervised node services."""

from alembic import op
import sqlalchemy as sa


revision = "0016_service_heartbeats"
down_revision = "0015_permission_administration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rn_service_heartbeats",
        sa.Column("service_name", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rn_service_heartbeats_status", "rn_service_heartbeats", ["status"])
    op.create_index("ix_rn_service_heartbeats_last_attempt_at", "rn_service_heartbeats", ["last_attempt_at"])
    op.create_index("ix_rn_service_heartbeats_last_success_at", "rn_service_heartbeats", ["last_success_at"])


def downgrade() -> None:
    op.drop_table("rn_service_heartbeats")
