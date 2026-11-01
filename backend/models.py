import datetime
import uuid

from sqlalchemy import (
    Boolean,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SandboxTourRecord(Base):
    """One recoverable fictional example per anonymous sandbox user."""
    __tablename__ = "rn_sandbox_tours"
    user_id = Column(String, ForeignKey("rc_users.id"), primary_key=True)
    lease_token = Column(String, nullable=True)
    lease_until = Column(DateTime, nullable=True)
    manifest = Column(JSON, nullable=True)


class CatalogPublicationRecord(Base):
    """An administrator's explicit consent to share a particular catalog projection."""
    __tablename__ = "rn_catalog_publications"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), nullable=False, index=True)
    authority_claim_id = Column(String, ForeignKey("rn_authority_claims.id"), nullable=False, unique=True)
    public_payload = Column(JSON, nullable=False)
    search_text = Column(Text, nullable=False)
    basis_hash = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    approved_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=False)
    approved_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    withdrawn_at = Column(DateTime, nullable=True)


class RightsContractRecord(Base):
    __tablename__ = "rights_contracts"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_org_id = Column(String, index=True, nullable=True)
    key = Column(String, index=True, nullable=False)
    artist = Column(String, index=True, nullable=False)
    version = Column(Integer, default=1)
    source = Column(String, default="partner_override")  # mlc_live | openrouter_sim | partner_override
    editor = Column(String, nullable=True)
    batch_id = Column(String, nullable=True, index=True)
    contract_json = Column(JSON, nullable=False)
    effective_matrix = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __mapper_args__ = {
        "version_id_col": version,
        "version_id_generator": False,
    }


class RightsHistoryRecord(Base):
    __tablename__ = "rights_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_org_id = Column(String, index=True, nullable=True)
    contract_id = Column(String, index=True)
    key = Column(String, index=True)
    artist = Column(String, index=True)
    version = Column(Integer)
    editor = Column(String, nullable=True)
    batch_id = Column(String, nullable=True)
    note = Column(String, nullable=True)
    contract_json = Column(JSON, nullable=False)
    effective_matrix = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class MLCCacheRecord(Base):
    __tablename__ = "mlc_catalog_cache"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, index=True)
    payload = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class FeedbackEntry(Base):
    __tablename__ = "feedback_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(String, index=True)
    section = Column(String)
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class MagicSession(Base):
    __tablename__ = "magic_link_sessions"
    id = Column(String, primary_key=True)
    email = Column(String, index=True)
    expires_at = Column(DateTime)


class ConsumedMagicLinkRecord(Base):
    __tablename__ = "rn_consumed_magic_links"
    token_sha256 = Column(String, primary_key=True)
    email = Column(String, index=True, nullable=False)
    consumed_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)


# --- Rights Console vNext tables (non-breaking: new tables only) ---


class UserRecord(Base):
    __tablename__ = "rc_users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=True)
    role = Column(String, default="artist")  # artist | publisher | admin
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class CatalogItemRecord(Base):
    """
    Canonical catalog item (work or recording) for the Rights Console grid.
    This is separate from `RightsContractRecord` (which stores the policy contract/versioning).
    """

    __tablename__ = "rc_catalog_items"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_email = Column(String, index=True, nullable=False)  # the org/user who manages this catalog
    key = Column(String, index=True, nullable=False)  # normalized key used by the contract system
    item_type = Column(String, default="work")  # work | recording
    title = Column(String, index=True, nullable=False)
    artist = Column(String, index=True, nullable=True)
    isrc = Column(String, index=True, nullable=True)
    mlc_song_code = Column(String, index=True, nullable=True)
    mbid = Column(String, index=True, nullable=True)
    release_title = Column(String, nullable=True)
    release_date = Column(String, index=True, nullable=True)  # ISO date string
    territory = Column(String, index=True, nullable=True)  # ISO country or region code, optional
    source = Column(String, default="manual")  # manual | csv_import | cwr_import | mlc_pull | musicbrainz_pull
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ClaimRecord(Base):
    __tablename__ = "rc_claims"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_email = Column(String, index=True, nullable=False)
    key = Column(String, index=True, nullable=False)
    claimant_email = Column(String, index=True, nullable=False)
    status = Column(String, default="pending")  # pending | verified | rejected
    verification_note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)


