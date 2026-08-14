"""Allow signed permission lifecycle records to extend the receipt chain."""

from alembic import op
import sqlalchemy as sa


revision = "0007_permission_lifecycle"
down_revision = "0006_org_policy_defaults"
branch_labels = None
depends_on = None


TABLE = "rn_permission_receipts"
UNIQUE_INDEX = "ix_rn_receipts_permission_request_id"


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.drop_index(UNIQUE_INDEX, table_name=TABLE)

    if dialect == "postgresql":
        op.drop_constraint(
            "rn_permission_receipts_permission_request_id_key",
            TABLE,
            type_="unique",
        )
        op.add_column(
            TABLE,
            sa.Column("receipt_kind", sa.String(), nullable=True),
        )
        op.add_column(
            TABLE,
            sa.Column("prior_receipt_id", sa.String(), nullable=True),
        )
        op.create_foreign_key(
            "fk_rn_receipts_prior_receipt_id",
            TABLE,
            TABLE,
            ["prior_receipt_id"],
            ["id"],
        )
    else:
        naming_convention = {
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        }
        with op.batch_alter_table(
            TABLE,
            recreate="always",
            naming_convention=naming_convention,
        ) as batch:
            batch.drop_constraint(
                "uq_rn_permission_receipts_permission_request_id",
                type_="unique",
            )
            batch.add_column(sa.Column("receipt_kind", sa.String(), nullable=True))
            batch.add_column(sa.Column("prior_receipt_id", sa.String(), nullable=True))
            batch.create_foreign_key(
                "fk_rn_receipts_prior_receipt_id",
                TABLE,
                ["prior_receipt_id"],
                ["id"],
            )

    op.execute(f"UPDATE {TABLE} SET receipt_kind = 'grant' WHERE receipt_kind IS NULL")
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            "receipt_kind",
            existing_type=sa.String(),
            nullable=False,
        )
    op.create_index(UNIQUE_INDEX, TABLE, ["permission_request_id"], unique=False)
    op.create_index("ix_rn_receipts_receipt_kind", TABLE, ["receipt_kind"])
    op.create_index("ix_rn_receipts_prior_receipt_id", TABLE, ["prior_receipt_id"])


def downgrade() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            "SELECT permission_request_id FROM rn_permission_receipts "
            "GROUP BY permission_request_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            "Cannot downgrade permission lifecycle receipts after lifecycle records exist"
        )

    op.drop_index("ix_rn_receipts_prior_receipt_id", table_name=TABLE)
    op.drop_index("ix_rn_receipts_receipt_kind", table_name=TABLE)
    op.drop_index(UNIQUE_INDEX, table_name=TABLE)
    with op.batch_alter_table(TABLE, recreate="always") as batch:
        batch.drop_constraint("fk_rn_receipts_prior_receipt_id", type_="foreignkey")
        batch.drop_column("prior_receipt_id")
        batch.drop_column("receipt_kind")
        batch.create_unique_constraint(
            "uq_rn_permission_receipts_permission_request_id",
            ["permission_request_id"],
        )
    op.create_index(UNIQUE_INDEX, TABLE, ["permission_request_id"], unique=True)
