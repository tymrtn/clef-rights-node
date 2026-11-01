"""Bind catalog review to the observed assets and client assignments."""
from alembic import op
import sqlalchemy as sa

revision = "0020_catalog_review_basis"
down_revision = "0019_catalog_federation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rn_catalog_import_rows", sa.Column("review_basis", sa.String(64), nullable=True))
    op.add_column("rn_catalog_import_batches", sa.Column("review_digest", sa.String(64), nullable=True))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM rn_catalog_import_rows WHERE review_basis IS NOT NULL")).scalar_one():
        raise RuntimeError("Downgrade blocked: revision 0019 cannot preserve catalog review bindings")
    op.drop_column("rn_catalog_import_batches", "review_digest")
    op.drop_column("rn_catalog_import_rows", "review_basis")
