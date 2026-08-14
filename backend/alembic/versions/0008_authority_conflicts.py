"""Record and resolve overlapping authority claims."""

from alembic import op
import sqlalchemy as sa


revision = "0008_authority_conflicts"
down_revision = "0007_permission_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rn_authority_conflicts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("claim_a_id", sa.String(), sa.ForeignKey("rn_authority_claims.id"), nullable=False),
        sa.Column("claim_b_id", sa.String(), sa.ForeignKey("rn_authority_claims.id"), nullable=False),
        sa.Column("work_key", sa.String(), nullable=False),
        sa.Column("right_type", sa.String(), nullable=False),
        sa.Column("basis", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("claim_a_prior_status", sa.String(), nullable=False),
        sa.Column("claim_b_prior_status", sa.String(), nullable=False),
        sa.Column("detected_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution", sa.String(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.UniqueConstraint("claim_a_id", "claim_b_id", name="uq_rn_authority_conflict_pair"),
    )
    op.create_index("ix_rn_authority_conflicts_claim_a_id", "rn_authority_conflicts", ["claim_a_id"])
    op.create_index("ix_rn_authority_conflicts_claim_b_id", "rn_authority_conflicts", ["claim_b_id"])
    op.create_index("ix_rn_authority_conflicts_work_key", "rn_authority_conflicts", ["work_key"])
    op.create_index("ix_rn_authority_conflicts_right_type", "rn_authority_conflicts", ["right_type"])
    op.create_index("ix_rn_authority_conflicts_status", "rn_authority_conflicts", ["status"])


def downgrade() -> None:
    op.drop_table("rn_authority_conflicts")
