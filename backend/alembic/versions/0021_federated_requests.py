"""Permission requests signed by configured peer nodes, and requests this node sends to them."""
from alembic import op
import sqlalchemy as sa

revision = "0021_federated_requests"
down_revision = "0020_catalog_review_basis"
branch_labels = None
depends_on = None

PERMISSION_TABLE = "rn_permission_requests"
TWO_ACTORS = ("((requested_by_user_id IS NOT NULL AND requested_by_api_credential_id IS NULL) "
              "OR (requested_by_user_id IS NULL AND requested_by_api_credential_id IS NOT NULL))")
THREE_ACTORS = ("((requested_by_user_id IS NOT NULL AND requested_by_api_credential_id IS NULL AND requested_by_peer_node_id IS NULL) "
                "OR (requested_by_user_id IS NULL AND requested_by_api_credential_id IS NOT NULL AND requested_by_peer_node_id IS NULL) "
                "OR (requested_by_user_id IS NULL AND requested_by_api_credential_id IS NULL AND requested_by_peer_node_id IS NOT NULL))")
# The name 0009 gave the SQLite constraint; a "ck" convention here would re-prefix every reflected CHECK.
SQLITE_NAMES = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
SQLITE_ACTOR = "rn_permission_request_single_request_actor"


def _replace_actor_constraint(expression, *, add_column):
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(PERMISSION_TABLE, recreate="always", naming_convention=SQLITE_NAMES) as batch:
            batch.drop_constraint(SQLITE_ACTOR, type_="check")
            if add_column:
                batch.add_column(sa.Column("requested_by_peer_node_id", sa.String(), nullable=True))
            else:
                batch.drop_column("requested_by_peer_node_id")
            batch.create_check_constraint(SQLITE_ACTOR, expression)
        return
    op.drop_constraint("ck_rn_permission_request_single_request_actor", PERMISSION_TABLE, type_="check")
    if add_column:
        op.add_column(PERMISSION_TABLE, sa.Column("requested_by_peer_node_id", sa.String(), nullable=True))
    else:
        op.drop_column(PERMISSION_TABLE, "requested_by_peer_node_id")
    op.create_check_constraint("ck_rn_permission_request_single_request_actor", PERMISSION_TABLE, expression)


def upgrade():
    _replace_actor_constraint(THREE_ACTORS, add_column=True)
    op.create_index("ix_rn_permission_requests_requested_by_peer_node_id", PERMISSION_TABLE, ["requested_by_peer_node_id"])
    with op.batch_alter_table("rn_organizations") as batch:
        batch.alter_column("created_by_user_id", existing_type=sa.String(), nullable=True)
    op.create_table("rn_federated_inbound_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("peer_node_id", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("statement_hash", sa.String(), nullable=False),
        sa.Column("statement", sa.JSON(), nullable=False),
        sa.Column("permission_request_id", sa.String(), sa.ForeignKey("rn_permission_requests.id"), nullable=False, unique=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("peer_node_id", "request_id", name="uq_rn_federated_inbound_peer_request"))
    op.create_table("rn_federated_outbound_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("requester_org_id", sa.String(), sa.ForeignKey("rn_organizations.id"), nullable=False),
        sa.Column("peer_id", sa.String(), nullable=False),
        sa.Column("peer_node_id", sa.String(), nullable=False),
        sa.Column("peer_origin", sa.String(), nullable=False),
        sa.Column("publication_id", sa.String(), nullable=False),
        sa.Column("request_statement", sa.JSON(), nullable=False),
        sa.Column("remote_permission_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("status_statement", sa.JSON(), nullable=True),
        sa.Column("requested_by_user_id", sa.String(), sa.ForeignKey("rc_users.id"), nullable=True),
        sa.Column("requested_by_api_credential_id", sa.String(), sa.ForeignKey("rn_api_credentials.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("NOT (requested_by_user_id IS NOT NULL AND requested_by_api_credential_id IS NOT NULL)",
                           name="ck_rn_federated_outbound_single_actor"))
    op.create_index("ix_rn_federated_outbound_requests_requester_org_id", "rn_federated_outbound_requests", ["requester_org_id"])


def downgrade():
    bind = op.get_bind()
    held = sum(bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
               for table in ("rn_federated_inbound_requests", "rn_federated_outbound_requests"))
    held += bind.execute(sa.text("SELECT COUNT(*) FROM rn_organizations WHERE created_by_user_id IS NULL")).scalar_one()
    if held:
        raise RuntimeError("Downgrade blocked: revision 0020 cannot preserve federated permission requests")
    op.drop_index("ix_rn_federated_outbound_requests_requester_org_id", table_name="rn_federated_outbound_requests")
    op.drop_table("rn_federated_outbound_requests")
    op.drop_table("rn_federated_inbound_requests")
    with op.batch_alter_table("rn_organizations") as batch:
        batch.alter_column("created_by_user_id", existing_type=sa.String(), nullable=False)
    op.drop_index("ix_rn_permission_requests_requested_by_peer_node_id", table_name=PERMISSION_TABLE)
    _replace_actor_constraint(TWO_ACTORS, add_column=False)