class ApprovalRequestRecord(Base):
    __tablename__ = "rc_approval_requests"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_email = Column(String, index=True, nullable=False)
    key = Column(String, index=True, nullable=False)
    requested_by = Column(String, index=True, nullable=False)
    requested_at = Column(DateTime, default=datetime.datetime.utcnow)
    due_at = Column(DateTime, nullable=True)
    status = Column(String, default="open")  # open | approved | rejected | expired | cancelled
    decision_by = Column(String, index=True, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)
    # optional: keep a snapshot of the contract diff summary for audit friendliness
    change_summary = Column(JSON, nullable=True)


class CommentThreadRecord(Base):
    __tablename__ = "rc_comment_threads"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_email = Column(String, index=True, nullable=False)
    key = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CommentRecord(Base):
    __tablename__ = "rc_comments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, index=True, nullable=False)
    author_email = Column(String, index=True, nullable=False)
    body = Column(Text, nullable=False)
    mentions = Column(JSON, nullable=True)  # list of emails
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AuditLogRecord(Base):
    __tablename__ = "rc_audit_log"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_email = Column(String, index=True, nullable=False)
    key = Column(String, index=True, nullable=True)
    actor_email = Column(String, index=True, nullable=True)
    action = Column(String, index=True, nullable=False)  # rights.save | rights.bulk_update | import.csv | approval.request | approval.decide | comment.create
    entity_id = Column(String, index=True, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class SavedSearchRecord(Base):
    __tablename__ = "rc_saved_searches"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_email = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    query = Column(JSON, nullable=False)  # filters payload
    is_smart_folder = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ApiTokenRecord(Base):
    __tablename__ = "rc_api_tokens"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_email = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    token_sha256 = Column(String, unique=True, index=True, nullable=False)
    scopes = Column(JSON, nullable=False)  # list of scopes/permissions
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class WebhookRecord(Base):
    __tablename__ = "rc_webhooks"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_email = Column(String, index=True, nullable=False)
    url = Column(String, nullable=False)
    events = Column(JSON, nullable=False)  # list of event names
    secret = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class WebhookDeliveryRecord(Base):
    __tablename__ = "rc_webhook_deliveries"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    webhook_id = Column(String, index=True, nullable=False)
    event = Column(String, index=True, nullable=False)
    status = Column(String, default="pending")  # pending | success | failed
    status_code = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    delivered_at = Column(DateTime, nullable=True)


class OrganizationRecord(Base):
    __tablename__ = "rn_organizations"
    __table_args__ = (
        UniqueConstraint("slug"),
        Index("ix_rn_organizations_slug", "slug", unique=True),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    slug = Column(String, nullable=False)
    name = Column(String, nullable=False)
    profile = Column(JSON, nullable=False, default=dict)
    created_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class OrganizationMembershipRecord(Base):
    __tablename__ = "rn_organization_memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_rn_org_membership"),
        Index("ix_rn_memberships_org_id", "org_id"),
        Index("ix_rn_memberships_user_id", "user_id"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), nullable=False)
    user_id = Column(String, ForeignKey("rc_users.id"), nullable=False)
    role = Column(String, nullable=False, default="member")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class ApiCredentialRecord(Base):
    __tablename__ = "rn_api_credentials"
    __table_args__ = (
        UniqueConstraint("token_prefix"),
        UniqueConstraint("token_sha256"),
        Index("ix_rn_api_credentials_token_prefix", "token_prefix", unique=True),
        Index("ix_rn_api_credentials_token_sha256", "token_sha256", unique=True),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    token_prefix = Column(String, nullable=False)
    token_sha256 = Column(String, nullable=False)
    scopes = Column(JSON, nullable=False, default=list)
    created_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class WebhookEndpointRecord(Base):
    __tablename__ = "rn_webhook_endpoints"
    __table_args__ = (
        CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) "
            "OR (created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_webhook_endpoint_single_creator",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    url = Column(String, nullable=False)
    events = Column(JSON, nullable=False, default=list)
    secret_ciphertext = Column(Text, nullable=False)
    secret_hint = Column(String, nullable=False)
    enabled = Column(Boolean, index=True, nullable=False, default=True)
    created_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    created_by_api_credential_id = Column(String, ForeignKey("rn_api_credentials.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)
    disabled_at = Column(DateTime, nullable=True)


class WebhookEventRecord(Base):
    __tablename__ = "rn_webhook_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    event = Column(String, index=True, nullable=False)
    payload = Column(JSON, nullable=False)
    occurred_at = Column(DateTime, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class WebhookOutboxDeliveryRecord(Base):
    __tablename__ = "rn_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "event_id", name="uq_rn_webhook_endpoint_event"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    endpoint_id = Column(String, ForeignKey("rn_webhook_endpoints.id"), index=True, nullable=False)
    event_id = Column(String, ForeignKey("rn_webhook_events.id"), index=True, nullable=False)
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    status = Column(String, index=True, nullable=False, default="pending")
    attempt_count = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, index=True, nullable=False, default=datetime.datetime.utcnow)
    lease_until = Column(DateTime, index=True, nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    dead_lettered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)


class WebhookAttemptRecord(Base):
    __tablename__ = "rn_webhook_attempts"
    __table_args__ = (
        UniqueConstraint("delivery_id", "attempt_number", name="uq_rn_webhook_delivery_attempt"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String, ForeignKey("rn_webhook_deliveries.id"), index=True, nullable=False)
    attempt_number = Column(Integer, nullable=False)
    request_timestamp = Column(Integer, nullable=False)
    outcome = Column(String, index=True, nullable=False)
    status_code = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


class ServiceHeartbeatRecord(Base):
    """Latest non-secret operational signal from a supervised node service."""

    __tablename__ = "rn_service_heartbeats"
    service_name = Column(String, primary_key=True)
    status = Column(String, index=True, nullable=False)
    last_attempt_at = Column(DateTime, index=True, nullable=False)
    last_success_at = Column(DateTime, index=True, nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )


class AuditEventRecord(Base):
    __tablename__ = "rn_audit_events"
    __table_args__ = (
        CheckConstraint(
            "NOT (actor_user_id IS NOT NULL AND actor_api_credential_id IS NOT NULL)",
            name="ck_rn_audit_single_actor_identity",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=True)
    actor_type = Column(String, index=True, nullable=False)
    actor_user_id = Column(String, ForeignKey("rc_users.id"), index=True, nullable=True)
    actor_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        index=True,
        nullable=True,
    )
    action = Column(String, index=True, nullable=False)
    resource_type = Column(String, index=True, nullable=False)
    resource_id = Column(String, index=True, nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


@event.listens_for(AuditEventRecord, "before_update")
def _prevent_audit_event_update(*_args) -> None:
    raise RuntimeError("Rights Node audit events are append-only")


@event.listens_for(AuditEventRecord, "before_delete")
def _prevent_audit_event_delete(*_args) -> None:
    raise RuntimeError("Rights Node audit events are append-only")


class AuthorityClaimRecord(Base):
    __tablename__ = "rn_authority_claims"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    rights_contract_id = Column(String, ForeignKey("rights_contracts.id"), index=True, nullable=False)
    work_key = Column(String, index=True, nullable=False)
    right_type = Column(String, index=True, nullable=False)
    territory = Column(String, nullable=False, default="worldwide")
    status = Column(String, index=True, nullable=False, default="self_asserted")
    evidence = Column(JSON, nullable=False, default=dict)
    asserted_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=False)
    reviewed_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    verified_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class AuthorityConflictRecord(Base):
    __tablename__ = "rn_authority_conflicts"
    __table_args__ = (
        UniqueConstraint("claim_a_id", "claim_b_id", name="uq_rn_authority_conflict_pair"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    claim_a_id = Column(String, ForeignKey("rn_authority_claims.id"), index=True, nullable=False)
    claim_b_id = Column(String, ForeignKey("rn_authority_claims.id"), index=True, nullable=False)
    work_key = Column(String, index=True, nullable=False)
    right_type = Column(String, index=True, nullable=False)
    basis = Column(JSON, nullable=False, default=dict)
    status = Column(String, index=True, nullable=False, default="open")
    claim_a_prior_status = Column(String, nullable=False)
    claim_b_prior_status = Column(String, nullable=False)
    detected_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=False)
    detected_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    resolved_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution = Column(String, nullable=True)
    resolution_note = Column(Text, nullable=True)


class PermissionRequestRecord(Base):
    __tablename__ = "rn_permission_requests"
    __table_args__ = (
        CheckConstraint(
            "((requested_by_user_id IS NOT NULL AND requested_by_api_credential_id IS NULL) "
            "OR (requested_by_user_id IS NULL AND requested_by_api_credential_id IS NOT NULL))",
            name="ck_rn_permission_request_single_request_actor",
        ),
        CheckConstraint(
            "NOT (decided_by_user_id IS NOT NULL AND decided_by_api_credential_id IS NOT NULL)",
            name="ck_rn_permission_request_single_decision_actor",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    requester_org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    authority_claim_id = Column(String, ForeignKey("rn_authority_claims.id"), index=True, nullable=False)
    work_key = Column(String, index=True, nullable=False)
    intended_usage = Column(String, index=True, nullable=False)
    territory = Column(String, nullable=False, default="worldwide")
    term_start = Column(String, nullable=True)
    term_end = Column(String, nullable=True)
    context = Column(JSON, nullable=False, default=dict)
    provenance = Column(JSON, nullable=False, default=dict)
    license_obligations = Column(JSON, nullable=False, default=dict)
    status = Column(String, index=True, nullable=False, default="pending")
    requested_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    requested_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        index=True,
        nullable=True,
    )
    decided_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    decided_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        index=True,
        nullable=True,
    )
    decision_note = Column(Text, nullable=True)
    requested_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    decided_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class PermissionReviewAssignmentRecord(Base):
    __tablename__ = "rn_permission_review_assignments"
    __table_args__ = (
        CheckConstraint(
            "action IN ('assigned', 'cleared')",
            name="ck_rn_permission_review_assignment_action",
        ),
        CheckConstraint(
            "((assigned_by_user_id IS NOT NULL AND assigned_by_api_credential_id IS NULL) "
            "OR (assigned_by_user_id IS NULL AND assigned_by_api_credential_id IS NOT NULL))",
            name="ck_rn_permission_review_assignment_single_actor",
        ),
        CheckConstraint(
            "((action = 'assigned' AND reviewer_user_id IS NOT NULL) "
            "OR (action = 'cleared' AND reviewer_user_id IS NULL))",
            name="ck_rn_permission_review_assignment_reviewer",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    permission_request_id = Column(
        String,
        ForeignKey("rn_permission_requests.id"),
        index=True,
        nullable=False,
    )
    authority_org_id = Column(
        String,
        ForeignKey("rn_organizations.id"),
        index=True,
        nullable=False,
    )
    action = Column(String, index=True, nullable=False)
    reviewer_user_id = Column(String, ForeignKey("rc_users.id"), index=True, nullable=True)
    reason = Column(Text, nullable=False)
    assigned_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    assigned_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


class PermissionUsageReportRecord(Base):
    __tablename__ = "rn_permission_usage_reports"
    __table_args__ = (
        UniqueConstraint(
            "permission_request_id",
            "idempotency_key",
            name="uq_rn_permission_usage_report_idempotency",
        ),
        CheckConstraint(
            "((submitted_by_user_id IS NOT NULL AND submitted_by_api_credential_id IS NULL) "
            "OR (submitted_by_user_id IS NULL AND submitted_by_api_credential_id IS NOT NULL))",
            name="ck_rn_permission_usage_report_single_actor",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    permission_request_id = Column(
        String,
        ForeignKey("rn_permission_requests.id"),
        index=True,
        nullable=False,
    )
    requester_org_id = Column(
        String,
        ForeignKey("rn_organizations.id"),
        index=True,
        nullable=False,
    )
    publication_url = Column(String, nullable=False)
    published_at = Column(DateTime, index=True, nullable=False)
    platform = Column(String, nullable=True)
    declared_credit_text = Column(Text, nullable=True)
    declared_backlink_url = Column(String, nullable=True)
    metadata_payload = Column(JSON, nullable=False, default=dict)
    evidence = Column(JSON, nullable=False, default=dict)
    idempotency_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    submitted_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    submitted_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


class PermissionComplianceReviewRecord(Base):
    __tablename__ = "rn_permission_compliance_reviews"
    __table_args__ = (
        UniqueConstraint(
            "usage_report_id",
            "idempotency_key",
            name="uq_rn_permission_compliance_review_idempotency",
        ),
        CheckConstraint(
            "outcome IN ('compliant', 'noncompliant', 'inconclusive')",
            name="ck_rn_permission_compliance_review_outcome",
        ),
        CheckConstraint(
            "((reviewed_by_user_id IS NOT NULL AND reviewed_by_api_credential_id IS NULL) "
            "OR (reviewed_by_user_id IS NULL AND reviewed_by_api_credential_id IS NOT NULL))",
            name="ck_rn_permission_compliance_review_single_actor",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    usage_report_id = Column(
        String,
        ForeignKey("rn_permission_usage_reports.id"),
        index=True,
        nullable=False,
    )
    permission_request_id = Column(
        String,
        ForeignKey("rn_permission_requests.id"),
        index=True,
        nullable=False,
    )
    authority_org_id = Column(
        String,
        ForeignKey("rn_organizations.id"),
        index=True,
        nullable=False,
    )
    outcome = Column(String, index=True, nullable=False)
    note = Column(Text, nullable=False)
    evidence = Column(JSON, nullable=False, default=dict)
    idempotency_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    reviewed_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    reviewed_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


for _append_only_model in (
    PermissionReviewAssignmentRecord,
    PermissionUsageReportRecord,
    PermissionComplianceReviewRecord,
):
    event.listen(
        _append_only_model,
        "before_update",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("Rights Node permission administration and compliance records are append-only")
        ),
    )
    event.listen(
        _append_only_model,
        "before_delete",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("Rights Node permission administration and compliance records are append-only")
        ),
    )


class PermissionReceiptRecord(Base):
    __tablename__ = "rn_permission_receipts"
    __table_args__ = (
        UniqueConstraint("payload_hash"),
        UniqueConstraint("transparency_sequence"),
        UniqueConstraint("entry_hash"),
        Index("ix_rn_receipts_permission_request_id", "permission_request_id"),
        Index("ix_rn_receipts_receipt_kind", "receipt_kind"),
        Index("ix_rn_receipts_prior_receipt_id", "prior_receipt_id"),
        Index("ix_rn_receipts_node_id", "node_id"),
        Index("ix_rn_receipts_payload_hash", "payload_hash", unique=True),
        Index("ix_rn_receipts_key_id", "key_id"),
        Index(
            "ix_rn_receipts_transparency_sequence",
            "transparency_sequence",
            unique=True,
        ),
        Index("ix_rn_receipts_entry_hash", "entry_hash", unique=True),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    permission_request_id = Column(String, ForeignKey("rn_permission_requests.id"), nullable=False)
    receipt_kind = Column(String, nullable=False, default="grant")
    prior_receipt_id = Column(String, ForeignKey("rn_permission_receipts.id"), nullable=True)
    schema_version = Column(String, nullable=False)
    node_id = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String, nullable=False)
    signature = Column(Text, nullable=False)
    public_key = Column(Text, nullable=False)
    key_id = Column(String, nullable=False)
    transparency_sequence = Column(Integer, nullable=False)
    previous_entry_hash = Column(String, nullable=True)
    entry_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class OrganizationPrivacyRecord(Base):
    __tablename__ = "rn_organization_privacy"
    org_id = Column(String, ForeignKey("rn_organizations.id"), primary_key=True)
    publish_public_receipts = Column(Boolean, nullable=False, default=False)
    receipt_retention_days = Column(Integer, nullable=True)
    legal_hold = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)
    __table_args__ = (CheckConstraint("receipt_retention_days IS NULL OR receipt_retention_days BETWEEN 1 AND 36500", name="ck_rn_privacy_retention"),)


class ReceiptDisclosureRecord(Base):
    """A separately signed public statement and a deletable private opening."""
    __tablename__ = "rn_receipt_disclosures"
    receipt_id = Column(String, ForeignKey("rn_permission_receipts.id"), primary_key=True)
    public_id = Column(String, unique=True, nullable=False)
    authority_org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    requester_org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    commitment_nonce = Column(String, nullable=True)
    private_commitment = Column(String, nullable=False)
    public_receipt = Column(JSON, nullable=True)
    public_sequence = Column(Integer, unique=True, nullable=True)
    public_entry_hash = Column(String, unique=True, nullable=True)
    retain_until = Column(DateTime, nullable=True)
    withdrawn_at = Column(DateTime, nullable=True)
    erased_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class PrivacyErasureRequestRecord(Base):
    __tablename__ = "rn_privacy_erasure_requests"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)
    resource_id = Column(String, index=True, nullable=False)
    resource_hash = Column(String, nullable=False)
    required_org_ids = Column(JSON, nullable=False)
    approved_org_ids = Column(JSON, nullable=False, default=list)
    status = Column(String, nullable=False, default="requested")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class DdexExchangeRecord(Base):
    __tablename__ = "rn_ddex_exchanges"
    __table_args__ = (
        CheckConstraint(
            "((generated_by_user_id IS NOT NULL AND generated_by_api_credential_id IS NULL) "
            "OR (generated_by_user_id IS NULL AND generated_by_api_credential_id IS NOT NULL))",
            name="ck_rn_ddex_exchange_single_generator",
        ),
        UniqueConstraint("message_id"),
        UniqueConstraint("payload_sha256"),
        Index("ix_rn_ddex_exchanges_message_id", "message_id", unique=True),
        Index(
            "ix_rn_ddex_exchanges_payload_sha256",
            "payload_sha256",
            unique=True,
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    permission_request_id = Column(
        String, ForeignKey("rn_permission_requests.id"), index=True, nullable=False
    )
    message_id = Column(String, nullable=False)
    standard = Column(String, nullable=False, default="MWL")
    profile = Column(String, nullable=False)
    message_type = Column(String, index=True, nullable=False)
    direction = Column(String, nullable=False, default="outbound")
    payload_sha256 = Column(String, nullable=False)
    payload_xml = Column(Text, nullable=False)
    validation_status = Column(String, nullable=False, default="schema_valid")
    generated_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    generated_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        nullable=True,
    )
    generated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class DdexAcknowledgementRecord(Base):
    __tablename__ = "rn_ddex_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "exchange_id",
            "idempotency_key",
            name="uq_rn_ddex_ack_exchange_idempotency",
        ),
        CheckConstraint(
            "status IN ('received', 'processing', 'accepted', 'rejected', 'error')",
            name="ck_rn_ddex_ack_status",
        ),
        CheckConstraint(
            "acknowledgement_type IN ('transport', 'business')",
            name="ck_rn_ddex_ack_type",
        ),
        CheckConstraint(
            "((recorded_by_user_id IS NOT NULL AND recorded_by_api_credential_id IS NULL) "
            "OR (recorded_by_user_id IS NULL AND recorded_by_api_credential_id IS NOT NULL))",
            name="ck_rn_ddex_ack_single_recorder",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    exchange_id = Column(
        String,
        ForeignKey("rn_ddex_exchanges.id"),
        index=True,
        nullable=False,
    )
    acknowledgement_type = Column(String, index=True, nullable=False)
    status = Column(String, index=True, nullable=False)
    partner_message_id = Column(String, index=True, nullable=True)
    media_type = Column(String, nullable=True)
    payload_sha256 = Column(String, index=True, nullable=True)
    payload_text = Column(Text, nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    idempotency_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    recorded_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    recorded_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        nullable=True,
    )
    received_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


class SettlementRecord(Base):
    __tablename__ = "rn_settlements"
    __table_args__ = (
        UniqueConstraint("permission_request_id", name="uq_rn_settlement_permission_request"),
        CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) "
            "OR (created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_settlement_single_creator",
        ),
        CheckConstraint("minimum_commitment_minor >= 0", name="ck_rn_settlement_minimum_nonnegative"),
        CheckConstraint("royalty_rate_bps >= 0 AND royalty_rate_bps <= 10000", name="ck_rn_settlement_rate_bps"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    permission_request_id = Column(
        String,
        ForeignKey("rn_permission_requests.id"),
        index=True,
        nullable=False,
    )
    requester_org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    authority_org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    currency = Column(String, nullable=False)
    minimum_commitment_minor = Column(BigInteger, nullable=False, default=0)
    minimum_recoupable = Column(Boolean, nullable=False, default=True)
    royalty_rate_bps = Column(Integer, nullable=False, default=0)
    royalty_basis = Column(String, nullable=False, default="net_revenue")
    terms = Column(JSON, nullable=False, default=dict)
    created_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    created_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class SettlementBeneficiaryRecord(Base):
    __tablename__ = "rn_settlement_beneficiaries"
    __table_args__ = (
        UniqueConstraint("settlement_id", "identifier", name="uq_rn_settlement_beneficiary_identifier"),
        CheckConstraint("share_bps > 0 AND share_bps <= 10000", name="ck_rn_settlement_beneficiary_share"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    settlement_id = Column(String, ForeignKey("rn_settlements.id"), index=True, nullable=False)
    beneficiary_org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=True)
    name = Column(String, nullable=False)
    identifier = Column(String, nullable=False)
    share_bps = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class SettlementEntryRecord(Base):
    __tablename__ = "rn_settlement_entries"
    __table_args__ = (
        UniqueConstraint("settlement_id", "idempotency_key", name="uq_rn_settlement_entry_idempotency"),
        CheckConstraint("amount_minor > 0", name="ck_rn_settlement_entry_amount_positive"),
        CheckConstraint(
            "((recorded_by_user_id IS NOT NULL AND recorded_by_api_credential_id IS NULL) "
            "OR (recorded_by_user_id IS NULL AND recorded_by_api_credential_id IS NOT NULL))",
            name="ck_rn_settlement_entry_single_actor",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    settlement_id = Column(String, ForeignKey("rn_settlements.id"), index=True, nullable=False)
    kind = Column(String, index=True, nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    beneficiary_id = Column(
        String,
        ForeignKey("rn_settlement_beneficiaries.id"),
        index=True,
        nullable=True,
    )
    period_start = Column(String, nullable=True)
    period_end = Column(String, nullable=True)
    external_reference = Column(String, nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    calculation = Column(JSON, nullable=False, default=dict)
    idempotency_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    recorded_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    recorded_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


class SettlementReconciliationRecord(Base):
    __tablename__ = "rn_settlement_reconciliations"
    __table_args__ = (
        UniqueConstraint("settlement_id", "idempotency_key", name="uq_rn_reconciliation_idempotency"),
        UniqueConstraint("receipt_id"),
        Index("ix_rn_settlement_reconciliations_receipt_id", "receipt_id"),
        CheckConstraint(
            "((recorded_by_user_id IS NOT NULL AND recorded_by_api_credential_id IS NULL) "
            "OR (recorded_by_user_id IS NULL AND recorded_by_api_credential_id IS NOT NULL))",
            name="ck_rn_reconciliation_single_actor",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    settlement_id = Column(String, ForeignKey("rn_settlements.id"), index=True, nullable=False)
    receipt_id = Column(
        String,
        ForeignKey("rn_permission_receipts.id"),
        nullable=False,
    )
    status = Column(String, index=True, nullable=False)
    assertion_type = Column(String, nullable=False)
    entry_count = Column(Integer, nullable=False)
    ledger_digest = Column(String, index=True, nullable=False)
    totals = Column(JSON, nullable=False)
    evidence = Column(JSON, nullable=False, default=dict)
    idempotency_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    recorded_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    recorded_by_api_credential_id = Column(
        String,
        ForeignKey("rn_api_credentials.id"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


class CatalogClientRecord(Base):
    __tablename__ = "rn_catalog_clients"
    __table_args__ = (
        UniqueConstraint("org_id", "external_reference", name="uq_rn_catalog_client_reference"),
        CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) "
            "OR (created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_catalog_client_single_creator",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    external_reference = Column(String, nullable=False)
    contact_email = Column(String, nullable=True)
    created_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    created_by_api_credential_id = Column(String, ForeignKey("rn_api_credentials.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class CatalogImportBatchRecord(Base):
    __tablename__ = "rn_catalog_import_batches"
    __table_args__ = (
        UniqueConstraint("org_id", "file_sha256", name="uq_rn_catalog_import_file"),
        CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) "
            "OR (created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_catalog_import_single_creator",
        ),
        CheckConstraint(
            "NOT (committed_by_user_id IS NOT NULL AND committed_by_api_credential_id IS NOT NULL)",
            name="ck_rn_catalog_import_single_committer",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    filename = Column(String, nullable=False)
    file_sha256 = Column(String, index=True, nullable=False)
    review_digest = Column(String(64), nullable=True)
    status = Column(String, index=True, nullable=False, default="preview")
    summary = Column(JSON, nullable=False, default=dict)
    created_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    created_by_api_credential_id = Column(String, ForeignKey("rn_api_credentials.id"), nullable=True)
    committed_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    committed_by_api_credential_id = Column(String, ForeignKey("rn_api_credentials.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    committed_at = Column(DateTime, nullable=True)


class CatalogAssetRecord(Base):
    __tablename__ = "rn_catalog_assets"
    __table_args__ = (
        UniqueConstraint("org_id", "work_key", "version", name="uq_rn_catalog_asset_version"),
        CheckConstraint("version > 0", name="ck_rn_catalog_asset_version_positive"),
        CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) "
            "OR (created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_catalog_asset_single_creator",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("rn_organizations.id"), index=True, nullable=False)
    work_key = Column(String, index=True, nullable=False)
    version = Column(Integer, nullable=False)
    item_type = Column(String, index=True, nullable=False)
    title = Column(String, index=True, nullable=False)
    artist = Column(String, index=True, nullable=True)
    iswc = Column(String, index=True, nullable=True)
    isrc = Column(String, index=True, nullable=True)
    mlc_song_code = Column(String, index=True, nullable=True)
    territory = Column(String, nullable=False, default="worldwide")
    source_reference = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    import_batch_id = Column(String, ForeignKey("rn_catalog_import_batches.id"), index=True, nullable=True)
    import_row_number = Column(Integer, nullable=True)
    created_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    created_by_api_credential_id = Column(String, ForeignKey("rn_api_credentials.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class CatalogImportRowRecord(Base):
    __tablename__ = "rn_catalog_import_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_rn_catalog_import_row_number"),
        CheckConstraint(
            "NOT (resolved_by_user_id IS NOT NULL AND resolved_by_api_credential_id IS NOT NULL)",
            name="ck_rn_catalog_import_row_single_resolver",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id = Column(String, ForeignKey("rn_catalog_import_batches.id"), index=True, nullable=False)
    row_number = Column(Integer, nullable=False)
    source_json = Column(JSON, nullable=False)
    normalized_json = Column(JSON, nullable=False, default=dict)
    review_basis = Column(String(64), nullable=True)
    status = Column(String, index=True, nullable=False)
    errors = Column(JSON, nullable=False, default=list)
    existing_item_id = Column(String, ForeignKey("rn_catalog_assets.id"), index=True, nullable=True)
    resolution = Column(String, nullable=True)
    resolution_note = Column(Text, nullable=True)
    resolved_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    resolved_by_api_credential_id = Column(String, ForeignKey("rn_api_credentials.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    imported_item_id = Column(String, ForeignKey("rn_catalog_assets.id"), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class CatalogAssignmentRecord(Base):
    __tablename__ = "rn_catalog_assignments"
    __table_args__ = (
        CheckConstraint(
            "((created_by_user_id IS NOT NULL AND created_by_api_credential_id IS NULL) "
            "OR (created_by_user_id IS NULL AND created_by_api_credential_id IS NOT NULL))",
            name="ck_rn_catalog_assignment_single_creator",
        ),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    catalog_asset_id = Column(String, ForeignKey("rn_catalog_assets.id"), index=True, nullable=False)
    client_id = Column(String, ForeignKey("rn_catalog_clients.id"), index=True, nullable=True)
    reason = Column(Text, nullable=False)
    created_by_user_id = Column(String, ForeignKey("rc_users.id"), nullable=True)
    created_by_api_credential_id = Column(String, ForeignKey("rn_api_credentials.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)


def _prevent_financial_record_update(*_args) -> None:
    raise RuntimeError("Rights Node settlement ledger records are append-only")


def _prevent_financial_record_delete(*_args) -> None:
    raise RuntimeError("Rights Node settlement ledger records are append-only")


for _immutable_financial_model in (
    SettlementRecord,
    SettlementBeneficiaryRecord,
    SettlementEntryRecord,
    SettlementReconciliationRecord,
):
    event.listen(_immutable_financial_model, "before_update", _prevent_financial_record_update)
    event.listen(_immutable_financial_model, "before_delete", _prevent_financial_record_delete)


def _prevent_catalog_record_mutation(*_args) -> None:
    raise RuntimeError("Rights Node catalog assets and assignments are append-only")


for _immutable_catalog_model in (CatalogAssetRecord, CatalogAssignmentRecord):
    event.listen(_immutable_catalog_model, "before_update", _prevent_catalog_record_mutation)
    event.listen(_immutable_catalog_model, "before_delete", _prevent_catalog_record_mutation)


def _prevent_webhook_evidence_mutation(*_args) -> None:
    raise RuntimeError("Rights Node webhook events and attempts are append-only")


for _immutable_webhook_model in (WebhookEventRecord, WebhookAttemptRecord):
    event.listen(_immutable_webhook_model, "before_update", _prevent_webhook_evidence_mutation)
    event.listen(_immutable_webhook_model, "before_delete", _prevent_webhook_evidence_mutation)


def _prevent_ddex_evidence_mutation(*_args) -> None:
    raise RuntimeError("Rights Node DDEX exchanges and acknowledgements are append-only")


for _immutable_ddex_model in (DdexExchangeRecord, DdexAcknowledgementRecord):
    event.listen(_immutable_ddex_model, "before_update", _prevent_ddex_evidence_mutation)
    event.listen(_immutable_ddex_model, "before_delete", _prevent_ddex_evidence_mutation)
