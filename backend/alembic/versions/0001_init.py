"""Initial schema"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rights_contracts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False, index=True),
        sa.Column("artist", sa.String(), nullable=False, index=True),
        sa.Column("version", sa.Integer(), default=1),
        sa.Column("source", sa.String(), default="partner_override"),
        sa.Column("editor", sa.String()),
        sa.Column("batch_id", sa.String(), index=True),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("effective_matrix", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "rights_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_id", sa.String(), index=True),
        sa.Column("key", sa.String(), index=True),
        sa.Column("artist", sa.String(), index=True),
        sa.Column("version", sa.Integer()),
        sa.Column("editor", sa.String()),
        sa.Column("batch_id", sa.String()),
        sa.Column("note", sa.String()),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("effective_matrix", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "mlc_catalog_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(), index=True),
        sa.Column("payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "feedback_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_id", sa.String(), index=True),
        sa.Column("section", sa.String()),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "magic_link_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), index=True),
        sa.Column("expires_at", sa.DateTime()),
    )

    op.create_table(
        "rc_users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), unique=True, index=True, nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("role", sa.String(), default="artist"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "rc_catalog_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), index=True, nullable=False),
        sa.Column("key", sa.String(), index=True, nullable=False),
        sa.Column("item_type", sa.String(), default="work"),
        sa.Column("title", sa.String(), index=True, nullable=False),
        sa.Column("artist", sa.String(), index=True, nullable=True),
        sa.Column("isrc", sa.String(), index=True, nullable=True),
        sa.Column("mlc_song_code", sa.String(), index=True, nullable=True),
        sa.Column("mbid", sa.String(), index=True, nullable=True),
        sa.Column("release_title", sa.String(), nullable=True),
        sa.Column("release_date", sa.String(), index=True, nullable=True),
        sa.Column("territory", sa.String(), index=True, nullable=True),
        sa.Column("source", sa.String(), default="manual"),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "rc_claims",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), index=True, nullable=False),
        sa.Column("key", sa.String(), index=True, nullable=False),
        sa.Column("claimant_email", sa.String(), index=True, nullable=False),
        sa.Column("status", sa.String(), default="pending"),
        sa.Column("verification_note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "rc_approval_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), index=True, nullable=False),
        sa.Column("key", sa.String(), index=True, nullable=False),
        sa.Column("requested_by", sa.String(), index=True, nullable=False),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), default="open"),
        sa.Column("decision_by", sa.String(), index=True, nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.JSON(), nullable=True),
    )

    op.create_table(
        "rc_comment_threads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), index=True, nullable=False),
        sa.Column("key", sa.String(), index=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "rc_comments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("thread_id", sa.String(), index=True, nullable=False),
        sa.Column("author_email", sa.String(), index=True, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "rc_audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), index=True, nullable=False),
        sa.Column("key", sa.String(), index=True, nullable=True),
        sa.Column("actor_email", sa.String(), index=True, nullable=True),
        sa.Column("action", sa.String(), index=True, nullable=False),
        sa.Column("entity_id", sa.String(), index=True, nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "rc_saved_searches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), index=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("query", sa.JSON(), nullable=False),
        sa.Column("is_smart_folder", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "rc_api_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), index=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("token_sha256", sa.String(), unique=True, index=True, nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "rc_webhooks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), index=True, nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("secret", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "rc_webhook_deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("webhook_id", sa.String(), index=True, nullable=False),
        sa.Column("event", sa.String(), index=True, nullable=False),
        sa.Column("status", sa.String(), default="pending"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("rc_webhook_deliveries")
    op.drop_table("rc_webhooks")
    op.drop_table("rc_api_tokens")
    op.drop_table("rc_saved_searches")
    op.drop_table("rc_audit_log")
    op.drop_table("rc_comments")
    op.drop_table("rc_comment_threads")
    op.drop_table("rc_approval_requests")
    op.drop_table("rc_claims")
    op.drop_table("rc_catalog_items")
    op.drop_table("rc_users")
    op.drop_table("magic_link_sessions")
    op.drop_table("feedback_entries")
    op.drop_table("mlc_catalog_cache")
    op.drop_table("rights_history")
    op.drop_table("rights_contracts")
