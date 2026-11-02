import datetime
import uuid
from typing import Callable, Optional, List, Dict, Any
from copy import deepcopy
import csv
import io
import json
import os
import jwt
import hashlib
import secrets
import logging
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends, Header, Query, UploadFile, File, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import IntegrityError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from pythonjsonlogger import jsonlogger

from services.mlc_client import MLCClient, MLCClientError, MLCQueryError, mlc_source_scope
from services.musicbrainz_client import MusicBrainzClient
from services.mock_clients import MockMLCClient, MockMusicBrainzClient, mock_intent
from services.settings import Settings
from services.auth import MagicLinkService
from services.intent import IntentService
from services.notifications import notification_provider_from_settings, send_slack_message
from services import privacy as data_privacy
from services.receipts import (
    LIFECYCLE_SCHEMA_VERSION,
    ReceiptSigner,
    SCHEMA_VERSION,
    SETTLEMENT_SCHEMA_VERSION,
    canonical_json,
    sha256_hex,
)
from services.adapters import DDEXAdapter, MLCAdapter
from services.adapters.base import UnsupportedCapability
from services.adapters.ddex_mwl import (
    MWL_PROFILE,
    MWLExportError,
    MWLSchemaValidationError,
    MWLTerms,
    build_license_decision,
    build_license_request,
)
from services.webhooks import signed_webhook_body, webhook_signature
from services.database import database_revision_state, require_database_at_head
from services.readiness import HeartbeatSnapshot, ReadinessInputs, evaluate_node_readiness
from services.webhook_outbox import (
    SUPPORTED_WEBHOOK_EVENTS,
    WebhookSecretBox,
    enqueue_webhook_event,
    generate_webhook_secret,
    normalize_webhook_url,
)
from models import (
    RightsContractRecord,
    RightsHistoryRecord,
    CatalogItemRecord,
    AuditLogRecord,
    ClaimRecord,
    MagicSession,
    ConsumedMagicLinkRecord,
    UserRecord,
    ApprovalRequestRecord,
    CommentThreadRecord,
    CommentRecord,
    SavedSearchRecord,
    ApiTokenRecord,
    WebhookRecord,
    WebhookDeliveryRecord,
    OrganizationRecord,
    OrganizationMembershipRecord,
    ApiCredentialRecord,
    AuditEventRecord,
    AuthorityClaimRecord,
    AuthorityConflictRecord,
    PermissionRequestRecord,
    PermissionReviewAssignmentRecord,
    PermissionUsageReportRecord,
    PermissionComplianceReviewRecord,
    PermissionReceiptRecord,
    OrganizationPrivacyRecord,
    ReceiptDisclosureRecord,
    PrivacyErasureRequestRecord,
    DdexExchangeRecord,
    DdexAcknowledgementRecord,
    SettlementRecord,
    SettlementBeneficiaryRecord,
    SettlementEntryRecord,
    SettlementReconciliationRecord,
    CatalogClientRecord,
    CatalogImportBatchRecord,
    CatalogAssetRecord,
    CatalogImportRowRecord,
    CatalogAssignmentRecord,
    WebhookEndpointRecord,
    WebhookEventRecord,
    WebhookOutboxDeliveryRecord,
    WebhookAttemptRecord,
    ServiceHeartbeatRecord,
)

PROJECT_ENV_PATH = Path(os.getenv("CLEF_ENV_FILE") or Path(__file__).resolve().parents[1] / ".env")
load_dotenv(dotenv_path=PROJECT_ENV_PATH, override=False)

settings = Settings()
notification_provider = notification_provider_from_settings(settings)
webhook_secret_box = WebhookSecretBox.from_config(
    key_b64=settings.WEBHOOK_ENCRYPTION_KEY_B64,
    development_secret=settings.RIGHTS_MAGIC_LINK_SECRET,
)

def configure_logging():
    if settings.STRUCTURED_LOGGING:
        handler = logging.StreamHandler()
        formatter = jsonlogger.JsonFormatter("%(levelname)s %(name)s %(message)s")
        handler.setFormatter(formatter)
        root = logging.getLogger()
        root.handlers = [handler]
        root.setLevel(settings.LOG_LEVEL)
    else:
        logging.basicConfig(level=settings.LOG_LEVEL)


configure_logging()

def _client_address(request: Request) -> str:
    """Behind the web proxy, the edge's client header distinguishes clients; otherwise the socket peer does."""
    supplied = request.headers.get(settings.CLIENT_IP_HEADER) if settings.CLIENT_IP_HEADER else None
    return supplied.strip() if supplied and supplied.strip() else get_remote_address(request)


limiter = Limiter(key_func=_client_address, default_limits=[settings.RATE_LIMIT])

app = FastAPI(title="Clef Rights Node API", version="0.2.1")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

cors_origins = settings.CORS_ALLOW_ORIGINS or ["*"]
allow_all = any(o == "*" for o in cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def production_legacy_boundary(request: Request, call_next):
    if settings.DEMO_MODE:
        return await call_next(request)
    path = request.url.path
    allowed = (
        path == "/"
        or path == "/health"
        or path == "/openapi.json"
        or path.startswith("/docs")
        or path.startswith("/redoc")
        or path.startswith("/auth/")
        or path.startswith("/v1/")
        or path == "/.well-known/clef-node"
    )
    if not allowed:
        return JSONResponse(
            status_code=410,
            content={
                "detail": "This legacy Rights Console route is available only in explicit demo mode. Use the /v1 API.",
            },
        )
    return await call_next(request)

# --- DB bootstrap ---
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)
if settings.APP_ENV.lower() in {"staging", "production"}:
    require_database_at_head(
        engine,
        backend_root=Path(__file__).resolve().parent,
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        from sandbox_tour import fence_tour_mutation
        fence_tour_mutation(db)
        yield db
    finally:
        db.close()


# --- Services ---
intent_service = IntentService(settings.OPENROUTER_API_KEY, settings.OPENROUTER_INTENT_MODEL)
receipt_signer = ReceiptSigner(
    node_id=settings.NODE_ID,
    private_key_b64=settings.NODE_SIGNING_PRIVATE_KEY_B64,
    app_env=settings.APP_ENV,
)
_LOCAL_TRANSPARENCY_LOCK = threading.RLock()


@contextmanager
def _transparency_write_lock(db: Session):
    """Serialize transparency sequence allocation through the enclosing commit."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        lock_id = int(
            hashlib.sha256(b"clef:rn_permission_receipts:sequence").hexdigest()[:15],
            16,
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
        yield
        return
    with _LOCAL_TRANSPARENCY_LOCK:
        yield


@contextmanager
def _authority_write_lock(db: Session):
    """PostgreSQL uses claim/policy row locks; SQLite serializes the whole decision.

    Never acquire the PostgreSQL transparency lock before a claim row lock.
    Grant issuance holds its claim/policy rows before allocating a log sequence.
    """
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        yield
    else:
        with _LOCAL_TRANSPARENCY_LOCK:
            yield


mlc_adapter = MLCAdapter(
    enabled=settings.MLC_ENABLED,
    username=settings.MLC_USERNAME,
    password=settings.MLC_PASSWORD,
    base_url=settings.MLC_BASE_URL,
    authorized_capabilities=settings.MLC_AUTHORIZED_CAPABILITIES,
    connect_timeout_seconds=settings.MLC_CONNECT_TIMEOUT_SECONDS,
    read_timeout_seconds=settings.MLC_READ_TIMEOUT_SECONDS,
    max_retries=settings.MLC_MAX_RETRIES,
    max_response_bytes=settings.MLC_MAX_RESPONSE_BYTES,
)
ddex_adapter = DDEXAdapter(
    enabled=settings.DDEX_ENABLED,
    implementation_license_confirmed=settings.DDEX_IMPLEMENTATION_LICENSE_CONFIRMED,
    dpid=settings.DDEX_DPID,
    partner_dpid=settings.DDEX_PARTNER_DPID,
    sender_name=settings.DDEX_SENDER_NAME,
    partner_name=settings.DDEX_PARTNER_NAME,
    profile=settings.DDEX_PROFILE,
    mwl_xsd_path=settings.DDEX_MWL_XSD_PATH,
    authorized_capabilities=settings.DDEX_AUTHORIZED_CAPABILITIES,
)


# --- Helpers ---
from services.policy_vocabulary import (CORE_USAGE_KEYS, AI_USAGE_KEYS, USAGE_KEYS, AI_INPUT_KEYS,
    AI_MODEL_SCOPE_KEYS, AI_LIMIT_KEYS, AI_SAFEGUARD_KEYS, RESTRICTION_KEYS, default_ai_policy)

def default_usage_matrix(value: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Initialize usage matrix with tri-state values: 'blocked', 'requires_approval', 'allowed'"""
    matrix = value or {}
    out: Dict[str, str] = {}
    for key in USAGE_KEYS:
        # Default to 'blocked' if not specified
        out[key] = matrix.get(key, 'blocked')
    return out


def default_restriction_matrix(value: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Initialize restriction matrix with tri-state values: 'allowed', 'conditional', 'denied'"""
    matrix = value or {}
    out: Dict[str, str] = {}
    for key in RESTRICTION_KEYS:
        # Default to 'allowed' (no restriction) if not specified
        out[key] = matrix.get(key, 'allowed')
    return out




DEFAULT_CONTROLLED_RIGHTS_BY_ORGANIZATION_TYPE = {
    "rights_holder": ["composition"],
    "artist": ["composition", "master", "lyrics", "performance", "voice", "likeness"],
    "label": ["master"],
    "publisher": ["composition", "lyrics"],
    "administrator": ["composition", "master"],
    "pro": ["composition", "performance"],
    "cmo": ["composition", "performance"],
    "collective": ["composition", "performance"],
    "requester": [],
}


def default_organization_profile(
    *,
    organization_type: str = "rights_holder",
    default_territory: str = "worldwide",
    controlled_right_types: Optional[List[str]] = None,
    ai_policy_preset: str = "review_each_ai_use",
) -> Dict[str, Any]:
    usage = default_usage_matrix()
    ai_state = "requires_approval" if ai_policy_preset == "review_each_ai_use" else "blocked"
    for key in AI_USAGE_KEYS:
        usage[key] = ai_state
    restrictions = {key: "conditional" for key in RESTRICTION_KEYS}
    return {
        "organizationType": organization_type,
        "defaultTerritory": default_territory,
        "controlledRightTypes": (
            controlled_right_types
            if controlled_right_types is not None
            else list(DEFAULT_CONTROLLED_RIGHTS_BY_ORGANIZATION_TYPE.get(organization_type, ["composition"]))
        ),
        "aiPolicyPreset": ai_policy_preset,
        "policyDefaults": {
            "matrix": {"usage": usage, "restrictions": restrictions},
            "aiPolicy": default_ai_policy(ai_policy_preset),
        },
    }


def default_contract_template(artist: str) -> Dict[str, Any]:
    # For demo: default to "allowed" for common use cases instead of "blocked"
    usage_matrix = default_usage_matrix({
        "streaming_visual": "allowed",
        "ugc_creator": "allowed",
        "personal_noncommercial": "allowed",
        "ads_brand": "requires_approval",
        "film_tv": "requires_approval",
    })
    restriction_matrix = default_restriction_matrix()
    publisher_usage = default_usage_matrix({
        "streaming_visual": "allowed",
        "ugc_creator": "allowed",
        "personal_noncommercial": "allowed",
    })
    return {
        "policyVersion": "2.1",
        "artist": {
            "usageMatrix": usage_matrix,
            "restrictionMatrix": restriction_matrix,
            "approval": {"approvalWindowDays": 21},
        },
        "publisher": {
            "usageMatrix": publisher_usage,
            "royalties": {"splits": []},
        },
        "master": {
            "stance": "extended",
            "pricing": {
                "basePriceUsd": {},
                "licenseStanceMultiplier": 1.0,
                "audienceReachMultiplier": 1.0,
                "surcharges": {},
            },
        },
        "platform": {"guarantees": ["provenance_receipt"]},
        "matrix": {
            "usage": usage_matrix,
            "restrictions": restriction_matrix,
        },
        "metadata": {
            "archetypeId": "developing_selective",
            "simulated": True,
        },
        "artistName": artist,
    }


def compute_effective_matrix(contract: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the effective usage and restriction matrices from the contract."""
    matrix = contract.get("matrix") or {}
    usage = matrix.get("usage")
    restrictions = matrix.get("restrictions")
    if usage and restrictions:
        return {"usage": usage, "restrictions": restrictions}
    # Initialize from artist preferences or defaults
    usage_matrix = default_usage_matrix(contract.get("artist", {}).get("usageMatrix"))
    restriction_matrix = default_restriction_matrix(contract.get("artist", {}).get("restrictionMatrix"))
    matrix = {"usage": usage_matrix, "restrictions": restriction_matrix}
    contract["matrix"] = matrix
    return matrix


def clone_contract_with_matrix(payload: Dict[str, Any]) -> Dict[str, Any]:
    contract = deepcopy(payload)
    compute_effective_matrix(contract)
    return contract


def normalise_key(raw: Dict[str, Any]) -> str:
    mlc_song_code = raw.get("mlcSongCode") or raw.get("mlcsongCode")
    if mlc_song_code:
        return f"mlc:{mlc_song_code}"
    if raw.get("isrc"):
        return f"isrc:{raw['isrc']}"
    if raw.get("mbid") or raw.get("id"):
        return f"source:{raw.get('mbid') or raw.get('id')}"
    title = raw.get("title") or raw.get("workTitle")
    artist = raw.get("artist") or raw.get("performer")
    release = raw.get("release") or raw.get("releaseTitle") or raw.get("releaseDate")
    writers = raw.get("writers") or []
    publisher = raw.get("publisher") or raw.get("publishers") or []
    if title and (artist or release or writers or publisher):
        basis = json.dumps(
            {
                "entityType": raw.get("type") or ("recording" if raw.get("isrc") else "work"),
                "title": title,
                "artist": artist,
                "release": release,
                "writers": writers,
                "publisher": publisher,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return f"candidate:{hashlib.sha256(basis.encode('utf-8')).hexdigest()}"
    return f"unresolved:{uuid.uuid4()}"


def _owner_from_headers(x_owner_email: Optional[str], x_artist_name: Optional[str]) -> str:
    # NOTE: existing frontend uses X-Artist-Name as an "org lock" header.
    # vNext uses X-Owner-Email but we keep backward compatibility.
    if x_owner_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", x_owner_email.strip()):
        raise HTTPException(status_code=400, detail="X-Owner-Email must be a valid email address")
    owner = (x_owner_email or x_artist_name or "").strip()
    if not owner:
        raise HTTPException(status_code=400, detail="Owner lock required (X-Owner-Email or X-Artist-Name)")
    return owner


def _audit(
    db: Session,
    owner_email: str,
    actor_email: Optional[str],
    action: str,
    *,
    key: Optional[str] = None,
    entity_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        db.add(
            AuditLogRecord(
                owner_email=owner_email,
                key=key,
                actor_email=actor_email,
                action=action,
                entity_id=entity_id,
                details=details or {},
                created_at=datetime.datetime.utcnow(),
            )
        )
        db.commit()
    except Exception:
        # Audit must never break the primary flow.
        db.rollback()


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _emit_event(
    db: Session,
    *,
    owner_email: str,
    event: str,
    payload: Dict[str, Any],
) -> None:
    """
    Webhook dispatcher (best-effort):
    - Creates delivery logs
    - Attempts immediate delivery
    """
    hooks = (
        db.query(WebhookRecord)
        .filter(WebhookRecord.owner_email == owner_email, WebhookRecord.enabled == True)  # noqa: E712
        .all()
    )
    for h in hooks:
        events = h.events or []
        if event not in events and "*" not in events:
            continue
        delivery = WebhookDeliveryRecord(
            webhook_id=h.id,
            event=event,
            status="pending",
            payload=payload,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        try:
            occurred_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            body = signed_webhook_body(
                delivery_id=delivery.id,
                event=event,
                payload=payload,
                occurred_at=occurred_at,
            )
            headers = {"Content-Type": "application/json"}
            if h.secret:
                timestamp = int(datetime.datetime.utcnow().timestamp())
                headers["X-Clef-Timestamp"] = str(timestamp)
                headers["X-Clef-Signature"] = webhook_signature(
                    secret=h.secret,
                    timestamp=timestamp,
                    body=body,
                )
            import requests

            resp = requests.post(h.url, data=body, headers=headers, timeout=10)
            delivery.status_code = resp.status_code
            delivery.status = "success" if 200 <= resp.status_code < 300 else "failed"
            delivery.delivered_at = datetime.datetime.utcnow()
            if delivery.status == "failed":
                delivery.error = f"HTTP {resp.status_code}"
        except Exception as e:
            delivery.status = "failed"
            delivery.error = str(e)
            delivery.delivered_at = datetime.datetime.utcnow()
        db.commit()


def _upsert_catalog_item(
    db: Session,
    *,
    owner_email: str,
    key: str,
    title: str,
    item_type: str,
    artist: Optional[str] = None,
    isrc: Optional[str] = None,
    mlc_song_code: Optional[str] = None,
    mbid: Optional[str] = None,
    release_title: Optional[str] = None,
    release_date: Optional[str] = None,
    territory: Optional[str] = None,
    source: str = "manual",
    raw: Optional[Dict[str, Any]] = None,
) -> CatalogItemRecord:
    row = (
        db.query(CatalogItemRecord)
        .filter(CatalogItemRecord.owner_email == owner_email, CatalogItemRecord.key == key)
        .first()
    )
    now = datetime.datetime.utcnow()
    if not row:
        row = CatalogItemRecord(
            owner_email=owner_email,
            key=key,
            title=title,
            item_type=item_type if item_type in ("work", "recording") else "work",
            artist=artist,
            isrc=isrc,
            mlc_song_code=mlc_song_code,
            mbid=mbid,
            release_title=release_title,
            release_date=release_date,
            territory=territory,
            source=source,
            raw=raw or {},
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.title = title or row.title
        row.item_type = item_type if item_type in ("work", "recording") else row.item_type
        row.artist = artist or row.artist
        row.isrc = isrc or row.isrc
        row.mlc_song_code = mlc_song_code or row.mlc_song_code
        row.mbid = mbid or row.mbid
        row.release_title = release_title or row.release_title
        row.release_date = release_date or row.release_date
        row.territory = territory or row.territory
        row.source = source or row.source
        if raw:
            row.raw = {**(row.raw or {}), **raw}
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def load_contract(db: Session, key: str, artist: str) -> Optional[RightsContractRecord]:
    return (
        db.query(RightsContractRecord)
        .filter(RightsContractRecord.key == key, RightsContractRecord.artist == artist)
        .order_by(RightsContractRecord.version.desc())
        .first()
    )


def save_contract(db: Session, key: str, artist: str, payload: Dict[str, Any], *, expected_version: int, editor: Optional[str] = None, source: str = "partner_override", batch_id: Optional[str] = None, note: Optional[str] = None, owner_org_id: Optional[str] = None, commit: bool = True) -> RightsContractRecord:
    if owner_org_id:
        record = (
            db.query(RightsContractRecord)
            .filter(RightsContractRecord.key == key, RightsContractRecord.owner_org_id == owner_org_id)
            .order_by(RightsContractRecord.version.desc())
            .first()
        )
    else:
        record = load_contract(db, key, artist)
    if record and record.version != expected_version:
        raise HTTPException(
            status_code=409,
            detail={"message": "Rights policy changed since it was loaded", "currentVersion": record.version},
        )
    if not record and expected_version != 0:
        raise HTTPException(
            status_code=409,
            detail={"message": "Rights policy no longer matches the expected version", "currentVersion": 0},
        )
    effective_matrix = compute_effective_matrix(payload)
    if record:
        version = record.version + 1
    else:
        version = 1
        record = RightsContractRecord()
        record.key = key
        record.artist = artist
    record.version = version
    record.owner_org_id = owner_org_id
    record.editor = editor
    record.source = source
    record.batch_id = batch_id
    record.contract_json = payload
    record.effective_matrix = effective_matrix
    record.updated_at = datetime.datetime.utcnow()
    if not record.id:
        record.id = str(uuid.uuid4())
        record.created_at = datetime.datetime.utcnow()
        db.add(record)
    db.flush()

    history = RightsHistoryRecord(
        owner_org_id=owner_org_id,
        contract_id=record.id,
        key=key,
        artist=artist,
        version=version,
        editor=editor,
        batch_id=batch_id,
        note=note,
        contract_json=payload,
        effective_matrix=effective_matrix,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(history)
    if commit:
        try:
            db.commit()
        except StaleDataError as error:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"message": "Rights policy changed during this save; reload before retrying"},
            ) from error
        db.refresh(record)
    return record


# --- Auth (Magic Link: 30-minute expiry/session) ---
class InviteRequest(BaseModel):
    email: str


magic = MagicLinkService(
    secret=settings.RIGHTS_MAGIC_LINK_SECRET,
    link_exp_minutes=settings.RIGHTS_MAGIC_LINK_EXP_MINUTES,
    session_ttl_minutes=settings.RIGHTS_SESSION_TTL_MINUTES,
    notification_provider=notification_provider,
    base_url=settings.CONSOLE_BASE_URL,
)


@app.post("/auth/invite")
@limiter.limit("5/minute")
def send_invite(request: Request, req: InviteRequest):
    if not notification_provider.enabled and not settings.ALLOW_DEV_MAGIC_LINKS:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    normalized_email = req.email.strip().lower()
    if settings.AUTH_SIGNUP_MODE == "operator_only" and normalized_email not in settings.NODE_OPERATOR_EMAILS:
        # Keep the response indistinguishable from an accepted request so the
        # operator allowlist cannot be enumerated from the public login form.
        return JSONResponse(status_code=202, content={"ok": True, "sent": True})
    try:
        link = magic.create_and_send_link(normalized_email)
        response = {"ok": True, "sent": notification_provider.enabled}
        if settings.ALLOW_DEV_MAGIC_LINKS:
            response["devLink"] = link
        return JSONResponse(status_code=202, content=response)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logging.getLogger(__name__).exception("Magic-link delivery failed")
        raise HTTPException(status_code=502, detail="Magic-link delivery failed") from error


@app.get("/auth/validate")
@limiter.limit("20/minute")
def validate(request: Request, token: str, db: Session = Depends(get_db)):
    valid, email_or_err = magic.validate_token(token)
    if not valid:
        raise HTTPException(status_code=401, detail=email_or_err)
    if settings.AUTH_SIGNUP_MODE == "operator_only" and email_or_err.lower() not in settings.NODE_OPERATOR_EMAILS:
        raise HTTPException(status_code=401, detail="Sign-in is not available for this address")
    token_hash = _sha256(token)
    if (
        db.query(ConsumedMagicLinkRecord)
        .filter(ConsumedMagicLinkRecord.token_sha256 == token_hash)
        .first()
    ):
        raise HTTPException(status_code=409, detail="Magic link has already been used")
    # persist session for multi-user collaboration
    session = magic.create_session(email_or_err)
    try:
        expires_at = datetime.datetime.fromisoformat(session["expires_at"])
    except Exception:
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.RIGHTS_SESSION_TTL_MINUTES)
    db.add(
        ConsumedMagicLinkRecord(
            token_sha256=token_hash,
            email=email_or_err,
            consumed_at=datetime.datetime.utcnow(),
            expires_at=datetime.datetime.utcnow()
            + datetime.timedelta(minutes=settings.RIGHTS_MAGIC_LINK_EXP_MINUTES),
        )
    )
    db.merge(MagicSession(id=_sha256(session["id"]), email=email_or_err, expires_at=expires_at))
    # upsert user
    user = db.query(UserRecord).filter(UserRecord.email == email_or_err).first()
    if not user:
        role = "admin" if email_or_err.lower() in settings.NODE_OPERATOR_EMAILS else "artist"
        user = UserRecord(email=email_or_err, display_name=email_or_err.split("@")[0], role=role)
        db.add(user)
    elif email_or_err.lower() in settings.NODE_OPERATOR_EMAILS and user.role != "admin":
        user.role = "admin"
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Magic link has already been used") from error
    _audit(
        db,
        owner_email=email_or_err,
        actor_email=email_or_err,
        action="auth.session.created",
        details={"sessionIdHash": _sha256(session["id"])},
    )
    return {"valid": True, "session": session, "user": {"email": user.email, "role": user.role, "displayName": user.display_name}}


@app.post("/v1/sandbox/session")
@limiter.limit("10/minute")
def create_sandbox_session(request: Request, db: Session = Depends(get_db)):
    if not (
        settings.NODE_DEPLOYMENT_MODE == "public_sandbox"
        and settings.SANDBOX_GUEST_ACCESS
    ):
        raise HTTPException(status_code=404, detail="Sandbox guest access is unavailable")
    guest_id = uuid.uuid4().hex
    email = f"sandbox-{guest_id}@sandbox.invalid"
    raw_session_id = secrets.token_urlsafe(24)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(
        minutes=settings.RIGHTS_SESSION_TTL_MINUTES
    )
    user = UserRecord(
        email=email,
        display_name=f"Synthetic guest {guest_id[:8]}",
        role="admin",
    )
    db.add(user)
    db.add(
        MagicSession(
            id=_sha256(raw_session_id),
            email=email,
            expires_at=expires_at,
        )
    )
    db.commit()
    _audit(
        db,
        owner_email=email,
        actor_email=email,
        action="auth.sandbox_session.created",
        details={"sessionIdHash": _sha256(raw_session_id)},
    )
    return {
        "session": {
            "id": raw_session_id,
            "email": email,
            "expires_at": expires_at.isoformat(),
        }
    }


def _find_session(db: Session, raw_session_id: str) -> Optional[MagicSession]:
    session = db.query(MagicSession).filter(MagicSession.id == _sha256(raw_session_id)).first()
    if not session and settings.DEMO_MODE:
        session = db.query(MagicSession).filter(MagicSession.id == raw_session_id).first()
    return session


def _get_current_user(
    db: Session,
    x_session_id: Optional[str],
    x_user_email: Optional[str],
) -> Optional[UserRecord]:
    """
    Auth helper:
    - Prefer X-Session-Id (magic link session)
    - Fallback to X-User-Email for local/dev flows (explicit and auditable)
    """
    if x_session_id:
        sess = _find_session(db, x_session_id)
        if sess and sess.expires_at and sess.expires_at > datetime.datetime.utcnow():
            return db.query(UserRecord).filter(UserRecord.email == sess.email).first()
    if x_user_email and settings.ALLOW_DEV_IDENTITY_HEADERS:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", x_user_email.strip()):
            raise HTTPException(status_code=400, detail="X-User-Email must be a valid email address")
        x_user_email = x_user_email.strip()
        user = db.query(UserRecord).filter(UserRecord.email == x_user_email).first()
        if user:
            return user
        # Demo-friendly bootstrap: first user becomes admin, subsequent default to artist.
        try:
            total = db.query(UserRecord).count()
        except Exception:
            total = 0
        role = "admin" if total == 0 else "artist"
        user = UserRecord(email=x_user_email, display_name=x_user_email.split("@")[0], role=role)
        db.add(user)
        db.commit()
        return user
    return None


def _require_user(user: Optional[UserRecord]) -> UserRecord:
    if not user:
        raise HTTPException(status_code=401, detail="Auth required (X-Session-Id or X-User-Email)")
    return user


def _require_session_user(db: Session, x_session_id: Optional[str]) -> UserRecord:
    if not x_session_id:
        raise HTTPException(status_code=401, detail="X-Session-Id is required")
    sess = _find_session(db, x_session_id)
    if not sess or not sess.expires_at or sess.expires_at <= datetime.datetime.utcnow():
        raise HTTPException(status_code=401, detail="Session is missing or expired")
    user = db.query(UserRecord).filter(UserRecord.email == sess.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Session user not found")
    return user


@app.delete("/auth/session", status_code=204)
def revoke_session(
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    if not x_session_id:
        raise HTTPException(status_code=401, detail="X-Session-Id is required")
    session = _find_session(db, x_session_id)
    if session:
        db.delete(session)
        db.commit()
    return Response(status_code=204)


def _require_membership(
    db: Session,
    *,
    org_id: str,
    user_id: str,
    allowed_roles: set[str] | None = None,
) -> OrganizationMembershipRecord:
    membership = (
        db.query(OrganizationMembershipRecord)
        .filter(
            OrganizationMembershipRecord.org_id == org_id,
            OrganizationMembershipRecord.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Organization membership required")
    if allowed_roles and membership.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient organization role")
    return membership


def _require_operator(user: UserRecord) -> None:
    sandbox_operator = (
        settings.NODE_DEPLOYMENT_MODE == "public_sandbox"
        and settings.SANDBOX_GUEST_ACCESS
        and user.email.lower().endswith("@sandbox.invalid")
    )
    if user.role != "admin" or (
        user.email.lower() not in settings.NODE_OPERATOR_EMAILS and not sandbox_operator
    ):
        raise HTTPException(status_code=403, detail="Node operator authorization required")


API_TOKEN_PREFIX = "clef_rn_"
API_CREDENTIAL_SCOPES = frozenset(
    {
        "directory:read",
        "registry:read",
        "rights:read",
        "permissions:read",
        "permissions:request",
        "permissions:decide",
        "permissions:assign",
        "permissions:lifecycle",
        "compliance:report",
        "compliance:review",
        "settlements:read",
        "settlements:write",
        "settlements:reconcile",
        "catalog:read",
        "catalog:write",
        "ddex:read",
        "ddex:write",
        "webhooks:read",
        "webhooks:write",
        "audit:read",
    }
)


@dataclass(frozen=True)
class V1Principal:
    user: Optional[UserRecord] = None
    credential: Optional[ApiCredentialRecord] = None

    @property
    def org_id(self) -> Optional[str]:
        return self.credential.org_id if self.credential else None


def _require_v1_principal(
    db: Session,
    *,
    x_session_id: Optional[str],
    authorization: Optional[str],
    required_scope: Optional[str] = None,
) -> V1Principal:
    if x_session_id and authorization:
        raise HTTPException(status_code=400, detail="Use either a session or a bearer credential, not both")
    if x_session_id:
        return V1Principal(user=_require_session_user(db, x_session_id))
    if not authorization:
        raise HTTPException(status_code=401, detail="A session or bearer API credential is required")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="A valid bearer API credential is required")
    token = token.strip()
    credential = (
        db.query(ApiCredentialRecord)
        .filter(ApiCredentialRecord.token_sha256 == _sha256(token))
        .first()
    )
    now = datetime.datetime.utcnow()
    if (
        not credential
        or credential.revoked_at is not None
        or credential.expires_at is None
        or credential.expires_at <= now
    ):
        raise HTTPException(status_code=401, detail="API credential is invalid, expired, or revoked")
    if required_scope and required_scope not in set(credential.scopes or []):
        raise HTTPException(status_code=403, detail=f"API credential requires scope {required_scope}")
    credential.last_used_at = now
    db.commit()
    db.refresh(credential)
    return V1Principal(credential=credential)


def _require_principal_organization(
    db: Session,
    *,
    principal: V1Principal,
    org_id: str,
    required_scope: Optional[str] = None,
    allowed_roles: Optional[set[str]] = None,
) -> Optional[OrganizationMembershipRecord]:
    if principal.user:
        return _require_membership(
            db,
            org_id=org_id,
            user_id=principal.user.id,
            allowed_roles=allowed_roles,
        )
    credential = principal.credential
    if not credential or credential.org_id != org_id:
        raise HTTPException(status_code=403, detail="API credential is scoped to another organization")
    if required_scope and required_scope not in set(credential.scopes or []):
        raise HTTPException(status_code=403, detail=f"API credential requires scope {required_scope}")
    return None


def _principal_actor(
    principal: V1Principal,
    *,
    organization_id: Optional[str] = None,
    organization_role: Optional[str] = None,
) -> Dict[str, Any]:
    if principal.credential:
        return {
            "type": "api_credential",
            "credentialId": principal.credential.id,
            "credentialName": principal.credential.name,
            "organizationId": principal.credential.org_id,
        }
    if not principal.user:
        raise RuntimeError("Authenticated principal has no actor identity")
    actor: Dict[str, Any] = {
        "type": "organization_member",
        "userId": principal.user.id,
    }
    if organization_id:
        actor["organizationId"] = organization_id
    if organization_role:
        actor["organizationRole"] = organization_role
    return actor


def _record_v1_audit(
    db: Session,
    *,
    org_id: Optional[str],
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    details: Optional[Dict[str, Any]] = None,
    principal: Optional[V1Principal] = None,
    actor_type: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    actor_api_credential_id: Optional[str] = None,
) -> AuditEventRecord:
    if principal:
        if principal.credential:
            actor_type = actor_type or "api_credential"
            actor_api_credential_id = principal.credential.id
        elif principal.user:
            actor_type = actor_type or "organization_member"
            actor_user_id = principal.user.id
    row = AuditEventRecord(
        org_id=org_id,
        actor_type=actor_type or "system",
        actor_user_id=actor_user_id,
        actor_api_credential_id=actor_api_credential_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        created_at=datetime.datetime.utcnow(),
    )
    db.add(row)
    if org_id:
        enqueue_webhook_event(
            db,
            org_id=org_id,
            event=action,
            payload={
                "schemaVersion": "clef.webhook-event.v1",
                "organizationId": org_id,
                "action": action,
                "resource": {"type": resource_type, "id": resource_id},
                "actor": {
                    "type": row.actor_type,
                    "userId": row.actor_user_id,
                    "credentialId": row.actor_api_credential_id,
                },
                "details": details or {},
            },
            occurred_at=row.created_at,
        )
    return row


class UserUpdateRoleRequest(BaseModel):
    email: str
    role: str  # artist | publisher | admin
    display_name: Optional[str] = None


@app.get("/users/me")
def users_me(
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    user = _get_current_user(db, x_session_id, x_user_email)
    if not user:
        return {"ok": False, "user": None}
    return {"ok": True, "user": {"email": user.email, "role": user.role, "displayName": user.display_name}}


@app.post("/users/set-role")
def users_set_role(
    req: UserUpdateRoleRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    actor = _require_user(_get_current_user(db, x_session_id, x_user_email))
    # Minimal enforcement: only admins can change roles.
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required to change roles")
    role = req.role.strip().lower()
    if role not in ("artist", "publisher", "admin"):
        raise HTTPException(status_code=400, detail="role must be artist|publisher|admin")
    user = db.query(UserRecord).filter(UserRecord.email == req.email).first()
    if not user:
        user = UserRecord(email=req.email, display_name=req.display_name, role=role)
        db.add(user)
    else:
        user.role = role
        if req.display_name is not None:
            user.display_name = req.display_name
    db.commit()
    _audit(db, owner_email=actor.email, actor_email=actor.email, action="user.set_role", details={"target": req.email, "role": role})
    return {"ok": True, "user": {"email": user.email, "role": user.role, "displayName": user.display_name}}


@app.get("/audit/list")
def audit_list(
    key: Optional[str] = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    query = db.query(AuditLogRecord).filter(AuditLogRecord.owner_email == owner)
    if key:
        query = query.filter(AuditLogRecord.key == key)
    rows = query.order_by(AuditLogRecord.created_at.desc()).limit(limit).all()
    return {
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "key": r.key,
                "actor": r.actor_email,
                "createdAt": r.created_at,
                "details": r.details or {},
            }
            for r in rows
        ]
    }


# --- API tokens ---


class TokenCreateRequest(BaseModel):
    name: str
    scopes: List[str] = []


@app.post("/tokens/create")
def tokens_create(
    req: TokenCreateRequest,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _require_user(_get_current_user(db, x_session_id, x_user_email))
    if user.role not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="publisher/admin required")
    token = secrets.token_urlsafe(32)
    token_hash = _sha256(token)
    row = ApiTokenRecord(owner_email=owner, name=req.name, token_sha256=token_hash, scopes=req.scopes or [])
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(db, owner_email=owner, actor_email=user.email, action="token.create", details={"name": req.name, "scopes": req.scopes})
    return {"ok": True, "token": token, "tokenId": row.id}


@app.get("/tokens/list")
def tokens_list(
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    rows = db.query(ApiTokenRecord).filter(ApiTokenRecord.owner_email == owner).order_by(ApiTokenRecord.created_at.desc()).all()
    return {
        "items": [
            {"id": r.id, "name": r.name, "scopes": r.scopes, "createdAt": r.created_at, "revokedAt": r.revoked_at}
            for r in rows
        ]
    }


@app.post("/tokens/revoke")
def tokens_revoke(
    token_id: str,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _require_user(_get_current_user(db, x_session_id, x_user_email))
    if user.role not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="publisher/admin required")
    row = db.query(ApiTokenRecord).filter(ApiTokenRecord.owner_email == owner, ApiTokenRecord.id == token_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Token not found")
    row.revoked_at = datetime.datetime.utcnow()
    db.commit()
    _audit(db, owner_email=owner, actor_email=user.email, action="token.revoke", details={"tokenId": token_id})
    return {"ok": True}


# --- Webhooks ---


class WebhookCreateRequest(BaseModel):
    url: str
    events: List[str]
    secret: Optional[str] = None


@app.post("/webhooks/create")
def webhooks_create(
    req: WebhookCreateRequest,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _require_user(_get_current_user(db, x_session_id, x_user_email))
    if user.role not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="publisher/admin required")
    row = WebhookRecord(owner_email=owner, url=req.url, events=req.events, secret=req.secret, enabled=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(db, owner_email=owner, actor_email=user.email, action="webhook.create", details={"url": req.url, "events": req.events})
    return {"ok": True, "id": row.id}


@app.get("/webhooks/list")
def webhooks_list(
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    rows = db.query(WebhookRecord).filter(WebhookRecord.owner_email == owner).order_by(WebhookRecord.updated_at.desc()).all()
    return {"items": [{"id": r.id, "url": r.url, "events": r.events, "enabled": r.enabled, "updatedAt": r.updated_at} for r in rows]}


@app.post("/webhooks/delete")
def webhooks_delete(
    webhook_id: str,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _require_user(_get_current_user(db, x_session_id, x_user_email))
    if user.role not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="publisher/admin required")
    row = db.query(WebhookRecord).filter(WebhookRecord.owner_email == owner, WebhookRecord.id == webhook_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    db.delete(row)
    db.commit()
    _audit(db, owner_email=owner, actor_email=user.email, action="webhook.delete", details={"id": webhook_id})
    return {"ok": True}


@app.get("/webhooks/deliveries")
def webhooks_deliveries(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    # join-ish: filter deliveries by webhooks owned by owner
    hook_ids = [h.id for h in db.query(WebhookRecord).filter(WebhookRecord.owner_email == owner).all()]
    if not hook_ids:
        return {"items": []}
    rows = (
        db.query(WebhookDeliveryRecord)
        .filter(WebhookDeliveryRecord.webhook_id.in_(hook_ids))
        .order_by(WebhookDeliveryRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "webhookId": r.webhook_id,
                "event": r.event,
                "status": r.status,
                "statusCode": r.status_code,
                "error": r.error,
                "createdAt": r.created_at,
                "deliveredAt": r.delivered_at,
            }
            for r in rows
        ]
    }


# --- Embed widget ---


@app.get("/embed/badge.js")
def embed_badge_js(
    owner: str = Query(...),
    key: str = Query(...),
    intended_usage: str = Query(default="streaming_visual"),
):
    """
    Tiny partner-embeddable badge script.
    Usage:
      <script src=\"/embed/badge.js?owner=...&key=...\" async></script>
      <div class=\"clef-rights-badge\"></div>
    """
    # We intentionally keep this minimal; partners can host this script themselves if desired.
    script = f"""
(function() {{
  function render(el, text, cls, href) {{
    el.innerHTML = '';
    var a = document.createElement('a');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.style.textDecoration = 'none';
    var span = document.createElement('span');
    span.textContent = text;
    span.style.fontFamily = 'ui-sans-serif, system-ui, -apple-system';
    span.style.fontSize = '12px';
    span.style.padding = '6px 10px';
    span.style.borderRadius = '999px';
    span.style.display = 'inline-block';
    span.style.border = '1px solid rgba(0,0,0,0.08)';
    span.style.background = cls.bg;
    span.style.color = cls.fg;
    a.appendChild(span);
    el.appendChild(a);
  }}
  function clsFor(status) {{
    if (status === 'allowed') return {{ bg: '#DCFCE7', fg: '#166534' }};
    if (status === 'requires_approval') return {{ bg: '#FEF9C3', fg: '#854D0E' }};
    return {{ bg: '#FEE2E2', fg: '#991B1B' }};
  }}
  var els = document.querySelectorAll('.clef-rights-badge');
  if (!els.length) return;
  fetch('/rights/summary?key=' + encodeURIComponent('{key}') + '&intended_usage=' + encodeURIComponent('{intended_usage}'), {{
    headers: {{ 'X-Artist-Name': '{owner}' }}
  }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
    els.forEach(function(el) {{
      var status = data.headlineStatus || 'blocked';
      var label = status === 'requires_approval' ? 'Approval required' : (status === 'allowed' ? 'Allowed' : 'Blocked');
      render(el, 'Clef Rights: ' + label, clsFor(status), data.deepLinkUrl || '#');
    }});
  }}).catch(function() {{
    els.forEach(function(el) {{
      render(el, 'Clef Rights: unavailable', {{ bg: '#F3F4F6', fg: '#374151' }}, '#');
    }});
  }});
}})();
"""
    return Response(content=script, media_type="application/javascript")


# --- MLC helpers ---


def get_mlc() -> Optional[MLCClient]:
    if settings.MOCK_INTEGRATIONS:
        return MockMLCClient()
    try:
        return mlc_adapter.require("catalog_lookup")
    except UnsupportedCapability:
        return None


def get_musicbrainz() -> Optional[MusicBrainzClient]:
    if settings.MUSICBRAINZ_ENABLED or settings.MOCK_INTEGRATIONS:
        client_id = settings.MUSICBRAINZ_CLIENT_ID or ""
        client_secret = settings.MUSICBRAINZ_CLIENT_SECRET or ""
        if settings.MOCK_INTEGRATIONS and not settings.MUSICBRAINZ_ENABLED:
            return MockMusicBrainzClient()
        return MusicBrainzClient(
            client_id,
            client_secret,
            base_url=settings.MUSICBRAINZ_BASE_URL
        )
    return None


@app.get("/integrations/status")
def integrations_status():
    """
    Simple transparency endpoint for UI badges: live / degraded / mock.
    - live: enabled + credentials (where applicable)
    - degraded: enabled but credentials missing or last call failing
    - mock: explicitly disabled
    """
    mlc = "live" if (settings.MLC_ENABLED and settings.MLC_USERNAME and settings.MLC_PASSWORD) else ("mock" if not settings.MLC_ENABLED else "degraded")
    musicbrainz = "live" if settings.MUSICBRAINZ_ENABLED else "mock"
    openrouter = "live" if settings.OPENROUTER_API_KEY else "degraded"
    return {
        "mlc": {"status": mlc, "enabled": settings.MLC_ENABLED},
        "musicbrainz": {"status": musicbrainz, "enabled": settings.MUSICBRAINZ_ENABLED},
        "openrouter_intent": {"status": openrouter, "enabled": bool(settings.OPENROUTER_API_KEY)},
    }


class CatalogPullRequest(BaseModel):
    artist: Optional[str] = None
    title: Optional[str] = None
    limit: Optional[int] = 25


@app.post("/catalog/pull/musicbrainz")
def catalog_pull_musicbrainz(
    req: CatalogPullRequest,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    client = get_musicbrainz()
    if not client:
        return {"ok": False, "musicbrainz_enabled": False, "note": "MusicBrainz integration is disabled"}
    results = client.search_recordings(artist=req.artist, title=req.title, isrc=None, limit=req.limit or 25)
    created = 0
    duplicates = 0
    for rec in results or []:
        title = rec.get("title") or "Untitled"
        mbid = rec.get("id")
        # artist name best-effort
        artist_name = None
        if "artist-credit" in rec and rec["artist-credit"]:
            try:
                artist_name = rec["artist-credit"][0].get("name")
            except Exception:
                artist_name = None
        key = mbid or title
        existing = (
            db.query(CatalogItemRecord)
            .filter(CatalogItemRecord.owner_email == owner, CatalogItemRecord.key == key)
            .first()
        )
        if existing:
            duplicates += 1
            continue
        _upsert_catalog_item(
            db,
            owner_email=owner,
            key=key,
            title=title,
            item_type="recording",
            artist=artist_name or req.artist,
            mbid=mbid,
            source="musicbrainz_pull",
            raw={"musicbrainz": rec},
        )
        created += 1
    _audit(db, owner_email=owner, actor_email=owner, action="catalog.pull.musicbrainz", details={"created": created, "duplicates": duplicates})
    return {"ok": True, "created": created, "duplicates": duplicates, "count": len(results or []), "musicbrainz_enabled": True}


@app.post("/catalog/pull/mlc")
def catalog_pull_mlc(
    req: CatalogPullRequest,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    client = get_mlc()
    if not client:
        return {"ok": False, "mlc_enabled": False, "note": "MLC integration is disabled or missing credentials"}
    if not req.artist:
        raise HTTPException(status_code=400, detail="artist required for MLC pull")
    # Prefer recordings search when title provided; otherwise pull is best-effort and may be limited by MLC API constraints.
    results = client.search_recordings(artist=req.artist, title=req.title if req.title else None, isrc=None)
    created = 0
    duplicates = 0
    for item in (results or [])[: (req.limit or 25)]:
        title = item.get("title") or "Untitled"
        isrc = item.get("isrc")
        mlc_sc = item.get("mlcSongCode") or item.get("mlcsongCode")
        key = mlc_sc or isrc or title
        existing = (
            db.query(CatalogItemRecord)
            .filter(CatalogItemRecord.owner_email == owner, CatalogItemRecord.key == key)
            .first()
        )
        if existing:
            duplicates += 1
            continue
        _upsert_catalog_item(
            db,
            owner_email=owner,
            key=key,
            title=title,
            item_type="recording",
            artist=item.get("artist") or req.artist,
            isrc=isrc,
            mlc_song_code=mlc_sc,
            source="mlc_pull",
            raw={"mlc": item},
        )
        created += 1
    _audit(db, owner_email=owner, actor_email=owner, action="catalog.pull.mlc", details={"created": created, "duplicates": duplicates})
    return {"ok": True, "created": created, "duplicates": duplicates, "mlc_enabled": True}


class IntentRequest(BaseModel):
    intent: str
    filters: Optional[Dict[str, Any]] = None


@app.post("/mlc/query-intent")
def mlc_query_intent(req: IntentRequest, x_artist_name: Optional[str] = Header(default=None)):
    artist = x_artist_name or req.filters.get("artist") if req.filters else None
    if not artist:
        raise HTTPException(status_code=400, detail="Artist lock required")
    result = intent_service.parse_intent(artist, req.intent, req.filters)
    if result.get("fallback") and settings.MOCK_INTEGRATIONS:
        result = mock_intent(artist, req.intent, req.filters or {})
    return result


class RecordingQuery(BaseModel):
    artist: Optional[str] = None
    title: Optional[str] = None
    isrc: Optional[str] = None


@app.post("/mlc/search/recordings")
def mlc_search_recordings(q: RecordingQuery, x_artist_name: Optional[str] = Header(default=None)):
    client = get_mlc()
    if not client:
        return {"results": [], "mlc_enabled": False}
    try:
        is_mock = isinstance(client, MockMLCClient)
        artist = q.artist or x_artist_name
        if not artist:
            # recordings endpoint requires at least artist
            return {"results": [], "mlc_enabled": True, "note": "Recordings search skipped (artist required)"}
        # Title is optional - allow artist-only searches to return all recordings for that artist
        # Note: The MLC API may require both artist and title - if artist-only returns empty, try with empty title string
        results = client.search_recordings(artist=artist, title=q.title if q.title else None, isrc=q.isrc)
        
        # If artist-only search returned empty, the API likely requires both fields
        if not results and artist and not q.title and not q.isrc:
            return {
                "results": [], 
                "mlc_enabled": True, 
                "note": "The MLC API requires both artist and title for recordings search. Please add a song title to your search."
            }
        
        return {"results": results, "mlc_enabled": True, "mock": is_mock}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MLC recordings search failed: {str(e)}")


class MusicBrainzQuery(BaseModel):
    artist: Optional[str] = None
    title: Optional[str] = None
    isrc: Optional[str] = None
    limit: Optional[int] = 100


@app.post("/musicbrainz/search")
def musicbrainz_search(q: MusicBrainzQuery, x_artist_name: Optional[str] = Header(default=None)):
    """Search MusicBrainz for recordings by artist, title, or ISRC."""
    client = get_musicbrainz()
    if not client:
        return {"results": [], "musicbrainz_enabled": False}
    try:
        is_mock = isinstance(client, MockMusicBrainzClient)
        artist = q.artist or x_artist_name
        if not artist and not q.title and not q.isrc:
            return {
                "results": [],
                "musicbrainz_enabled": True,
                "note": "Please provide at least artist, title, or ISRC"
            }
        
        results = client.search_recordings(
            artist=artist,
            title=q.title,
            isrc=q.isrc,
            limit=q.limit or 100
        )
        
        # Normalize MusicBrainz results to match our frontend expectations
        normalized_results = []
        for rec in results:
            # Extract artist name from artist-credit
            artist_name = None
            if "artist-credit" in rec and rec["artist-credit"]:
                if isinstance(rec["artist-credit"], list) and len(rec["artist-credit"]) > 0:
                    artist_name = rec["artist-credit"][0].get("name", "")
                elif isinstance(rec["artist-credit"], dict):
                    artist_name = rec["artist-credit"].get("name", "")
            
            # Extract release info
            release_title = None
            release_date = None
            if "releases" in rec and rec["releases"]:
                first_release = rec["releases"][0]
                release_title = first_release.get("title")
                release_date = first_release.get("date")
            
            # Extract ISRCs
            isrcs = []
            if "isrc-list" in rec:
                isrcs = [isrc.get("isrc") for isrc in rec["isrc-list"] if isrc.get("isrc")]
            
            normalized_results.append({
                "mbid": rec.get("id"),  # MusicBrainz ID
                "title": rec.get("title"),
                "artist": artist_name or artist,
                "release": release_title,
                "releaseDate": release_date,
                "isrc": isrcs[0] if isrcs else None,
                "isrcs": isrcs,
                "length": rec.get("length"),  # Duration in milliseconds
                "disambiguation": rec.get("disambiguation"),  # Additional info to distinguish duplicates
                "raw": rec,  # Full MusicBrainz response for reference
            })
        
        return {
            "results": normalized_results,
            "musicbrainz_enabled": True,
            "count": len(normalized_results),
            "mock": is_mock,
        }
    except Exception as e:
        print(f"MusicBrainz search error: {str(e)}")
        return {
            "results": [],
            "musicbrainz_enabled": True,
            "error": str(e),
            "note": "MusicBrainz search failed. Please try again or refine your search."
        }


class SongcodeQuery(BaseModel):
    title: Optional[str] = None
    writer_lastname: Optional[str] = None
    publisher: Optional[str] = None
    years: Optional[List[int]] = None


@app.post("/mlc/search/songcode")
def mlc_search_songcode(q: SongcodeQuery, x_artist_name: Optional[str] = Header(default=None)):
    client = get_mlc()
    if not client:
        return {"results": [], "mlc_enabled": False}
    try:
        is_mock = isinstance(client, MockMLCClient)
        results = client.search_songcode(title=q.title, writer_lastname=q.writer_lastname)
        if q.publisher:
            pub_lower = q.publisher.lower()
            filtered = []
            for r in results:
                publishers = r.get("publishers") or []
                if any(pub_lower in str(p.get("publisherName", "")).lower() for p in publishers):
                    filtered.append(r)
            results = filtered
        if x_artist_name:
            last = x_artist_name.split(" ")[-1].lower()
            filtered = []
            for r in results:
                writers = r.get("writers") or []
                if any(str(w.get("writerLastName", "")).lower() == last for w in writers):
                    filtered.append(r)
            results = filtered or results
        return {"results": results, "mlc_enabled": True, "mock": is_mock}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MLC songcode search failed: {str(e)}")


# --- Rights endpoints ---


class RightsSavePayload(BaseModel):
    key: str
    artist: str
    contract: Dict[str, Any]
    note: Optional[str] = None
    expected_version: int


def _require_durable_rights_key(key: str) -> None:
    if key.startswith(("candidate:", "unresolved:")):
        raise HTTPException(
            status_code=422,
            detail="Import the catalog result and assign a durable identifier before editing rights",
        )


@app.post("/rights/save")
def save_rights(
    payload: RightsSavePayload,
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
    x_owner_email: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    _require_durable_rights_key(payload.key)
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _get_current_user(db, x_session_id, x_user_email)
    actor = user.email if user else owner
    artist = owner or payload.artist
    if not artist:
        raise HTTPException(status_code=400, detail="Artist is required")
    record = save_contract(
        db,
        payload.key,
        artist,
        payload.contract,
        editor=actor,
        note=payload.note,
        expected_version=payload.expected_version,
    )
    # best-effort: keep catalog item updated for faceting/search
    try:
        title = payload.contract.get("title") or payload.contract.get("workTitle") or payload.contract.get("artistName") or payload.key
        _upsert_catalog_item(
            db,
            owner_email=artist,
            key=payload.key,
            title=str(title),
            item_type="work",
            artist=artist,
            source="manual",
            raw={"lastSavedContractVersion": record.version},
        )
    except Exception:
        db.rollback()
    _audit(db, owner_email=artist, actor_email=actor, action="rights.save", key=payload.key, entity_id=record.id, details={"version": record.version})
    _emit_event(
        db,
        owner_email=artist,
        event="rights.updated",
        payload={"key": payload.key, "version": record.version, "editor": actor, "updatedAt": record.updated_at.isoformat() if record.updated_at else None},
    )
    return {
        "id": record.id,
        "version": record.version,
        "updated_at": record.updated_at,
        "contract": record.contract_json,
        "matrix": record.effective_matrix,
    }


@app.get("/rights/by-key")
def rights_by_key(
    key: str = Query(...),
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
    x_owner_email: Optional[str] = Header(default=None),
):
    artist = _owner_from_headers(x_owner_email, x_artist_name)
    if not artist:
        raise HTTPException(status_code=400, detail="Owner/artist lock required")
    record = load_contract(db, key, artist)
    if record:
        return {
            "id": record.id,
            "version": record.version,
            "contract": record.contract_json,
            "matrix": record.effective_matrix,
            "updated_at": record.updated_at,
            "isNew": False,
        }
    template = default_contract_template(artist)
    return {
        "id": None,
        "version": 0,
        "contract": template,
        "matrix": template["matrix"],
        "updated_at": None,
        "isNew": True,
    }


@app.get("/rights/history")
def rights_history(
    key: str = Query(...),
    limit: int = Query(10),
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
    x_owner_email: Optional[str] = Header(default=None),
):
    artist = _owner_from_headers(x_owner_email, x_artist_name)
    if not artist:
        raise HTTPException(status_code=400, detail="Owner/artist lock required")
    rows = (
        db.query(RightsHistoryRecord)
        .filter(RightsHistoryRecord.key == key, RightsHistoryRecord.artist == artist)
        .order_by(RightsHistoryRecord.version.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "version": row.version,
            "editor": row.editor,
            "batchId": row.batch_id,
            "note": row.note,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@app.get("/rights/history/version")
def rights_history_version(
    key: str = Query(...),
    version: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
    x_owner_email: Optional[str] = Header(default=None),
):
    artist = _owner_from_headers(x_owner_email, x_artist_name)
    if not artist:
        raise HTTPException(status_code=400, detail="Owner/artist lock required")
    row = (
        db.query(RightsHistoryRecord)
        .filter(RightsHistoryRecord.key == key, RightsHistoryRecord.artist == artist, RightsHistoryRecord.version == version)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"version": row.version, "editor": row.editor, "note": row.note, "created_at": row.created_at, "contract": row.contract_json, "matrix": row.effective_matrix}


class BulkChangePayload(BaseModel):
    keys: List[str]
    changes: Dict[str, Any]
    note: Optional[str] = None


@app.post("/rights/bulk-update")
def rights_bulk_update(
    payload: BulkChangePayload,
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
    x_owner_email: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _get_current_user(db, x_session_id, x_user_email)
    actor = user.email if user else owner
    if not payload.keys:
        raise HTTPException(status_code=400, detail="No keys supplied")
    for key in payload.keys:
        _require_durable_rights_key(key)
    batch_id = str(uuid.uuid4())
    updated = []
    for key in payload.keys:
        record = load_contract(db, key, owner)
        contract = record.contract_json if record else default_contract_template(owner)
        apply_changes(contract, payload.changes)
        saved = save_contract(
            db,
            key,
            owner,
            contract,
            expected_version=record.version if record else 0,
            editor=actor,
            batch_id=batch_id,
            note=payload.note,
        )
        updated.append({
            "key": key,
            "contract": saved.contract_json,
            "matrix": saved.effective_matrix,
            "version": saved.version,
        })
    _audit(
        db,
        owner_email=owner,
        actor_email=actor,
        action="rights.bulk_update",
        details={"batchId": batch_id, "count": len(updated), "note": payload.note},
    )
    return {"batchId": batch_id, "items": updated}


@app.get("/rights/list")
def rights_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
    x_owner_email: Optional[str] = Header(default=None),
):
    artist = _owner_from_headers(x_owner_email, x_artist_name)
    if not artist:
        raise HTTPException(status_code=400, detail="Owner/artist lock required")
    query = (
        db.query(RightsContractRecord)
        .filter(RightsContractRecord.artist == artist)
        .order_by(RightsContractRecord.updated_at.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "items": [
            {
                "key": row.key,
                "version": row.version,
                "updated_at": row.updated_at,
                "matrix": row.effective_matrix,
                "contract": row.contract_json,
            }
            for row in rows
        ],
    }


# --- Catalog (grid backing store) ---


class CatalogSeedResponse(BaseModel):
    ok: bool
    created: int = 0
    removed: int = 0
    duplicates: int = 0


@app.post("/catalog/seed-sample")
def catalog_seed_sample(
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    """
    One-click: populate a sample catalog so the grid isn't empty.
    Safe for core: explicitly invoked and revertible via /catalog/reset-sample.

    Every bundled record is fictional. Public and explicit demo deployments must
    not seed real artists, works, identifiers, organizations, or authority claims.
    """
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    sample = [
        {"key": "SYNTH-REC-0001", "title": "Northern Signal", "item_type": "recording", "artist": "Northlight Assembly", "isrc": None},
        {"key": "SYNTH-WORK-0001", "title": "Northern Signal", "item_type": "work", "artist": "Avery North", "mlc_song_code": None},
        {"key": "SYNTH-REC-0002", "title": "Glass Orchard", "item_type": "recording", "artist": "Juniper Static", "isrc": None},
        {"key": "SYNTH-WORK-0002", "title": "Glass Orchard", "item_type": "work", "artist": "Mara Vale", "mlc_song_code": None},
    ]
    created = 0
    duplicates = 0
    for item in sample:
        existing = (
            db.query(CatalogItemRecord)
            .filter(CatalogItemRecord.owner_email == owner, CatalogItemRecord.key == item["key"])
            .first()
        )
        if existing:
            duplicates += 1
            continue
        _upsert_catalog_item(
            db,
            owner_email=owner,
            key=item["key"],
            title=item["title"],
            item_type=item["item_type"],
            artist=item.get("artist"),
            isrc=item.get("isrc"),
            mlc_song_code=item.get("mlc_song_code"),
            source="sample",
            raw={"sample": True},
        )
        # If an explicitly synthetic fixture includes a contract, preserve it.
        if item.get("raw") and isinstance(item["raw"], dict) and "artist" in item["raw"]:
            try:
                save_contract(
                    db,
                    item["key"],
                    owner,
                    item["raw"],
                    expected_version=0,
                    editor="system",
                    note="Seeded from fixture",
                )
            except Exception as e:
                logger.warning(f"Failed to seed contract for {item['key']}: {e}")
        created += 1
    _audit(db, owner_email=owner, actor_email=owner, action="catalog.seed_sample", details={"created": created, "duplicates": duplicates})
    return CatalogSeedResponse(ok=True, created=created, duplicates=duplicates)


@app.post("/catalog/reset-sample")
def catalog_reset_sample(
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    rows = (
        db.query(CatalogItemRecord)
        .filter(CatalogItemRecord.owner_email == owner, CatalogItemRecord.source == "sample")
        .all()
    )
    removed = len(rows)
    for r in rows:
        db.delete(r)
    db.commit()
    _audit(db, owner_email=owner, actor_email=owner, action="catalog.reset_sample", details={"removed": removed})
    return CatalogSeedResponse(ok=True, removed=removed)


@app.get("/catalog/list")
def catalog_list(
    q: Optional[str] = Query(default=None, description="Search by title/artist/key"),
    item_type: Optional[str] = Query(default=None, description="work|recording"),
    source: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    query = db.query(CatalogItemRecord).filter(CatalogItemRecord.owner_email == owner)
    if item_type in ("work", "recording"):
        query = query.filter(CatalogItemRecord.item_type == item_type)
    if source:
        query = query.filter(CatalogItemRecord.source == source)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (CatalogItemRecord.title.ilike(like))
            | (CatalogItemRecord.artist.ilike(like))
            | (CatalogItemRecord.key.ilike(like))
        )
    total = query.count()
    rows = query.order_by(CatalogItemRecord.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "items": [
            {
                "id": r.id,
                "key": r.key,
                "title": r.title,
                "type": r.item_type,
                "artist": r.artist,
                "isrc": r.isrc,
                "mlcSongCode": r.mlc_song_code,
                "mbid": r.mbid,
                "release": r.release_title,
                "releaseDate": r.release_date,
                "territory": r.territory,
                "source": r.source,
                "updated_at": r.updated_at,
            }
            for r in rows
        ],
    }


@app.get("/catalog/faceted")
def catalog_faceted_search(
    q: Optional[str] = Query(default=None),
    intended_usage: str = Query(default="streaming_visual"),
    stance: Optional[str] = Query(default=None, description="allowed|requires_approval|blocked"),
    approval_required: Optional[bool] = Query(default=None),
    blocked_restriction: Optional[str] = Query(default=None, description="restriction key that must be denied"),
    territory: Optional[str] = Query(default=None),
    release_date_from: Optional[str] = Query(default=None),
    release_date_to: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    """
    Faceted catalog search:
    - Filters on catalog metadata plus computed stance derived from the saved rights contract.
    """
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    query = db.query(CatalogItemRecord).filter(CatalogItemRecord.owner_email == owner)
    if territory:
        query = query.filter(CatalogItemRecord.territory == territory)
    if release_date_from:
        query = query.filter(CatalogItemRecord.release_date >= release_date_from)
    if release_date_to:
        query = query.filter(CatalogItemRecord.release_date <= release_date_to)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (CatalogItemRecord.title.ilike(like))
            | (CatalogItemRecord.artist.ilike(like))
            | (CatalogItemRecord.key.ilike(like))
        )
    total = query.count()
    rows = query.order_by(CatalogItemRecord.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for r in rows:
        record = load_contract(db, r.key, owner)
        contract = deepcopy(record.contract_json) if record else default_contract_template(owner)
        matrix = compute_effective_matrix(contract)
        usage_matrix = matrix.get("usage") or {}
        restriction_matrix = matrix.get("restrictions") or {}
        headline = _derive_headline_status(usage_matrix, intended_usage)
        if stance and headline != stance:
            continue
        if approval_required is not None:
            if approval_required != (headline == "requires_approval"):
                continue
        if blocked_restriction:
            if restriction_matrix.get(blocked_restriction) != "denied":
                continue
        # Compute combined AI/Generative protection status
        # Most restrictive of: ai_training_recursive, derivative_remix, likeness_voice_clone
        ai_training = usage_matrix.get("ai_training_recursive", "allowed")
        derivative = usage_matrix.get("derivative_remix", "allowed")
        voice_clone = restriction_matrix.get("likeness_voice_clone", "allowed")
        # Map restriction "denied" to "blocked" for consistency
        if voice_clone == "denied":
            voice_clone = "blocked"
        elif voice_clone == "conditional":
            voice_clone = "requires_approval"
        # Most restrictive wins: blocked > requires_approval > allowed
        ai_statuses = [ai_training, derivative, voice_clone]
        if "blocked" in ai_statuses:
            ai_gen_status = "blocked"
        elif "requires_approval" in ai_statuses:
            ai_gen_status = "requires_approval"
        else:
            ai_gen_status = "allowed"
        items.append(
            {
                "id": r.id,
                "key": r.key,
                "title": r.title,
                "type": r.item_type,
                "artist": r.artist,
                "isrc": r.isrc,
                "mlcSongCode": r.mlc_song_code,
                "releaseDate": r.release_date,
                "territory": r.territory,
                "headlineStatus": headline,
                "aiGenStatus": ai_gen_status,
                "approvalWindowDays": ((contract.get("artist") or {}).get("approval") or {}).get("approvalWindowDays"),
                "blockedRestrictions": [k for k, v in restriction_matrix.items() if v == "denied"],
                "updated_at": r.updated_at,
            }
        )
    return {"total": total, "page": page, "pageSize": page_size, "items": items}


# --- Saved searches (smart folders) ---


class SavedSearchCreateRequest(BaseModel):
    name: str
    query: Dict[str, Any]
    is_smart_folder: Optional[bool] = False


@app.get("/saved-searches/list")
def saved_searches_list(
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    rows = db.query(SavedSearchRecord).filter(SavedSearchRecord.owner_email == owner).order_by(SavedSearchRecord.updated_at.desc()).all()
    return {
        "items": [
            {"id": r.id, "name": r.name, "query": r.query, "isSmartFolder": bool(r.is_smart_folder), "updatedAt": r.updated_at}
            for r in rows
        ]
    }


@app.post("/saved-searches/create")
def saved_searches_create(
    req: SavedSearchCreateRequest,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    row = SavedSearchRecord(owner_email=owner, name=req.name, query=req.query, is_smart_folder=bool(req.is_smart_folder))
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(db, owner_email=owner, actor_email=owner, action="saved_search.create", details={"name": req.name})
    return {"ok": True, "id": row.id}


@app.post("/saved-searches/delete")
def saved_searches_delete(
    search_id: str,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    row = db.query(SavedSearchRecord).filter(SavedSearchRecord.owner_email == owner, SavedSearchRecord.id == search_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Saved search not found")
    db.delete(row)
    db.commit()
    _audit(db, owner_email=owner, actor_email=owner, action="saved_search.delete", details={"id": search_id})
    return {"ok": True}


@app.get("/catalog/export/csv")
def catalog_export_csv(
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    rows = (
        db.query(CatalogItemRecord)
        .filter(CatalogItemRecord.owner_email == owner)
        .order_by(CatalogItemRecord.updated_at.desc())
        .all()
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["key", "title", "type", "artist", "isrc", "mlc_song_code", "mbid", "release_title", "release_date", "territory", "source"])
    for r in rows:
        writer.writerow([r.key, r.title, r.item_type, r.artist or "", r.isrc or "", r.mlc_song_code or "", r.mbid or "", r.release_title or "", r.release_date or "", r.territory or "", r.source or ""])
    _audit(db, owner_email=owner, actor_email=owner, action="catalog.export.csv", details={"count": len(rows)})
    return {"csv": out.getvalue(), "count": len(rows)}


@app.post("/catalog/import/csv")
async def catalog_import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except Exception:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")
    reader = csv.DictReader(io.StringIO(text))
    required_cols = {"title"}
    missing = [c for c in required_cols if c not in (reader.fieldnames or [])]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Missing required columns",
                "missing": missing,
                "fixIt": "Add a 'title' column. Optional columns: key,type,artist,isrc,mlc_song_code,mbid,release_date,territory",
            },
        )
    created = 0
    updated = 0
    errors: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    duplicates = 0

    for idx, row in enumerate(reader, start=2):  # header is line 1
        try:
            title = (row.get("title") or "").strip()
            if not title:
                raise ValueError("title is required")
            item_type = (row.get("type") or "work").strip().lower()
            if item_type not in ("work", "recording"):
                raise ValueError("type must be 'work' or 'recording'")
            isrc = (row.get("isrc") or "").strip() or None
            mlc_sc = (row.get("mlc_song_code") or row.get("mlcSongCode") or "").strip() or None
            key = (row.get("key") or "").strip() or (mlc_sc or isrc or title)
            if key in seen_keys:
                duplicates += 1
                continue
            seen_keys.add(key)

            existing = (
                db.query(CatalogItemRecord)
                .filter(CatalogItemRecord.owner_email == owner, CatalogItemRecord.key == key)
                .first()
            )
            _upsert_catalog_item(
                db,
                owner_email=owner,
                key=key,
                title=title,
                item_type=item_type,
                artist=(row.get("artist") or "").strip() or None,
                isrc=isrc,
                mlc_song_code=mlc_sc,
                mbid=(row.get("mbid") or "").strip() or None,
                release_title=(row.get("release_title") or "").strip() or None,
                release_date=(row.get("release_date") or "").strip() or None,
                territory=(row.get("territory") or "").strip() or None,
                source="csv_import",
                raw={"importFile": file.filename, "importLine": idx},
            )
            if existing:
                updated += 1
            else:
                created += 1
        except Exception as e:
            errors.append(
                {
                    "line": idx,
                    "error": str(e),
                    "row": row,
                    "fixIt": "Ensure required fields exist and 'type' is work|recording. Use key or isrc/mlc_song_code to prevent duplicates.",
                }
            )
    _audit(
        db,
        owner_email=owner,
        actor_email=owner,
        action="catalog.import.csv",
        details={"created": created, "updated": updated, "errors": len(errors), "duplicatesSkipped": duplicates},
    )
    return {"ok": True, "created": created, "updated": updated, "duplicatesSkipped": duplicates, "errors": errors}


@app.post("/catalog/import/cwr")
async def catalog_import_cwr(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    """
    Minimal CWR ingest:
    - Extracts work titles from NWR records (best-effort).
    - Returns per-line warnings for unsupported/empty records.
    """
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=400, detail="CWR must be text-decodable")

    created = 0
    warnings: List[Dict[str, Any]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        rec_type = (line[:3] or "").strip()
        if rec_type != "NWR":
            continue
        # CWR is fixed-width; titles commonly appear early in NWR lines.
        # We do best-effort extraction and clearly flag limitations.
        title_guess = (line[3:73] if len(line) >= 73 else line[3:]).strip()
        if not title_guess:
            warnings.append({"line": idx, "warning": "Empty NWR title; skipped"})
            continue
        key = f"CWR:{title_guess}".replace(" ", "_")[:128]
        _upsert_catalog_item(
            db,
            owner_email=owner,
            key=key,
            title=title_guess,
            item_type="work",
            artist=None,
            source="cwr_import",
            raw={"importFile": file.filename, "cwrRecordType": "NWR", "importLine": idx},
        )
        created += 1
    _audit(db, owner_email=owner, actor_email=owner, action="catalog.import.cwr", details={"created": created, "warnings": len(warnings)})
    return {
        "ok": True,
        "created": created,
        "warnings": warnings,
        "note": "CWR parsing is best-effort (NWR titles only). For full fidelity, prefer CSV with explicit columns.",
    }


# --- Claims (email verification + duplicate flags) ---


class ClaimCreateRequest(BaseModel):
    key: str
    claimant_email: str
    note: Optional[str] = None


@app.post("/claims/create")
def create_claim(
    req: ClaimCreateRequest,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    if not req.key or not req.claimant_email:
        raise HTTPException(status_code=400, detail="key and claimant_email required")
    existing = (
        db.query(ClaimRecord)
        .filter(ClaimRecord.owner_email == owner, ClaimRecord.key == req.key, ClaimRecord.claimant_email == req.claimant_email)
        .order_by(ClaimRecord.created_at.desc())
        .first()
    )
    if existing and existing.status in ("pending", "verified"):
        return {"ok": True, "claimId": existing.id, "status": existing.status, "duplicate": True}

    claim = ClaimRecord(
        owner_email=owner,
        key=req.key,
        claimant_email=req.claimant_email.strip(),
        status="pending",
        verification_note=req.note,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(claim)
    db.flush()
    _record_v1_audit(
        db,
        org_id=req.org_id,
        principal=V1Principal(user=user),
        action="authority_claim.asserted",
        resource_type="authority_claim",
        resource_id=claim.id,
        details={
            "workKey": claim.work_key,
            "rightType": claim.right_type,
            "territory": claim.territory,
        },
    )
    db.commit()
    db.refresh(claim)
    _audit(db, owner_email=owner, actor_email=req.claimant_email, action="claim.create", key=req.key, entity_id=claim.id, details={"note": req.note})
    # Email-based verification link (optional: uses the configured provider)
    exp = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.RIGHTS_MAGIC_LINK_EXP_MINUTES)
    token = jwt.encode({"claim_id": claim.id, "email": req.claimant_email, "exp": exp}, settings.RIGHTS_MAGIC_LINK_SECRET, algorithm="HS256")
    link = f"{settings.CONSOLE_BASE_URL}/claims/verify?token={token}"
    try:
        notification_provider.send(
            to_emails=[req.claimant_email],
            subject="Verify your work claim",
            text=f"Verify your claim for key {req.key}: {link}\n\nIf you did not request this, ignore this email.",
        )
    except Exception:
        pass
    return {"ok": True, "claimId": claim.id, "status": claim.status, "verifyLink": link}


@app.post("/claims/verify")
def verify_claim(token: str, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, settings.RIGHTS_MAGIC_LINK_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Token expired")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid token: {str(e)}")
    claim_id = payload.get("claim_id")
    email = payload.get("email")
    if not claim_id or not email:
        raise HTTPException(status_code=400, detail="Invalid token payload")
    claim = db.query(ClaimRecord).filter(ClaimRecord.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.claimant_email != email:
        raise HTTPException(status_code=403, detail="Email mismatch")
    claim.status = "verified"
    claim.verified_at = datetime.datetime.utcnow()
    db.commit()
    _audit(db, owner_email=claim.owner_email, actor_email=email, action="claim.verified", key=claim.key, entity_id=claim.id)
    return {"ok": True, "claimId": claim.id, "status": claim.status}


# --- Approvals workflow ---


class ApprovalRequestCreate(BaseModel):
    key: str
    due_in_days: Optional[int] = 7
    note: Optional[str] = None


@app.post("/approvals/request")
def approvals_request(
    req: ApprovalRequestCreate,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _require_user(_get_current_user(db, x_session_id, x_user_email))
    due = datetime.datetime.utcnow() + datetime.timedelta(days=int(req.due_in_days or 7))
    ar = ApprovalRequestRecord(
        owner_email=owner,
        key=req.key,
        requested_by=user.email,
        requested_at=datetime.datetime.utcnow(),
        due_at=due,
        status="open",
        decision_by=None,
        decided_at=None,
        decision_note=None,
        change_summary=None,
    )
    db.add(ar)
    db.commit()
    db.refresh(ar)
    _audit(db, owner_email=owner, actor_email=user.email, action="approval.request", key=req.key, entity_id=ar.id, details={"dueAt": due.isoformat(), "note": req.note})

    # Notifications (best-effort)
    try:
        send_slack_message(
            slack_webhook_url=settings.SLACK_WEBHOOK_URL,
            text=f"[Rights Console] Approval requested for {req.key} by {user.email}. Due {due.date().isoformat()}",
        )
    except Exception:
        pass
    try:
        notification_provider.send(
            to_emails=[owner],
            subject=f"Approval requested: {req.key}",
            text=f"Approval requested for {req.key} by {user.email}.\nDue: {due.isoformat()}\n\nOpen: {settings.CONSOLE_BASE_URL}?key={req.key}&view=detail",
        )
    except Exception:
        pass
    return {"ok": True, "approvalId": ar.id, "status": ar.status, "dueAt": ar.due_at}


class ApprovalDecideRequest(BaseModel):
    approval_id: str
    decision: str  # approved | rejected
    note: Optional[str] = None


@app.post("/approvals/decide")
def approvals_decide(
    req: ApprovalDecideRequest,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _require_user(_get_current_user(db, x_session_id, x_user_email))
    ar = db.query(ApprovalRequestRecord).filter(ApprovalRequestRecord.id == req.approval_id, ApprovalRequestRecord.owner_email == owner).first()
    if not ar:
        raise HTTPException(status_code=404, detail="Approval not found")
    if ar.status != "open":
        raise HTTPException(status_code=400, detail=f"Approval is not open (status={ar.status})")
    decision = req.decision.strip().lower()
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be approved|rejected")
    ar.status = decision
    ar.decision_by = user.email
    ar.decided_at = datetime.datetime.utcnow()
    ar.decision_note = req.note
    db.commit()
    _audit(db, owner_email=owner, actor_email=user.email, action="approval.decide", key=ar.key, entity_id=ar.id, details={"decision": decision, "note": req.note})
    _emit_event(
        db,
        owner_email=owner,
        event="approval.decided",
        payload={"key": ar.key, "approvalId": ar.id, "decision": decision, "decidedBy": user.email, "decidedAt": ar.decided_at.isoformat() if ar.decided_at else None},
    )
    return {"ok": True, "approvalId": ar.id, "status": ar.status, "decidedAt": ar.decided_at}


@app.get("/approvals/list")
def approvals_list(
    key: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    query = db.query(ApprovalRequestRecord).filter(ApprovalRequestRecord.owner_email == owner)
    if key:
        query = query.filter(ApprovalRequestRecord.key == key)
    if status:
        query = query.filter(ApprovalRequestRecord.status == status)
    rows = query.order_by(ApprovalRequestRecord.requested_at.desc()).limit(200).all()
    return {
        "items": [
            {
                "id": r.id,
                "key": r.key,
                "status": r.status,
                "requestedBy": r.requested_by,
                "requestedAt": r.requested_at,
                "dueAt": r.due_at,
                "decisionBy": r.decision_by,
                "decidedAt": r.decided_at,
                "decisionNote": r.decision_note,
            }
            for r in rows
        ]
    }


# --- Comments / @mentions ---


class CommentCreateRequest(BaseModel):
    key: str
    body: str
    mentions: Optional[List[str]] = None


@app.post("/comments/create")
def comments_create(
    req: CommentCreateRequest,
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
    x_session_id: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    user = _require_user(_get_current_user(db, x_session_id, x_user_email))
    thread = db.query(CommentThreadRecord).filter(CommentThreadRecord.owner_email == owner, CommentThreadRecord.key == req.key).first()
    if not thread:
        thread = CommentThreadRecord(owner_email=owner, key=req.key, created_at=datetime.datetime.utcnow())
        db.add(thread)
        db.commit()
        db.refresh(thread)
    comment = CommentRecord(
        thread_id=thread.id,
        author_email=user.email,
        body=req.body,
        mentions=req.mentions or [],
        created_at=datetime.datetime.utcnow(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    _audit(db, owner_email=owner, actor_email=user.email, action="comment.create", key=req.key, entity_id=comment.id, details={"mentions": req.mentions or []})
    # best-effort notifications
    try:
        send_slack_message(
            slack_webhook_url=settings.SLACK_WEBHOOK_URL,
            text=f"[Rights Console] Comment on {req.key} by {user.email}: {req.body[:160]}",
        )
    except Exception:
        pass
    if req.mentions:
        try:
            notification_provider.send(
                to_emails=req.mentions,
                subject=f"Mentioned in Rights Console: {req.key}",
                text=f"You were mentioned by {user.email} on {req.key}:\n\n{req.body}\n\nOpen: {settings.CONSOLE_BASE_URL}?key={req.key}&view=detail",
            )
        except Exception:
            pass
    return {"ok": True, "threadId": thread.id, "commentId": comment.id}


@app.get("/comments/thread")
def comments_thread(
    key: str = Query(...),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    thread = db.query(CommentThreadRecord).filter(CommentThreadRecord.owner_email == owner, CommentThreadRecord.key == key).first()
    if not thread:
        return {"threadId": None, "items": []}
    rows = db.query(CommentRecord).filter(CommentRecord.thread_id == thread.id).order_by(CommentRecord.created_at.asc()).all()
    return {
        "threadId": thread.id,
        "items": [
            {
                "id": r.id,
                "author": r.author_email,
                "body": r.body,
                "mentions": r.mentions or [],
                "createdAt": r.created_at,
            }
            for r in rows
        ],
    }


@app.post("/rights/export")
def rights_export(keys: Optional[List[str]] = Query(default=None), db: Session = Depends(get_db), x_artist_name: Optional[str] = Header(default=None)):
    artist = x_artist_name
    if not artist:
        raise HTTPException(status_code=400, detail="Artist lock required")
    query = db.query(RightsContractRecord).filter(RightsContractRecord.artist == artist)
    if keys:
        query = query.filter(RightsContractRecord.key.in_(keys))
    rows = query.order_by(RightsContractRecord.updated_at.desc()).all()
    items = []
    for row in rows:
        contract = deepcopy(row.contract_json)
        compute_effective_matrix(contract)
        items.append(
            {
                "key": row.key,
                "rightsContract": contract,
                "version": row.version,
                "updated_at": row.updated_at,
                "effectiveMatrix": row.effective_matrix,
                "editor": row.editor,
                "source": row.source,
            }
        )
    _audit(db, owner_email=artist, actor_email=artist, action="rights.export.json", details={"count": len(items), "keysFiltered": bool(keys)})
    return {"items": items}


@app.get("/rights/export/csv")
def rights_export_csv(
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
):
    artist = x_artist_name
    if not artist:
        raise HTTPException(status_code=400, detail="Artist lock required")
    rows = (
        db.query(RightsContractRecord)
        .filter(RightsContractRecord.artist == artist)
        .order_by(RightsContractRecord.updated_at.desc())
        .all()
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "key",
            "version",
            "updated_at",
            "headlineStatus_streaming_visual",
            "approvalWindowDays",
            "blockedRestrictions",
            "usageMatrix_json",
            "restrictionMatrix_json",
        ]
    )
    for r in rows:
        contract = deepcopy(r.contract_json)
        matrix = compute_effective_matrix(contract)
        usage = matrix.get("usage") or {}
        restrictions = matrix.get("restrictions") or {}
        headline = _derive_headline_status(usage, "streaming_visual")
        approval_days = ((contract.get("artist") or {}).get("approval") or {}).get("approvalWindowDays")
        blocked = [k for k, v in restrictions.items() if v == "denied"]
        writer.writerow(
            [
                r.key,
                r.version,
                r.updated_at.isoformat() if r.updated_at else "",
                headline,
                approval_days or "",
                "|".join(blocked),
                JSONResponse(content=usage).body.decode("utf-8"),
                JSONResponse(content=restrictions).body.decode("utf-8"),
            ]
        )
    _audit(db, owner_email=artist, actor_email=artist, action="rights.export.csv", details={"count": len(rows)})
    return {"csv": out.getvalue(), "count": len(rows)}


# --- Analytics & QA ---


@app.get("/dashboard/summary")
def dashboard_summary(
    intended_usage: str = Query(default="streaming_visual"),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    # counts by stance across catalog items
    items = db.query(CatalogItemRecord).filter(CatalogItemRecord.owner_email == owner).all()
    stance_counts = {"allowed": 0, "requires_approval": 0, "blocked": 0}
    for it in items:
        rec = load_contract(db, it.key, owner)
        contract = deepcopy(rec.contract_json) if rec else default_contract_template(owner)
        matrix = compute_effective_matrix(contract)
        headline = _derive_headline_status(matrix.get("usage") or {}, intended_usage)
        if headline in stance_counts:
            stance_counts[headline] += 1
    approvals_pending = (
        db.query(ApprovalRequestRecord)
        .filter(ApprovalRequestRecord.owner_email == owner, ApprovalRequestRecord.status == "open")
        .count()
    )
    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    changes_week = (
        db.query(AuditLogRecord)
        .filter(AuditLogRecord.owner_email == owner, AuditLogRecord.created_at >= since)
        .count()
    )
    ingest_errors = 0
    ingest_rows = (
        db.query(AuditLogRecord)
        .filter(AuditLogRecord.owner_email == owner, AuditLogRecord.action.in_(["catalog.import.csv", "rights.import.json", "catalog.import.cwr"]))
        .order_by(AuditLogRecord.created_at.desc())
        .limit(50)
        .all()
    )
    for r in ingest_rows:
        try:
            ingest_errors += int((r.details or {}).get("errors") or 0)
        except Exception:
            pass
    return {
        "ok": True,
        "stanceCounts": stance_counts,
        "approvalsPending": approvals_pending,
        "changesLast7Days": changes_week,
        "recentIngestErrors": ingest_errors,
    }


@app.get("/qa/validate-batch")
def qa_validate_batch(
    batch_id: str = Query(...),
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
):
    artist = x_artist_name
    if not artist:
        raise HTTPException(status_code=400, detail="Artist lock required")
    rows = (
        db.query(RightsHistoryRecord)
        .filter(RightsHistoryRecord.artist == artist, RightsHistoryRecord.batch_id == batch_id)
        .order_by(RightsHistoryRecord.version.desc())
        .all()
    )
    keys = sorted(set(r.key for r in rows))
    issues: List[Dict[str, Any]] = []
    for key in keys:
        latest = load_contract(db, key, artist)
        if not latest:
            continue
        contract = deepcopy(latest.contract_json)
        validation = rights_validate(RightsValidateRequest(key=key, contract=contract))
        if validation.get("issues"):
            issues.append({"key": key, "issues": validation["issues"]})
    ready = len(issues) == 0
    return {"ok": True, "batchId": batch_id, "readyToPublish": ready, "keys": keys, "issues": issues}


class RightsImportPayload(BaseModel):
    items: List[Dict[str, Any]]
    note: Optional[str] = None


@app.post("/rights/import")
def rights_import(payload: RightsImportPayload, db: Session = Depends(get_db), x_artist_name: Optional[str] = Header(default=None)):
    """
    Bulk import of rights contracts (JSON).
    Expected item shape matches /rights/export items:
    - key
    - rightsContract (the policy JSON)
    """
    artist = x_artist_name
    if not artist:
        raise HTTPException(status_code=400, detail="Artist lock required")
    created = 0
    updated = 0
    errors: List[Dict[str, Any]] = []
    batch_id = str(uuid.uuid4())
    for idx, item in enumerate(payload.items or [], start=1):
        try:
            key = str(item.get("key") or "").strip()
            contract = item.get("rightsContract") or item.get("contract")
            if not key:
                raise ValueError("Missing key")
            if not isinstance(contract, dict):
                raise ValueError("Missing rightsContract object")
            existing = load_contract(db, key, artist)
            saved = save_contract(
                db,
                key,
                artist,
                contract,
                expected_version=existing.version if existing else 0,
                editor=artist,
                source="import_json",
                batch_id=batch_id,
                note=payload.note or "Imported contracts",
            )
            if existing:
                updated += 1
            else:
                created += 1
            # keep catalog updated (best-effort)
            title = contract.get("title") or contract.get("workTitle") or contract.get("artistName") or key
            _upsert_catalog_item(
                db,
                owner_email=artist,
                key=key,
                title=str(title),
                item_type="work",
                artist=artist,
                source="import_json",
                raw={"importBatchId": batch_id, "importIndex": idx, "contractVersion": saved.version},
            )
        except Exception as e:
            errors.append({"index": idx, "error": str(e), "item": {"key": item.get("key")}})
    _audit(
        db,
        owner_email=artist,
        actor_email=artist,
        action="rights.import.json",
        details={"batchId": batch_id, "created": created, "updated": updated, "errors": len(errors), "note": payload.note},
    )
    return {
        "ok": True,
        "batchId": batch_id,
        "created": created,
        "updated": updated,
        "errors": errors,
        "fixIt": "Ensure each item includes a non-empty 'key' and a 'rightsContract' JSON object.",
    }


class RecommendMacroRequest(BaseModel):
    artist: str
    genres: Optional[List[str]] = None
    career_stage: Optional[str] = None
    context: Optional[str] = None


MACROS_VERSION = "2025-12-11"


def _macro_usage_examples() -> Dict[str, Dict[str, str]]:
    """
    Per-macro examples per usage category (short, UI-ready).
    These are illustrative guidance strings; they do not override the contract.
    """
    return {
        "brand_safe": {
            "ads_brand": "Allowed for mainstream brands; must avoid restricted categories (political, adult, weapons).",
            "ads_political": "Blocked (no campaigns or partisan messaging).",
            "film_tv": "Allowed for scripted and documentary sync.",
            "ugc_creator": "Allowed for creators; no deceptive endorsements.",
        },
        "sync_optimized": {
            "film_tv": "Allowed; expect fast approvals for placements and cue sheets.",
            "ads_brand": "Requires approval; pricing and context notes recommended.",
            "video_game": "Allowed; negotiate term and territory for interactive use.",
        },
        "creator_friendly": {
            "ugc_creator": "Allowed; enable creators to monetize and go viral.",
            "ai_training_recursive": "Blocked; no dataset reuse of outputs for model training.",
            "derivative_remix": "Allowed; remixes permitted unless restricted content applies.",
        },
    }


@app.get("/macros/list")
def macros_list():
    """
    Central source of truth for macros/templates.
    Frontend may fall back to local macros if needed.
    """
    # Keep this in sync with the frontend's RIGHTS_MACROS; versioned for auditability.
    macros = [
        {
            "id": "fully_open",
            "name": "🌍 Fully Open",
            "description": "Maximum exposure - allow all usage with minimal restrictions",
            "approvalWindowDays": 7,
            "tags": ["emerging", "new artist", "indie", "exposure", "growth", "visibility"],
        },
        {
            "id": "brand_safe",
            "name": "🛡️ Brand Safe",
            "description": "Commercial-friendly, block controversial content",
            "approvalWindowDays": 14,
            "tags": ["family", "mainstream", "commercial", "corporate", "safe", "advertiser friendly"],
        },
        {
            "id": "selective_premium",
            "name": "💎 Selective Premium",
            "description": "High-value placements only, approval required for premium contexts",
            "approvalWindowDays": 21,
            "tags": ["established", "premium", "selective", "high value", "quality control", "curated"],
        },
        {
            "id": "no_ads_artistic",
            "name": "🎨 No Ads - Artistic",
            "description": "Block advertising, prioritize artistic integrity",
            "approvalWindowDays": 30,
            "tags": ["artistic", "integrity", "non-commercial", "creative", "purist", "anti-commercial"],
        },
        {
            "id": "creator_friendly",
            "name": "✨ Creator Friendly",
            "description": "Optimize for UGC and social platforms, block AI training",
            "approvalWindowDays": 14,
            "tags": ["creator", "ugc", "social", "tiktok", "youtube", "viral", "influencer"],
        },
        {
            "id": "legacy_protective",
            "name": "🏛️ Legacy Protective",
            "description": "Strict approval process, protect catalog value",
            "approvalWindowDays": 45,
            "tags": ["legacy", "established", "catalog", "protective", "heritage", "classic"],
        },
        {
            "id": "sync_optimized",
            "name": "🎬 Sync Optimized",
            "description": "Prioritize film/TV placements, flexible for production needs",
            "approvalWindowDays": 21,
            "tags": ["sync", "film", "tv", "production", "soundtrack", "media"],
        },
    ]
    examples = _macro_usage_examples()
    return {"version": MACROS_VERSION, "macros": [{**m, "usageExamples": examples.get(m["id"], {})} for m in macros]}


class RightsValidateRequest(BaseModel):
    key: Optional[str] = None
    contract: Dict[str, Any]


@app.post("/rights/validate")
def rights_validate(req: RightsValidateRequest):
    """
    Conflict detector (guardrails). Returns warnings/errors; does not block saves by itself.
    """
    contract = req.contract or {}
    matrix = compute_effective_matrix(contract)
    usage = matrix.get("usage") or {}
    restrictions = matrix.get("restrictions") or {}
    approval_days = ((contract.get("artist") or {}).get("approval") or {}).get("approvalWindowDays") or 0
    pricing = ((contract.get("master") or {}).get("pricing") or {})
    base_price = pricing.get("basePriceUsd") or {}

    issues: List[Dict[str, Any]] = []

    # Approval window conflicts
    has_requires_approval = any(v == "requires_approval" for v in usage.values())
    if has_requires_approval and int(approval_days) <= 0:
        issues.append(
            {
                "severity": "warning",
                "code": "approval_window_missing",
                "message": "Some categories require approval, but approvalWindowDays is 0.",
                "fixIt": "Set approvalWindowDays (e.g., 7–30) so downstream UIs can display SLA expectations.",
                "field": "artist.approval.approvalWindowDays",
            }
        )
    if (not has_requires_approval) and int(approval_days) > 0:
        issues.append(
            {
                "severity": "info",
                "code": "approval_window_unused",
                "message": "Approval window is set, but no categories currently require approval.",
                "fixIt": "Either set at least one category to requires_approval or set approvalWindowDays to 0.",
                "field": "artist.approval.approvalWindowDays",
            }
        )

    # Restriction/usage contradictions (opinionated mappings)
    if restrictions.get("political") == "denied" and usage.get("ads_political") == "allowed":
        issues.append(
            {
                "severity": "warning",
                "code": "political_mismatch",
                "message": "Political restriction is denied, but political advertising is marked Allowed.",
                "fixIt": "Set ads_political to blocked/requires_approval or relax the political restriction.",
                "field": "matrix.usage.ads_political",
            }
        )
    if restrictions.get("likeness_voice_clone") == "denied" and usage.get("ai_training_recursive") == "allowed":
        issues.append(
            {
                "severity": "warning",
                "code": "voice_clone_training_mismatch",
                "message": "Voice/likeness cloning is denied, but recursive AI training is Allowed.",
                "fixIt": "Consider blocking ai_training_recursive or making likeness_voice_clone conditional if permitted under contract terms.",
                "field": "matrix.usage.ai_training_recursive",
            }
        )

    # Pricing/stance contradictions
    for usage_key, state in usage.items():
        if state == "blocked" and usage_key in base_price:
            issues.append(
                {
                    "severity": "info",
                    "code": "price_for_blocked",
                    "message": f"Pricing is set for '{usage_key}', but that category is Blocked.",
                    "fixIt": "Remove the price entry or change the category to requires_approval/allowed.",
                    "field": f"master.pricing.basePriceUsd.{usage_key}",
                }
            )
    for k, v in base_price.items():
        try:
            if float(v) < 0:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "negative_price",
                        "message": f"Negative price for '{k}'.",
                        "fixIt": "Use a non-negative USD price.",
                        "field": f"master.pricing.basePriceUsd.{k}",
                    }
                )
        except Exception:
            issues.append(
                {
                    "severity": "warning",
                    "code": "non_numeric_price",
                    "message": f"Non-numeric price for '{k}'.",
                    "fixIt": "Use a number (e.g., 250, 1000).",
                    "field": f"master.pricing.basePriceUsd.{k}",
                }
            )

    return {"ok": True, "issues": issues, "issueCount": len(issues)}

def _recommend_macro_fallback(artist: str, genres: list, career_stage: str) -> dict:
    """Score macros by matching genres + career_stage against macro tags (offline fallback)."""
    macros = [
        {"id": "fully_open", "tags": ["emerging", "new artist", "exposure", "viral", "indie", "electronic", "hip-hop", "growth"]},
        {"id": "brand_safe", "tags": ["family", "mainstream", "corporate", "pop", "country", "established", "safe"]},
        {"id": "selective_premium", "tags": ["established", "legacy", "premium", "jazz", "classical", "r&b", "curated"]},
        {"id": "sync_optimized", "tags": ["cinematic", "instrumental", "ambient", "soundtrack", "production", "sync", "film", "tv"]},
        {"id": "creator_friendly", "tags": ["emerging", "social", "tiktok", "youtube", "viral", "influencer", "ugc"]},
        {"id": "legacy_protective", "tags": ["legacy", "established", "catalog", "protective", "heritage", "classic"]},
        {"id": "no_ads_artistic", "tags": ["artistic", "integrity", "non-commercial", "creative", "purist", "jazz", "classical"]},
    ]

    # Build match terms from input
    match_terms = set()
    if career_stage:
        match_terms.add(career_stage.lower())
    for genre in (genres or []):
        match_terms.add(genre.lower())

    # Score each macro
    best_macro = "fully_open"
    best_score = 0
    for macro in macros:
        score = len(match_terms & set(macro["tags"]))
        if score > best_score:
            best_score = score
            best_macro = macro["id"]

    # Generate reasoning based on matches
    reasoning = f"Recommended based on {career_stage or 'artist'} profile"
    if genres:
        reasoning += f" and {', '.join(genres[:2])} genre focus"

    return {"macroId": best_macro, "reasoning": reasoning}


@app.post("/rights/recommend-macro")
async def recommend_macro(request: RecommendMacroRequest):
    """AI-powered macro recommendation based on artist metadata. Falls back to tag-based matching if OpenRouter unavailable."""

    # If no OpenRouter key, use fallback directly (no failed API call)
    if not settings.OPENROUTER_API_KEY:
        return _recommend_macro_fallback(
            request.artist,
            request.genres or [],
            request.career_stage or ""
        )

    macros = [
        {
            "id": "fully_open",
            "name": "🌍 Fully Open",
            "tags": ["emerging", "new artist", "indie", "exposure", "growth", "visibility"],
        },
        {
            "id": "brand_safe",
            "name": "🛡️ Brand Safe",
            "tags": ["family", "mainstream", "commercial", "corporate", "safe", "advertiser friendly"],
        },
        {
            "id": "selective_premium",
            "name": "💎 Selective Premium",
            "tags": ["established", "premium", "selective", "high value", "quality control", "curated"],
        },
        {
            "id": "no_ads_artistic",
            "name": "🎨 No Ads - Artistic",
            "tags": ["artistic", "integrity", "non-commercial", "creative", "purist", "anti-commercial"],
        },
        {
            "id": "creator_friendly",
            "name": "✨ Creator Friendly",
            "tags": ["creator", "ugc", "social", "tiktok", "youtube", "viral", "influencer"],
        },
        {
            "id": "legacy_protective",
            "name": "🏛️ Legacy Protective",
            "tags": ["legacy", "established", "catalog", "protective", "heritage", "classic"],
        },
        {
            "id": "sync_optimized",
            "name": "🎬 Sync Optimized",
            "tags": ["sync", "film", "tv", "production", "soundtrack", "media"],
        },
    ]

    # Build AI prompt
    prompt = f"""You are a music rights advisor. Based on the artist's profile, recommend the most suitable rights macro template.

Artist: {request.artist}
"""
    if request.genres:
        prompt += f"Genres: {', '.join(request.genres)}\n"
    if request.career_stage:
        prompt += f"Career Stage: {request.career_stage}\n"
    if request.context:
        prompt += f"Additional Context: {request.context}\n"

    prompt += f"""
Available macros:
"""
    for macro in macros:
        prompt += f"- {macro['id']}: {macro['name']} (tags: {', '.join(macro['tags'])})\n"

    prompt += """
Respond with a JSON object containing:
- "macroId": the ID of the recommended macro (e.g., "fully_open" or "brand_safe")
- "reasoning": a 1-2 sentence justification explaining why this macro fits the artist's profile

Example response:
{"macroId": "creator_friendly", "reasoning": "This artist's social media presence and viral potential makes creator-friendly licensing ideal for maximizing reach while maintaining control."}"""

    try:
        import httpx
        import json
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENROUTER_INTENT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            result = response.json()
            ai_response = result["choices"][0]["message"]["content"].strip()

            # Try to parse JSON response
            try:
                parsed = json.loads(ai_response)
                macro_id = parsed.get("macroId", "").lower()
                reasoning = parsed.get("reasoning", "Recommended based on artist profile")
            except:
                # Fallback: try to extract macro_id from raw response
                macro_id = ai_response.lower()
                reasoning = "Recommended based on artist profile"

            # Find matching macro
            for macro in macros:
                if macro["id"] in macro_id:
                    return {"macroId": macro["id"], "reasoning": reasoning}

            # Fallback
            return {"macroId": "fully_open", "reasoning": "Default recommendation for maximum exposure"}
    except Exception as e:
        # Use tag-based fallback on API error
        return _recommend_macro_fallback(
            request.artist,
            request.genres or [],
            request.career_stage or ""
        )


@app.get("/rights/similarity/suggest-macro")
def suggest_macro_for_key(
    key: str = Query(...),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    """
    Similarity suggestion: find the most common selected macro on 'similar' catalog items.
    Similarity definition (v1):
    - same owner + same artist (from catalog metadata)
    - fallback: all items under owner
    """
    owner = _owner_from_headers(x_owner_email, x_artist_name)
    item = db.query(CatalogItemRecord).filter(CatalogItemRecord.owner_email == owner, CatalogItemRecord.key == key).first()
    artist = item.artist if item else None

    # gather candidate keys
    q = db.query(CatalogItemRecord).filter(CatalogItemRecord.owner_email == owner)
    if artist:
        q = q.filter(CatalogItemRecord.artist == artist)
    candidates = q.limit(200).all()
    counts: Dict[str, int] = {}
    for c in candidates:
        rec = load_contract(db, c.key, owner)
        if not rec:
            continue
        meta = (rec.contract_json or {}).get("metadata") or {}
        mid = meta.get("selectedMacroId")
        if not mid:
            continue
        counts[mid] = counts.get(mid, 0) + 1
    if not counts:
        return {"ok": True, "macroId": None, "reasoning": "No prior macros found to learn from."}
    macro_id = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[0][0]
    reasoning = f"Suggested based on {counts[macro_id]} similar item(s) using this macro."
    return {"ok": True, "macroId": macro_id, "reasoning": reasoning, "counts": counts}


# --- Health ---
@app.get("/health")
def health():
    def status_flag(enabled: bool, mock: bool) -> str:
        if mock:
            return "mock"
        if enabled:
            return "live"
        return "disabled"

    # OpenRouter status: enabled if key present, otherwise using local fallback (still functional)
    openrouter_status = "live" if settings.OPENROUTER_API_KEY else "disabled (using local fallback)"
    if settings.MOCK_INTEGRATIONS and not settings.OPENROUTER_API_KEY:
        openrouter_status = "mock"

    integrations = {
        "mlc": status_flag(settings.MLC_ENABLED, settings.MOCK_INTEGRATIONS and not settings.MLC_ENABLED),
        "musicbrainz": status_flag(settings.MUSICBRAINZ_ENABLED, settings.MOCK_INTEGRATIONS and not settings.MUSICBRAINZ_ENABLED),
        "openrouter": {"status": openrouter_status, "required": False},
    }
    return {
        "status": "ok",
        "service": "rights-console",
        "time": datetime.datetime.utcnow().isoformat(),
        "mock_mode": settings.MOCK_INTEGRATIONS,
        "integrations": integrations,
    }


@app.get("/integrations/status")
def integration_status():
    return health()


# --- Utility functions ---

def apply_changes(contract: Dict[str, Any], changes: Dict[str, Any]) -> None:
    """Apply tri-state changes to usage and restriction matrices."""
    if not changes:
        return
    matrix = compute_effective_matrix(contract)

    # Tri-state usage changes: 'blocked', 'requires_approval', 'allowed'
    usage_changes: Dict[str, str] = changes.get("usageMatrix") or {}
    for usage_key, state in usage_changes.items():
        if state in ('blocked', 'requires_approval', 'allowed'):
            contract.setdefault("artist", {}).setdefault("usageMatrix", {})[usage_key] = state
            matrix.setdefault("usage", {})[usage_key] = state

    # Tri-state restriction changes: 'allowed', 'conditional', 'denied'
    restriction_changes: Dict[str, str] = changes.get("restrictionMatrix") or {}
    for restriction_key, state in restriction_changes.items():
        if state in ('allowed', 'conditional', 'denied'):
            contract.setdefault("artist", {}).setdefault("restrictionMatrix", {})[restriction_key] = state
            matrix.setdefault("restrictions", {})[restriction_key] = state

    # Approval window changes
    approval_changes: Dict[str, Any] = changes.get("approval") or {}
    if "approvalWindowDays" in approval_changes:
        contract.setdefault("artist", {}).setdefault("approval", {})["approvalWindowDays"] = int(approval_changes["approvalWindowDays"])

    # Pricing changes
    pricing_changes: Dict[str, Any] = changes.get("pricing") or {}
    if pricing_changes:
        master_pricing = contract.setdefault("master", {}).setdefault("pricing", {})
        for key, value in pricing_changes.items():
            if value is not None:
                master_pricing[key] = value


# --- Summaries for Clef integration ---

class RightsSummary(BaseModel):
    key: str
    artist: str
    headlineStatus: str  # allowed | requires_approval | blocked
    intendedUsage: Optional[str] = None
    approvalRequired: bool = False
    approvalWindowDays: Optional[int] = None
    restrictions: Dict[str, str] = {}
    pricing: Dict[str, Any] = {}
    matrix: Dict[str, Any] = {}
    deepLinkUrl: Optional[str] = None
    policyVersion: Optional[str] = None
    note: Optional[str] = None


def _derive_headline_status(usage_matrix: Dict[str, str], intended_usage: Optional[str]) -> str:
    # Primary: use intended usage if provided
    if intended_usage and intended_usage in usage_matrix:
        return usage_matrix[intended_usage]
    # Secondary: choose a common visual/creator default
    for fallback in ("streaming_visual", "ugc_creator", "personal_noncommercial"):
        if fallback in usage_matrix:
            return usage_matrix[fallback]
    # Otherwise pick the least permissive among keys present
    if not usage_matrix:
        return "blocked"
    # Order severity: blocked > requires_approval > allowed
    if any(v == "blocked" for v in usage_matrix.values()):
        return "blocked"
    if any(v == "requires_approval" for v in usage_matrix.values()):
        return "requires_approval"
    return "allowed"


def _compute_pricing_for_usage(contract: Dict[str, Any], intended_usage: Optional[str]) -> Dict[str, Any]:
    master = (contract or {}).get("master") or {}
    pricing = master.get("pricing") or {}
    base_price_usd = pricing.get("basePriceUsd") or {}
    stance_mult = float(pricing.get("licenseStanceMultiplier", 1.0) or 1.0)
    audience_mult = float(pricing.get("audienceReachMultiplier", 1.0) or 1.0)
    surcharges = pricing.get("surcharges") or {}

    out: Dict[str, Any] = {
        "licenseStanceMultiplier": stance_mult,
        "audienceReachMultiplier": audience_mult,
        "surcharges": surcharges,
        "basePriceUsd": base_price_usd,
    }
    if intended_usage and intended_usage in base_price_usd:
        base = float(base_price_usd.get(intended_usage) or 0.0)
        est = base * stance_mult * audience_mult
        out["estimatedPriceUsd"] = round(est, 2)
        out["basePriceUsdSelected"] = base
    return out


@app.get("/rights/summary")
def rights_summary(
    key: str = Query(..., description="Rights contract key: mlcSongCode | isrc | title"),
    intended_usage: Optional[str] = Query(
        default=None,
        description="Usage category to check (e.g., 'streaming_visual', 'ads_brand')"
    ),
    db: Session = Depends(get_db),
    x_artist_name: Optional[str] = Header(default=None),
):
    """
    Lightweight summary for Clef:
    - headlineStatus: allowed | requires_approval | blocked
    - approvalWindowDays (if applicable)
    - pricing estimate for intended_usage (if available)
    - restriction flags and deep link URL into the rights console UI
    """
    artist = x_artist_name or "Demo User"
    record = load_contract(db, key, artist)
    if record:
        contract = deepcopy(record.contract_json)
        matrix = compute_effective_matrix(contract)
        usage_matrix: Dict[str, str] = (matrix.get("usage") or {})
        restriction_matrix: Dict[str, str] = (matrix.get("restrictions") or {})
        headline = _derive_headline_status(usage_matrix, intended_usage)
        approval_days = ((contract.get("artist") or {}).get("approval") or {}).get("approvalWindowDays")
        pricing = _compute_pricing_for_usage(contract, intended_usage)
        deep_link = f"{settings.CONSOLE_BASE_URL}?artist={artist}&key={key}&view=detail"
        return RightsSummary(
            key=key,
            artist=artist,
            headlineStatus=headline,
            intendedUsage=intended_usage,
            approvalRequired=headline == "requires_approval",
            approvalWindowDays=approval_days,
            restrictions=restriction_matrix,
            pricing=pricing,
            matrix=matrix,
            deepLinkUrl=deep_link,
            policyVersion=contract.get("policyVersion"),
            note="Live contract",
        )
    # No record: return defaults based on template
    template = default_contract_template(artist)
    matrix = compute_effective_matrix(template)
    usage_matrix = matrix.get("usage") or {}
    restriction_matrix = matrix.get("restrictions") or {}
    headline = _derive_headline_status(usage_matrix, intended_usage)
    approval_days = ((template.get("artist") or {}).get("approval") or {}).get("approvalWindowDays")
    pricing = _compute_pricing_for_usage(template, intended_usage)
    deep_link = f"{settings.CONSOLE_BASE_URL}?artist={artist}&key={key}&view=detail"
    return RightsSummary(
        key=key,
        artist=artist,
        headlineStatus=headline,
        intendedUsage=intended_usage,
        approvalRequired=headline == "requires_approval",
        approvalWindowDays=approval_days,
        restrictions=restriction_matrix,
        pricing=pricing,
        matrix=matrix,
        deepLinkUrl=deep_link,
        policyVersion=template.get("policyVersion"),
        note="Using default template",
    )


@app.get("/rights/passport")
def rights_passport(
    key: str = Query(...),
    owner: Optional[str] = Query(default=None, description="Owner/org email (for share links)"),
    db: Session = Depends(get_db),
    x_owner_email: Optional[str] = Header(default=None),
    x_artist_name: Optional[str] = Header(default=None),
):
    """
    Rights passport: sharable read-only summary suitable for downstream partners.
    - Badges per usage category
    - Approval contact + escalation metadata
    - Pricing estimates + rationale notes
    """
    resolved_owner = (x_owner_email or x_artist_name or owner or "").strip()
    if not resolved_owner:
        raise HTTPException(status_code=400, detail="Owner required (X-Owner-Email or owner query param)")
    record = load_contract(db, key, resolved_owner)
    contract = deepcopy(record.contract_json) if record else default_contract_template(resolved_owner)
    matrix = compute_effective_matrix(contract)
    usage_matrix: Dict[str, str] = (matrix.get("usage") or {})
    restriction_matrix: Dict[str, str] = (matrix.get("restrictions") or {})
    approval_days = ((contract.get("artist") or {}).get("approval") or {}).get("approvalWindowDays")
    contact = contract.get("contact") or {}
    pricing = (contract.get("master") or {}).get("pricing") or {}
    rationale = pricing.get("rationaleNotes") or ""
    # compute estimates per usage where base prices exist
    base_price_usd = pricing.get("basePriceUsd") or {}
    stance_mult = float(pricing.get("licenseStanceMultiplier", 1.0) or 1.0)
    audience_mult = float(pricing.get("audienceReachMultiplier", 1.0) or 1.0)
    surcharges = pricing.get("surcharges") or {}
    estimates: Dict[str, Any] = {}
    for usage_key, base in base_price_usd.items():
        try:
            base_f = float(base)
        except Exception:
            continue
        est = base_f * stance_mult * audience_mult
        estimates[usage_key] = {
            "basePriceUsd": base_f,
            "estimatedPriceUsd": round(est, 2),
            "licenseStanceMultiplier": stance_mult,
            "audienceReachMultiplier": audience_mult,
            "surcharges": surcharges,
        }
    deep_link_edit = f"{settings.CONSOLE_BASE_URL}?owner={resolved_owner}&key={key}&view=detail"
    return {
        "key": key,
        "owner": resolved_owner,
        "policyVersion": contract.get("policyVersion"),
        "badges": usage_matrix,
        "approval": {"approvalWindowDays": approval_days},
        "contact": {
            "preferredChannel": contact.get("preferredChannel"),
            "email": contact.get("email") or resolved_owner,
            "slaHours": contact.get("slaHours"),
            "fallbackContact": contact.get("fallbackContact"),
            "notes": contact.get("notes"),
        },
        "restrictions": restriction_matrix,
        "pricing": {"estimates": estimates, "rationale": rationale},
        "deepLinkEdit": deep_link_edit,
        "updatedAt": record.updated_at if record else None,
        "note": "Live contract" if record else "Using default template",
    }


# --- Rights Node v1 contracts ---

RIGHT_TYPES = {"composition", "master", "lyrics", "performance", "voice", "likeness"}
ORGANIZATION_TYPES = {
    "artist",
    "label",
    "publisher",
    "administrator",
    "pro",
    "cmo",
    "collective",
    "rights_holder",
    "requester",
}
ORG_DECISION_ROLES = {"owner", "admin", "rights_manager"}
ORG_ADMIN_ROLES = {"owner", "admin"}


class NodeReadinessCheck(BaseModel):
    key: str
    status: str
    required: bool
    summary: str
    remediation: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class NodeReadiness(BaseModel):
    ready: bool
    deploymentMode: str
    checkedAt: str
    checks: List[NodeReadinessCheck]


class OrganizationOnboardingMilestone(BaseModel):
    key: str
    status: str
    summary: str
    action: Optional[str] = None
    count: int = 0


class OrganizationOnboardingStatus(BaseModel):
    organizationId: str
    organizationType: str
    complete: bool
    completedCount: int
    applicableCount: int
    milestones: List[OrganizationOnboardingMilestone]


class OrganizationCreateRequest(BaseModel):
    slug: str
    name: str
    organization_type: str = "rights_holder"
    default_territory: str = "worldwide"
    controlled_right_types: Optional[List[str]] = None
    ai_policy_preset: str = "review_each_ai_use"


class OrganizationMemberAddRequest(BaseModel):
    email: str
    role: str = "member"


class ApiCredentialCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: List[str] = Field(min_length=1)
    expires_in_days: int = Field(default=90, ge=1, le=365)


class RightsPolicyPutRequest(BaseModel):
    artist_name: str
    contract: Dict[str, Any]
    note: Optional[str] = None
    expected_version: int = 0


class AuthorityClaimCreateRequest(BaseModel):
    org_id: str
    rights_contract_id: str
    right_type: str
    territory: str = "worldwide"
    evidence: Dict[str, Any]


class AuthorityClaimVerifyRequest(BaseModel):
    evidence_note: Optional[str] = None


class AuthorityConflictResolutionRequest(BaseModel):
    resolution: str
    note: str = Field(min_length=1, max_length=4000)


class PermissionRequestCreate(BaseModel):
    requester_org_id: str
    authority_claim_id: str
    intended_usage: str
    territory: str = "worldwide"
    term_start: Optional[str] = None
    term_end: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class AttributionObligationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    credit_text: Optional[str] = Field(default=None, max_length=2000)
    backlink_required: bool = False
    backlink_url: Optional[str] = Field(default=None, max_length=2048)
    placements: List[str] = Field(default_factory=list, max_length=12)
    metadata_fields: Dict[str, str] = Field(default_factory=dict)


class LicenseObligationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribution: AttributionObligationInput = Field(default_factory=AttributionObligationInput)
    publication_reporting_required: bool = False
    publication_evidence_due_days: Optional[int] = Field(default=None, ge=1, le=3650)
    usage_reporting_frequency: str = "once"


class PermissionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    note: Optional[str] = None
    obligations: Optional[LicenseObligationsInput] = None


class PermissionReviewAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_user_id: Optional[str] = None
    reason: str = Field(min_length=1, max_length=4000)


class PermissionUsageReportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication_url: str = Field(min_length=1, max_length=2048)
    published_at: str
    platform: Optional[str] = Field(default=None, max_length=200)
    declared_credit_text: Optional[str] = Field(default=None, max_length=4000)
    declared_backlink_url: Optional[str] = Field(default=None, max_length=2048)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)


class PermissionComplianceReviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    note: str = Field(min_length=1, max_length=4000)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)


class PermissionLifecycleRequest(BaseModel):
    event_type: str
    reason: str = Field(min_length=1, max_length=4000)
    replacement_receipt_id: Optional[str] = None


class PermissionExpiryRunRequest(BaseModel):
    as_of: Optional[str] = None


class SettlementBeneficiaryInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    identifier: str = Field(min_length=1, max_length=300)
    share_bps: int = Field(gt=0, le=10000)
    beneficiary_org_id: Optional[str] = None


class SettlementCreateRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    minimum_commitment_minor: int = Field(default=0, ge=0)
    minimum_recoupable: bool = True
    royalty_rate_bps: int = Field(default=0, ge=0, le=10000)
    royalty_basis: str = "net_revenue"
    beneficiaries: List[SettlementBeneficiaryInput] = Field(min_length=1)
    terms: Dict[str, Any] = Field(default_factory=dict)
    confirm_immutable_terms: bool = False


class SettlementEntryCreateRequest(BaseModel):
    kind: str
    amount_minor: int = Field(gt=0)
    beneficiary_id: Optional[str] = None
    external_reference: Optional[str] = Field(default=None, max_length=500)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)


class RoyaltyCalculationRequest(BaseModel):
    basis_amount_minor: int = Field(gt=0)
    period_start: str
    period_end: str
    external_reference: str = Field(min_length=1, max_length=500)
    evidence: Dict[str, Any] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class SettlementReconcileRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    evidence: Dict[str, Any] = Field(default_factory=dict)


class CatalogClientCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    external_reference: str = Field(min_length=1, max_length=200)
    contact_email: Optional[str] = Field(default=None, max_length=320)


class CatalogReviewRequest(BaseModel):
    expected_preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class CatalogConflictResolutionRequest(CatalogReviewRequest):
    resolution: str
    note: str = Field(min_length=1, max_length=4000)


class CatalogImportCommitRequest(CatalogReviewRequest):
    confirm_import: bool = False


class CatalogAssignmentCreateRequest(BaseModel):
    client_id: Optional[str] = None
    reason: str = Field(min_length=1, max_length=4000)


class WebhookEndpointCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    events: List[str] = Field(min_length=1, max_length=100)


class WebhookEndpointUpdateRequest(BaseModel):
    url: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    events: Optional[List[str]] = Field(default=None, min_length=1, max_length=100)
    enabled: Optional[bool] = None


class ReceiptVerifyRequest(BaseModel):
    receipt: Dict[str, Any]


class MLCWorkSearchRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    writer_lastname: Optional[str] = Field(default=None, max_length=255)


class MLCRecordingSearchRequest(BaseModel):
    artist: Optional[str] = Field(default=None, max_length=500)
    title: Optional[str] = Field(default=None, max_length=500)
    isrc: Optional[str] = Field(default=None, max_length=32)


class MWLExportRequest(BaseModel):
    work_title: str
    work_identifier: str
    rights_controller_role: str
    iswc: Optional[str] = None
    territory: str = "US"
    rights_type: str = "MechanicalRight"
    use_type: str = "AsPerContract"
    distribution_channel_type: Optional[str] = "Internet"
    right_share_percentage: Decimal = Field(default=Decimal("100"), ge=0, le=100)
    royalty_rate_calculation_type: str = "NegotiatedRoyaltyRate"
    royalty_percentage: Decimal = Field(default=Decimal("100"), ge=0, le=100)
    percentage_type: str = "PercentageOfNetRevenue"
    rejection_reason: str = "DisagreementOverScopeOfLicense"
    confirm_composition_only_scope: bool = False


class DdexAcknowledgementRequest(BaseModel):
    acknowledgement_type: str = "transport"
    status: str
    partner_message_id: Optional[str] = Field(default=None, max_length=255)
    media_type: Optional[str] = Field(default=None, max_length=120)
    payload: Optional[str] = Field(default=None, max_length=262_144)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=255)


def _mwl_terms(req: MWLExportRequest, permission: PermissionRequestRecord) -> MWLTerms:
    return MWLTerms(
        work_title=req.work_title,
        work_identifier=req.work_identifier,
        territory=req.territory,
        iswc=req.iswc,
        rights_type=req.rights_type,
        use_type=req.use_type,
        distribution_channel_type=req.distribution_channel_type,
        right_share_percentage=req.right_share_percentage,
        royalty_rate_calculation_type=req.royalty_rate_calculation_type,
        royalty_percentage=req.royalty_percentage,
        percentage_type=req.percentage_type,
        term_start=permission.term_start,
        term_end=permission.term_end,
    )


def _persist_ddex_exchange(
    db: Session,
    *,
    permission: PermissionRequestRecord,
    message_id: str,
    message_type: str,
    payload: bytes,
    principal: V1Principal,
) -> DdexExchangeRecord:
    row = DdexExchangeRecord(
        permission_request_id=permission.id,
        message_id=message_id,
        standard="MWL",
        profile=MWL_PROFILE,
        message_type=message_type,
        direction="outbound",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_xml=payload.decode("utf-8"),
        validation_status="schema_valid",
        generated_by_user_id=principal.user.id if principal.user else None,
        generated_by_api_credential_id=(
            principal.credential.id if principal.credential else None
        ),
        generated_at=datetime.datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    claim = (
        db.query(AuthorityClaimRecord)
        .filter(AuthorityClaimRecord.id == permission.authority_claim_id)
        .first()
    )
    audit_org_ids = {permission.requester_org_id}
    if claim:
        audit_org_ids.add(claim.org_id)
    for org_id in audit_org_ids:
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=principal,
            action="ddex_exchange.generated",
            resource_type="ddex_exchange",
            resource_id=row.id,
            details={
                "messageId": message_id,
                "messageType": message_type,
                "profile": MWL_PROFILE,
                "payloadSha256": row.payload_sha256,
                "testMessage": not settings.DDEX_LIVE_MESSAGES,
            },
        )
    db.commit()
    db.refresh(row)
    return row


def _validate_rights_policy(contract: Dict[str, Any]) -> Dict[str, Any]:
    normalized = deepcopy(contract)
    policy_version = normalized.get("policyVersion") or "clef.rights-policy.v1"
    matrix = normalized.get("matrix") or {}
    usage = matrix.get("usage") or {}
    restrictions = matrix.get("restrictions") or {}
    required_usage = USAGE_KEYS if policy_version == "clef.rights-policy.v2" else CORE_USAGE_KEYS
    missing_usage = sorted(set(required_usage) - set(usage.keys()))
    missing_restrictions = sorted(set(RESTRICTION_KEYS) - set(restrictions.keys()))
    if missing_usage or missing_restrictions:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Production policies must explicitly declare every category",
                "missingUsage": missing_usage,
                "missingRestrictions": missing_restrictions,
            },
        )
    if any(value not in {"allowed", "requires_approval", "blocked"} for value in usage.values()):
        raise HTTPException(status_code=422, detail="Invalid usage state")
    if any(value not in {"allowed", "conditional", "denied"} for value in restrictions.values()):
        raise HTTPException(status_code=422, detail="Invalid restriction state")
    for key in AI_USAGE_KEYS:
        usage.setdefault(key, "blocked")
    ai_policy = normalized.get("aiPolicy")
    if policy_version == "clef.rights-policy.v2" and not isinstance(ai_policy, dict):
        raise HTTPException(status_code=422, detail="AI policy is required for rights-policy v2")
    if not isinstance(ai_policy, dict):
        ai_policy = default_ai_policy("blocked")
    inputs = ai_policy.get("inputs") or {}
    model_scopes = ai_policy.get("modelScopes") or {}
    limits = ai_policy.get("limits") or {}
    safeguards = ai_policy.get("safeguards") or {}
    missing_ai = {
        "inputs": sorted(set(AI_INPUT_KEYS) - set(inputs.keys())),
        "modelScopes": sorted(set(AI_MODEL_SCOPE_KEYS) - set(model_scopes.keys())),
        "limits": sorted(set(AI_LIMIT_KEYS) - set(limits.keys())),
        "safeguards": sorted(set(AI_SAFEGUARD_KEYS) - set(safeguards.keys())),
    }
    if policy_version == "clef.rights-policy.v2" and any(missing_ai.values()):
        raise HTTPException(status_code=422, detail={"message": "AI policy must declare every dimension", "missingAI": missing_ai})
    fallback_ai = default_ai_policy("blocked")
    for key in AI_INPUT_KEYS:
        inputs.setdefault(key, fallback_ai["inputs"][key])
    for key in AI_MODEL_SCOPE_KEYS:
        model_scopes.setdefault(key, fallback_ai["modelScopes"][key])
    for key in AI_LIMIT_KEYS:
        limits.setdefault(key, None)
    for key in AI_SAFEGUARD_KEYS:
        safeguards.setdefault(key, True)
    if any(value not in {"allowed", "requires_approval", "blocked"} for value in inputs.values()):
        raise HTTPException(status_code=422, detail="Invalid AI input state")
    if any(value not in {"allowed", "requires_approval", "blocked"} for value in model_scopes.values()):
        raise HTTPException(status_code=422, detail="Invalid AI model scope state")
    if any(value is not None and (not isinstance(value, (int, float)) or value < 0) for value in limits.values()):
        raise HTTPException(status_code=422, detail="AI limits must be non-negative numbers or null")
    if any(not isinstance(value, bool) for value in safeguards.values()):
        raise HTTPException(status_code=422, detail="AI safeguard values must be boolean")
    normalized["matrix"] = {"usage": usage, "restrictions": restrictions}
    normalized["aiPolicy"] = {
        "schemaVersion": "clef.ai-policy.v1",
        "inputs": inputs,
        "modelScopes": model_scopes,
        "limits": limits,
        "safeguards": safeguards,
    }
    normalized["policyVersion"] = policy_version
    normalized.setdefault("metadata", {})["simulated"] = False
    return normalized


def _serialize_receipt(row: PermissionReceiptRecord) -> Dict[str, Any]:
    return data_privacy.envelope(row)


def _evaluate_usage_policy(
    contract: RightsContractRecord,
    *,
    intended_usage: str,
    context: Dict[str, Any],
) -> tuple[str, List[str]]:
    state = (contract.effective_matrix or {}).get("usage", {}).get(intended_usage, "blocked")
    reasons = [f"operation:{intended_usage}:{state}"]
    if state == "blocked" or intended_usage not in {"ai_training_recursive", *AI_USAGE_KEYS}:
        return state, reasons

    request_ai = context.get("aiUse")
    if not isinstance(request_ai, dict):
        return "requires_approval", [*reasons, "aiUse:scope_missing"]
    policy_ai = (contract.contract_json or {}).get("aiPolicy") or default_ai_policy("blocked")
    effective = state

    assets = request_ai.get("inputAssets") or []
    if not isinstance(assets, list) or not assets:
        return "requires_approval", [*reasons, "inputAssets:not_declared"]
    unknown_assets = sorted(set(assets) - set(AI_INPUT_KEYS))
    if unknown_assets:
        raise HTTPException(status_code=422, detail={"message": "Unsupported AI input asset", "assets": unknown_assets})
    for asset in assets:
        asset_state = (policy_ai.get("inputs") or {}).get(asset, "blocked")
        reasons.append(f"input:{asset}:{asset_state}")
        if asset_state == "blocked":
            effective = "blocked"
        elif asset_state == "requires_approval" and effective == "allowed":
            effective = "requires_approval"

    model_scope = request_ai.get("modelScope")
    if model_scope not in AI_MODEL_SCOPE_KEYS:
        raise HTTPException(status_code=422, detail="A supported AI model scope is required")
    scope_state = (policy_ai.get("modelScopes") or {}).get(model_scope, "blocked")
    reasons.append(f"modelScope:{model_scope}:{scope_state}")
    if scope_state == "blocked":
        effective = "blocked"
    elif scope_state == "requires_approval" and effective == "allowed":
        effective = "requires_approval"

    requested_limits = {
        "maxSourceDurationSeconds": request_ai.get("sourceDurationSeconds"),
        "maxOutputDurationSeconds": request_ai.get("outputDurationSeconds"),
        "maxLyricCharacters": request_ai.get("lyricCharacters"),
        "sourceRetentionDays": request_ai.get("sourceRetentionDays"),
        "embeddingRetentionDays": request_ai.get("embeddingRetentionDays"),
    }
    policy_limits = policy_ai.get("limits") or {}
    for key, requested in requested_limits.items():
        if requested is None:
            reasons.append(f"limit:{key}:not_declared")
            if effective == "allowed":
                effective = "requires_approval"
            continue
        if not isinstance(requested, (int, float)) or requested < 0:
            raise HTTPException(status_code=422, detail=f"{key} must be a non-negative number")
        ceiling = policy_limits.get(key)
        if ceiling is None:
            reasons.append(f"limit:{key}:settle_in_license")
            if effective == "allowed":
                effective = "requires_approval"
        elif requested > ceiling:
            reasons.append(f"limit:{key}:exceeds_{ceiling}")
            effective = "blocked"
        else:
            reasons.append(f"limit:{key}:within_{ceiling}")
    accepted_safeguards = request_ai.get("acceptedSafeguards") or []
    if not isinstance(accepted_safeguards, list):
        raise HTTPException(status_code=422, detail="Accepted AI safeguards must be a list")
    unknown_safeguards = sorted(set(accepted_safeguards) - set(AI_SAFEGUARD_KEYS))
    if unknown_safeguards:
        raise HTTPException(status_code=422, detail={"message": "Unsupported AI safeguard", "safeguards": unknown_safeguards})
    for safeguard, required in (policy_ai.get("safeguards") or {}).items():
        if required and safeguard not in accepted_safeguards:
            reasons.append(f"safeguard:{safeguard}:not_accepted")
            effective = "blocked"
        elif required:
            reasons.append(f"safeguard:{safeguard}:accepted")
    return effective, reasons


def _evaluate_permission_policy(
    contract: RightsContractRecord,
    *,
    intended_usage: str,
    context: Dict[str, Any],
) -> tuple[str, List[str]]:
    categories = context.get("restrictionCategories")
    declared = categories is not None
    if declared and (
        not isinstance(categories, list)
        or any(not isinstance(key, str) or key not in RESTRICTION_KEYS for key in categories)
    ):
        raise HTTPException(status_code=422, detail="restrictionCategories must list supported content categories")
    applicable = set(categories or [])
    if intended_usage == "ads_political":
        applicable.add("political")
    # Accept legacy boolean declarations, with a positive declaration taking precedence.
    for key in RESTRICTION_KEYS:
        if key in context:
            if not isinstance(context[key], bool):
                raise HTTPException(status_code=422, detail=f"{key} must be a boolean")
            if context[key]:
                applicable.add(key)
    declared = declared or all(key in context for key in RESTRICTION_KEYS)
    restrictions = (contract.effective_matrix or {}).get("restrictions", {})
    restriction_state = "allowed"
    restriction_reasons = []
    for key in sorted(applicable):
        value = restrictions.get(key, "denied")
        restriction_reasons.append(f"restriction:{key}:{value}")
        if value == "denied":
            restriction_state = "blocked"
        elif value == "conditional" and restriction_state == "allowed":
            restriction_state = "requires_approval"
    if not declared and any(value != "allowed" for value in restrictions.values()):
        restriction_reasons.append("restrictions:scope_missing")
        if restriction_state == "allowed":
            restriction_state = "requires_approval"
    state, reasons = _evaluate_usage_policy(contract, intended_usage=intended_usage, context=context)
    severity = {"allowed": 0, "requires_approval": 1, "blocked": 2}
    return max((state, restriction_state), key=severity.__getitem__), [*reasons, *restriction_reasons]


def _territory_codes(value: str) -> set[str]:
    normalized = value.strip().lower()
    if normalized in {"worldwide", "world", "global", "*"}:
        return {"worldwide"}
    codes = [code.strip().upper() for code in value.split(",")]
    if not codes or any(not re.fullmatch(r"[A-Z]{2}", code) for code in codes):
        raise HTTPException(status_code=422, detail="Use two-letter country codes separated by commas, or worldwide")
    return set(codes)


def _checked_permission_policy(
    claim: AuthorityClaimRecord,
    contract: RightsContractRecord,
    *,
    intended_usage: str,
    territory: str,
    context: Dict[str, Any],
) -> tuple[str, List[str]]:
    if claim.status != "verified":
        raise HTTPException(status_code=409, detail="A verified authority claim is required")
    requested = _territory_codes(territory)
    authorized = _territory_codes(claim.territory)
    if "worldwide" not in authorized and not requested.issubset(authorized):
        raise HTTPException(status_code=409, detail="Requested territory exceeds the verified authority claim")
    state, reasons = _evaluate_permission_policy(contract, intended_usage=intended_usage, context=context)
    if state == "blocked":
        raise HTTPException(status_code=409, detail={
            "message": "The current published policy blocks this intended usage or scope",
            "policyEvaluation": reasons,
        })
    if state == "allowed" and _policy_requires_exact_attribution(contract, intended_usage=intended_usage):
        state = "requires_approval"
        reasons.append("obligation:attribution:exact_terms_required")
    return state, reasons


ATTRIBUTION_PLACEMENTS = {
    "description",
    "metadata",
    "on_screen",
    "liner_notes",
    "credits_page",
    "other",
}
USAGE_REPORTING_FREQUENCIES = {"once", "monthly", "quarterly", "annual"}
COMPLIANCE_REVIEW_OUTCOMES = {"compliant", "noncompliant", "inconclusive"}


def _normalize_https_url(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be an https URL without credentials or a fragment",
        )
    return normalized


def _policy_requires_exact_attribution(
    contract: RightsContractRecord,
    *,
    intended_usage: str,
) -> bool:
    if intended_usage not in {"ai_training_recursive", *AI_USAGE_KEYS}:
        return False
    safeguards = (((contract.contract_json or {}).get("aiPolicy") or {}).get("safeguards") or {})
    return safeguards.get("attribution") is True


def _empty_license_obligations() -> Dict[str, Any]:
    return {
        "schemaVersion": "clef.license-obligations.v1",
        "attribution": {
            "required": False,
            "creditText": None,
            "backlinkRequired": False,
            "backlinkUrl": None,
            "placements": [],
            "metadataFields": {},
        },
        "publicationReporting": {
            "required": False,
            "evidenceDueDaysAfterPublication": None,
            "frequency": "none",
        },
    }


def _normalize_license_obligations(
    obligations: Optional[LicenseObligationsInput],
    *,
    attribution_required_by_policy: bool,
) -> Dict[str, Any]:
    if obligations is None:
        if attribution_required_by_policy:
            raise HTTPException(
                status_code=422,
                detail="This policy requires exact attribution terms in the approval",
            )
        return _empty_license_obligations()

    attribution = obligations.attribution
    credit_text = (attribution.credit_text or "").strip() or None
    placements = list(
        dict.fromkeys(value.strip().lower() for value in attribution.placements if value.strip())
    )
    unsupported_placements = sorted(set(placements) - ATTRIBUTION_PLACEMENTS)
    if unsupported_placements:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Unsupported attribution placement",
                "placements": unsupported_placements,
            },
        )
    attribution_required = attribution.required or attribution_required_by_policy
    if attribution_required and not credit_text:
        raise HTTPException(status_code=422, detail="Required attribution needs exact credit text")
    if attribution_required and not placements:
        raise HTTPException(status_code=422, detail="Required attribution needs at least one placement")

    backlink_url = None
    if attribution.backlink_url:
        backlink_url = _normalize_https_url(
            attribution.backlink_url,
            field_name="Attribution backlink",
        )
    if attribution.backlink_required and not backlink_url:
        raise HTTPException(status_code=422, detail="A required backlink needs an exact https URL")

    metadata_fields: Dict[str, str] = {}
    if len(attribution.metadata_fields) > 50:
        raise HTTPException(status_code=422, detail="Attribution metadata is limited to 50 fields")
    for raw_key, raw_value in attribution.metadata_fields.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if not key or len(key) > 100 or not value or len(value) > 1000:
            raise HTTPException(
                status_code=422,
                detail="Attribution metadata keys and values must be non-empty and bounded",
            )
        metadata_fields[key] = value

    reporting_required = obligations.publication_reporting_required or attribution_required
    evidence_due_days = obligations.publication_evidence_due_days
    if reporting_required and evidence_due_days is None:
        evidence_due_days = 30
    if not reporting_required and evidence_due_days is not None:
        raise HTTPException(
            status_code=422,
            detail="A publication evidence deadline requires publication reporting",
        )
    frequency = obligations.usage_reporting_frequency.strip().lower()
    if reporting_required and frequency not in USAGE_REPORTING_FREQUENCIES:
        raise HTTPException(
            status_code=422,
            detail="Usage reporting frequency must be once, monthly, quarterly, or annual",
        )
    if not reporting_required:
        frequency = "none"

    return {
        "schemaVersion": "clef.license-obligations.v1",
        "attribution": {
            "required": attribution_required,
            "creditText": credit_text,
            "backlinkRequired": attribution.backlink_required,
            "backlinkUrl": backlink_url,
            "placements": placements,
            "metadataFields": metadata_fields,
        },
        "publicationReporting": {
            "required": reporting_required,
            "evidenceDueDaysAfterPublication": evidence_due_days,
            "frequency": frequency,
        },
    }


def _current_permission_assignment(
    db: Session,
    *,
    permission_id: str,
) -> Optional[PermissionReviewAssignmentRecord]:
    return (
        db.query(PermissionReviewAssignmentRecord)
        .filter(PermissionReviewAssignmentRecord.permission_request_id == permission_id)
        .order_by(
            PermissionReviewAssignmentRecord.created_at.desc(),
            PermissionReviewAssignmentRecord.id.desc(),
        )
        .first()
    )


def _require_assigned_reviewer(
    db: Session,
    *,
    permission_id: str,
    principal: V1Principal,
) -> Optional[PermissionReviewAssignmentRecord]:
    assignment = _current_permission_assignment(db, permission_id=permission_id)
    if not assignment or assignment.action == "cleared":
        return assignment
    if principal.credential:
        raise HTTPException(
            status_code=409,
            detail="This request is assigned to a named human reviewer; clear the assignment before machine action",
        )
    if not principal.user or principal.user.id != assignment.reviewer_user_id:
        raise HTTPException(status_code=403, detail="This request is assigned to another reviewer")
    return assignment


def _permission_request_actor_payload(
    db: Session,
    permission: PermissionRequestRecord,
) -> Dict[str, Any]:
    if permission.requested_by_api_credential_id:
        credential = (
            db.query(ApiCredentialRecord)
            .filter(ApiCredentialRecord.id == permission.requested_by_api_credential_id)
            .first()
        )
        return {
            "type": "api_credential",
            "credentialId": permission.requested_by_api_credential_id,
            "credentialName": credential.name if credential else None,
            "organizationId": permission.requester_org_id,
        }
    if permission.requested_by_peer_node_id:
        return {
            "type": "federated_peer",
            "nodeId": permission.requested_by_peer_node_id,
            "organizationId": permission.requester_org_id,
        }
    return {
        "type": "organization_member",
        "userId": permission.requested_by_user_id,
        "organizationId": permission.requester_org_id,
    }


def _issue_permission_receipt(
    db: Session,
    *,
    permission: PermissionRequestRecord,
    claim: AuthorityClaimRecord,
    contract: RightsContractRecord,
    decision_actor: Dict[str, Any],
) -> PermissionReceiptRecord:
    with _transparency_write_lock(db):
        try:
            return _issue_permission_receipt_locked(
                db,
                permission=permission,
                claim=claim,
                contract=contract,
                decision_actor=decision_actor,
            )
        except Exception:
            db.rollback()
            raise


def _issue_permission_receipt_locked(
    db: Session,
    *,
    permission: PermissionRequestRecord,
    claim: AuthorityClaimRecord,
    contract: RightsContractRecord,
    decision_actor: Dict[str, Any],
) -> PermissionReceiptRecord:
    state, reasons = _checked_permission_policy(
        claim, contract, intended_usage=permission.intended_usage,
        territory=permission.territory, context=permission.context,
    )
    if "restrictions:scope_missing" in reasons:
        raise HTTPException(status_code=409, detail="Declare applicable content categories before approval")
    permission.context = {**permission.context, "policyEvaluation": {"state": state, "reasons": reasons}}
    existing = (
        db.query(PermissionReceiptRecord)
        .filter(
            PermissionReceiptRecord.permission_request_id == permission.id,
            PermissionReceiptRecord.receipt_kind == "grant",
        )
        .first()
    )
    if existing:
        db.commit()
        db.refresh(existing)
        return existing

    authority_org = db.query(OrganizationRecord).filter(OrganizationRecord.id == claim.org_id).first()
    requester_org = db.query(OrganizationRecord).filter(OrganizationRecord.id == permission.requester_org_id).first()
    prior = db.query(PermissionReceiptRecord).order_by(PermissionReceiptRecord.transparency_sequence.desc()).first()
    sequence = 1 if not prior else prior.transparency_sequence + 1
    previous_entry_hash = prior.entry_hash if prior else None
    receipt_id = str(uuid.uuid4())
    issued_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    policy_hash = sha256_hex(canonical_json(contract.contract_json))
    disclosure_plan = data_privacy.plan_disclosure(db, claim.org_id, permission.requester_org_id)
    payload = {
        "disclosure": disclosure_plan.private_manifest(),
        "schemaVersion": SCHEMA_VERSION,
        "receiptId": receipt_id,
        "node": {"id": settings.NODE_ID, "keyId": receipt_signer.key_id},
        "issuedAt": issued_at,
        "status": "permissioned",
        "permission": {
            "requestId": permission.id,
            "workKey": permission.work_key,
            "intendedUsage": permission.intended_usage,
            "territory": permission.territory,
            "termStart": permission.term_start,
            "termEnd": permission.term_end,
            "context": permission.context,
            "licenseObligations": permission.license_obligations or _empty_license_obligations(),
            "requestedBy": _permission_request_actor_payload(db, permission),
        },
        "requester": {"organizationId": requester_org.id, "name": requester_org.name},
        "authority": {
            "claimId": claim.id,
            "organizationId": authority_org.id,
            "organizationName": authority_org.name,
            "rightType": claim.right_type,
            "territory": claim.territory,
            "verificationStatus": claim.status,
            "evidence": claim.evidence,
        },
        "policy": {
            "contractId": contract.id,
            "version": contract.version,
            "hash": policy_hash,
            "snapshot": contract.contract_json,
        },
        "decision": {
            "result": "approved",
            "actor": decision_actor,
            "decidedAt": permission.decided_at.replace(microsecond=0).isoformat() + "Z",
            "note": permission.decision_note,
        },
        "provenance": permission.provenance,
    }
    signed = receipt_signer.sign_receipt(
        payload=payload,
        transparency_sequence=sequence,
        previous_entry_hash=previous_entry_hash,
    )
    row = PermissionReceiptRecord(
        id=receipt_id,
        permission_request_id=permission.id,
        receipt_kind="grant",
        prior_receipt_id=None,
        schema_version=SCHEMA_VERSION,
        node_id=settings.NODE_ID,
        payload=payload,
        payload_hash=signed["proof"]["payloadHash"],
        signature=signed["proof"]["signature"],
        public_key=signed["proof"]["publicKey"],
        key_id=signed["proof"]["keyId"],
        transparency_sequence=sequence,
        previous_entry_hash=previous_entry_hash,
        entry_hash=signed["transparency"]["entryHash"],
        created_at=datetime.datetime.utcnow(),
    )
    db.add(row)
    data_privacy.attach_disclosure(db, row=row, plan=disclosure_plan, signer=receipt_signer)
    db.commit()
    db.refresh(row)
    return row


def _issue_permission_lifecycle_receipt(
    db: Session,
    *,
    permission: PermissionRequestRecord,
    claim: AuthorityClaimRecord,
    event_type: str,
    previous_status: str,
    resulting_status: str,
    reason: str,
    actor: Dict[str, Any],
    replacement_receipt: Optional[PermissionReceiptRecord] = None,
    effective_at: Optional[datetime.datetime] = None,
) -> PermissionReceiptRecord:
    with _transparency_write_lock(db):
        try:
            return _issue_permission_lifecycle_receipt_locked(
                db,
                permission=permission,
                claim=claim,
                event_type=event_type,
                previous_status=previous_status,
                resulting_status=resulting_status,
                reason=reason,
                actor=actor,
                replacement_receipt=replacement_receipt,
                effective_at=effective_at,
            )
        except Exception:
            db.rollback()
            raise


def _issue_permission_lifecycle_receipt_locked(
    db: Session,
    *,
    permission: PermissionRequestRecord,
    claim: AuthorityClaimRecord,
    event_type: str,
    previous_status: str,
    resulting_status: str,
    reason: str,
    actor: Dict[str, Any],
    replacement_receipt: Optional[PermissionReceiptRecord] = None,
    effective_at: Optional[datetime.datetime] = None,
) -> PermissionReceiptRecord:
    grant = (
        db.query(PermissionReceiptRecord)
        .filter(
            PermissionReceiptRecord.permission_request_id == permission.id,
            PermissionReceiptRecord.receipt_kind == "grant",
        )
        .first()
    )
    if not grant:
        raise HTTPException(status_code=409, detail="An issued permission receipt is required")
    prior = (
        db.query(PermissionReceiptRecord)
        .filter(PermissionReceiptRecord.permission_request_id == permission.id)
        .order_by(PermissionReceiptRecord.transparency_sequence.desc())
        .first()
    )
    transparency_prior = (
        db.query(PermissionReceiptRecord)
        .order_by(PermissionReceiptRecord.transparency_sequence.desc())
        .first()
    )
    sequence = 1 if not transparency_prior else transparency_prior.transparency_sequence + 1
    previous_entry_hash = transparency_prior.entry_hash if transparency_prior else None
    authority_org = db.query(OrganizationRecord).filter(OrganizationRecord.id == claim.org_id).first()
    requester_org = db.query(OrganizationRecord).filter(OrganizationRecord.id == permission.requester_org_id).first()
    receipt_id = str(uuid.uuid4())
    issued_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    event_effective_at = (effective_at or datetime.datetime.utcnow()).replace(microsecond=0).isoformat() + "Z"
    disclosure_plan = data_privacy.plan_disclosure(db, claim.org_id, permission.requester_org_id)
    payload = {
        "disclosure": disclosure_plan.private_manifest(),
        "schemaVersion": LIFECYCLE_SCHEMA_VERSION,
        "receiptId": receipt_id,
        "node": {"id": settings.NODE_ID, "keyId": receipt_signer.key_id},
        "issuedAt": issued_at,
        "status": resulting_status,
        "event": {
            "type": event_type,
            "reason": reason,
            "actor": actor,
            "effectiveAt": event_effective_at,
            "previousStatus": previous_status,
            "resultingStatus": resulting_status,
            "priorReceiptId": prior.id,
            "priorPayloadHash": prior.payload_hash,
            "originalGrantReceiptId": grant.id,
            "replacementReceiptId": replacement_receipt.id if replacement_receipt else None,
            "replacementPayloadHash": replacement_receipt.payload_hash if replacement_receipt else None,
        },
        "permission": {
            "requestId": permission.id,
            "workKey": permission.work_key,
            "intendedUsage": permission.intended_usage,
            "territory": permission.territory,
            "termStart": permission.term_start,
            "termEnd": permission.term_end,
            "requestedBy": _permission_request_actor_payload(db, permission),
        },
        "requester": {
            "organizationId": requester_org.id,
            "name": requester_org.name,
        },
        "authority": {
            "claimId": claim.id,
            "organizationId": authority_org.id,
            "organizationName": authority_org.name,
            "rightType": claim.right_type,
        },
    }
    signed = receipt_signer.sign_receipt(
        payload=payload,
        transparency_sequence=sequence,
        previous_entry_hash=previous_entry_hash,
    )
    row = PermissionReceiptRecord(
        id=receipt_id,
        permission_request_id=permission.id,
        receipt_kind=event_type,
        prior_receipt_id=prior.id,
        schema_version=LIFECYCLE_SCHEMA_VERSION,
        node_id=settings.NODE_ID,
        payload=payload,
        payload_hash=signed["proof"]["payloadHash"],
        signature=signed["proof"]["signature"],
        public_key=signed["proof"]["publicKey"],
        key_id=signed["proof"]["keyId"],
        transparency_sequence=sequence,
        previous_entry_hash=previous_entry_hash,
        entry_hash=signed["transparency"]["entryHash"],
        created_at=datetime.datetime.utcnow(),
    )
    db.add(row)
    data_privacy.attach_disclosure(db, row=row, plan=disclosure_plan, signer=receipt_signer)
    db.commit()
    db.refresh(row)
    return row


def expire_due_permissions(
    db: Session,
    *,
    as_of: datetime.date,
    actor: Dict[str, Any],
) -> List[PermissionReceiptRecord]:
    candidate_ids = [
        row.id
        for row in (
            db.query(PermissionRequestRecord.id)
            .filter(PermissionRequestRecord.status.in_({"approved", "disputed"}))
            .order_by(PermissionRequestRecord.requested_at.asc())
            .all()
        )
    ]
    receipts: List[PermissionReceiptRecord] = []
    for permission_id in candidate_ids:
        permission = (
            db.query(PermissionRequestRecord)
            .filter(PermissionRequestRecord.id == permission_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if not permission or permission.status not in {"approved", "disputed"}:
            continue
        try:
            term_end = datetime.date.fromisoformat(permission.term_end or "")
        except ValueError:
            continue
        if term_end >= as_of:
            continue
        claim = (
            db.query(AuthorityClaimRecord)
            .filter(AuthorityClaimRecord.id == permission.authority_claim_id)
            .first()
        )
        if not claim:
            continue
        previous_status = permission.status
        effective_at = datetime.datetime.combine(
            term_end + datetime.timedelta(days=1),
            datetime.time.min,
        )
        permission.status = "expired"
        permission.expires_at = effective_at
        for org_id in {permission.requester_org_id, claim.org_id}:
            _record_v1_audit(
                db,
                org_id=org_id,
                actor_type=actor.get("type", "system"),
                actor_user_id=actor.get("userId"),
                action="permission_request.expired",
                resource_type="permission_request",
                resource_id=permission.id,
                details={"termEnd": term_end.isoformat(), "previousStatus": previous_status},
            )
        receipts.append(
            _issue_permission_lifecycle_receipt(
                db,
                permission=permission,
                claim=claim,
                event_type="expiry",
                previous_status=previous_status,
                resulting_status="expired",
                reason=f"Declared license term ended on {term_end.isoformat()}",
                actor=actor,
                effective_at=effective_at,
            )
        )
    return receipts


@app.get("/v1/node/info")
def node_info():
    return {
        "nodeId": settings.NODE_ID,
        "deploymentMode": settings.NODE_DEPLOYMENT_MODE,
        "sandboxGuestAccess": settings.SANDBOX_GUEST_ACCESS,
        "webhookDeliveryEnabled": settings.WEBHOOK_DELIVERY_ENABLED,
        "softwareLicense": "AGPL-3.0-only",
        "sourceCodeUrl": settings.SOURCE_CODE_URL or None,
        "sourceCodeRevision": settings.SOURCE_CODE_REVISION,
        "receiptSchema": SCHEMA_VERSION,
        "keyId": receipt_signer.key_id,
        "publicKey": receipt_signer.public_key_b64,
        "ephemeralSigningKey": receipt_signer.ephemeral,
        "federationEnabled": app.state.federation_config.enabled,
    }


@app.get("/v1/node/readiness", response_model=NodeReadiness)
def node_readiness(
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_operator(user)
    revision = database_revision_state(engine, backend_root=Path(__file__).resolve().parent)
    heartbeat_rows = db.query(ServiceHeartbeatRecord).all()
    heartbeats = {
        row.service_name: HeartbeatSnapshot(
            status=row.status,
            last_attempt_at=row.last_attempt_at,
            last_success_at=row.last_success_at,
            details=row.details or {},
        )
        for row in heartbeat_rows
    }
    ddex_configured = all(
        (
            settings.DDEX_IMPLEMENTATION_LICENSE_CONFIRMED,
            settings.DDEX_DPID,
            settings.DDEX_PARTNER_DPID,
            settings.DDEX_SENDER_NAME,
            settings.DDEX_PARTNER_NAME,
            settings.DDEX_PROFILE,
            settings.DDEX_MWL_XSD_PATH,
        )
    )
    result = evaluate_node_readiness(
        ReadinessInputs(
            deployment_mode=settings.NODE_DEPLOYMENT_MODE,
            database_current=revision.current,
            expected_database_heads=tuple(sorted(revision.expected_heads)),
            current_database_heads=tuple(sorted(revision.current_heads)),
            source_code_url=settings.SOURCE_CODE_URL,
            source_code_revision=settings.SOURCE_CODE_REVISION,
            ephemeral_signing_key=receipt_signer.ephemeral,
            notification_provider=settings.NOTIFICATION_PROVIDER,
            webhook_delivery_enabled=settings.WEBHOOK_DELIVERY_ENABLED,
            expiry_worker_interval_seconds=settings.EXPIRY_WORKER_INTERVAL_SECONDS,
            webhook_worker_interval_seconds=settings.WEBHOOK_WORKER_INTERVAL_SECONDS,
            worker_heartbeats=heartbeats,
            demo_mode=settings.DEMO_MODE,
            mock_integrations=settings.MOCK_INTEGRATIONS,
            development_identity_headers=settings.ALLOW_DEV_IDENTITY_HEADERS,
            development_magic_links=settings.ALLOW_DEV_MAGIC_LINKS,
            mlc_enabled=settings.MLC_ENABLED,
            mlc_configured=bool(
                settings.MLC_USERNAME
                and settings.MLC_PASSWORD
                and settings.MLC_AUTHORIZED_CAPABILITIES
            ),
            ddex_enabled=settings.DDEX_ENABLED,
            ddex_configured=bool(ddex_configured),
            musicbrainz_enabled=settings.MUSICBRAINZ_ENABLED,
            musicbrainz_configured=bool(settings.MUSICBRAINZ_BASE_URL),
        )
    )
    return NodeReadiness.model_validate(result)


def _session_organizations(db: Session, user: UserRecord) -> List[Dict[str, Any]]:
    memberships = (
        db.query(OrganizationMembershipRecord)
        .filter(OrganizationMembershipRecord.user_id == user.id)
        .order_by(OrganizationMembershipRecord.created_at.asc())
        .all()
    )
    organizations: List[Dict[str, Any]] = []
    for membership in memberships:
        org = (
            db.query(OrganizationRecord)
            .filter(OrganizationRecord.id == membership.org_id)
            .first()
        )
        if org:
            profile = org.profile or default_organization_profile()
            organizations.append(
                {
                    "id": org.id,
                    "slug": org.slug,
                    "name": org.name,
                    "role": membership.role,
                    "profile": profile,
                }
            )
    return organizations


@app.get("/v1/session")
def v1_session(
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "displayName": user.display_name,
            "nodeRole": user.role,
        },
        "organizations": _session_organizations(db, user),
    }


@app.get(
    "/v1/organizations/{org_id}/onboarding-status",
    response_model=OrganizationOnboardingStatus,
)
def organization_onboarding_status(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_membership(
        db,
        org_id=org_id,
        user_id=user.id,
        allowed_roles=ORG_DECISION_ROLES,
    )
    organization = db.query(OrganizationRecord).filter(OrganizationRecord.id == org_id).first()
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    organization_type = (organization.profile or {}).get("organizationType", "rights_holder")
    requester_only = organization_type == "requester"

    catalog_count = db.query(CatalogAssetRecord).filter(CatalogAssetRecord.org_id == org_id).count()
    policy_count = db.query(RightsContractRecord).filter(RightsContractRecord.owner_org_id == org_id).count()
    claim_query = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.org_id == org_id)
    claim_count = claim_query.count()
    verified_claim_count = claim_query.filter(AuthorityClaimRecord.status == "verified").count()
    reviewer_count = (
        db.query(OrganizationMembershipRecord)
        .filter(
            OrganizationMembershipRecord.org_id == org_id,
            OrganizationMembershipRecord.role.in_(ORG_DECISION_ROLES),
        )
        .count()
    )
    if requester_only:
        permission_count = (
            db.query(PermissionRequestRecord)
            .filter(PermissionRequestRecord.requester_org_id == org_id)
            .count()
        )
    else:
        permission_count = (
            db.query(PermissionRequestRecord)
            .join(
                AuthorityClaimRecord,
                AuthorityClaimRecord.id == PermissionRequestRecord.authority_claim_id,
            )
            .filter(AuthorityClaimRecord.org_id == org_id)
            .count()
        )
    webhook_count = (
        db.query(WebhookEndpointRecord)
        .filter(WebhookEndpointRecord.org_id == org_id, WebhookEndpointRecord.enabled.is_(True))
        .count()
    )
    settlement_query = db.query(SettlementRecord).filter(
        (SettlementRecord.requester_org_id == org_id)
        | (SettlementRecord.authority_org_id == org_id)
    )
    settlement_count = settlement_query.count()
    reconciliation_count = (
        db.query(SettlementReconciliationRecord)
        .join(SettlementRecord, SettlementRecord.id == SettlementReconciliationRecord.settlement_id)
        .filter(
            (SettlementRecord.requester_org_id == org_id)
            | (SettlementRecord.authority_org_id == org_id)
        )
        .count()
    )

    def milestone(
        key: str,
        status: str,
        summary: str,
        *,
        action: Optional[str] = None,
        count: int = 0,
    ) -> Dict[str, Any]:
        return {"key": key, "status": status, "summary": summary, "action": action, "count": count}

    if requester_only:
        rights_milestones = [
            milestone("catalog", "not_applicable", "Requester organizations do not administer a controlled catalog."),
            milestone("policy", "not_applicable", "Requester organizations cannot publish rights policies."),
            milestone("authority", "not_applicable", "Requester organizations cannot assert authority through onboarding."),
            milestone("reviewer", "not_applicable", "Rights-decision routing is managed by the authority organization."),
        ]
    else:
        authority_status = "complete" if verified_claim_count else ("in_progress" if claim_count else "pending")
        authority_summary = (
            "At least one authority claim has independent evidence verification."
            if verified_claim_count
            else (
                "Authority evidence has been submitted and is awaiting or resolving review."
                if claim_count
                else "No authority claim has been submitted; catalog and policy records alone are not authority."
            )
        )
        rights_milestones = [
            milestone("catalog", "complete" if catalog_count else "pending", "A managed catalog record is present." if catalog_count else "Import or add a catalog record.", action="catalog", count=catalog_count),
            milestone("policy", "complete" if policy_count else "pending", "A versioned rights policy is present." if policy_count else "Publish a conservative policy for a managed work.", action="policies", count=policy_count),
            milestone("authority", authority_status, authority_summary, action="authority", count=verified_claim_count or claim_count),
            milestone("reviewer", "complete" if reviewer_count else "pending", "A decision-capable organization member is configured." if reviewer_count else "Add an owner, administrator, or rights manager for decisions.", action="team", count=reviewer_count),
        ]

    request_summary = (
        "At least one permission request has been submitted."
        if requester_only and permission_count
        else "Submit a permission request against verified authority."
        if requester_only
        else "At least one permission request has reached this organization."
        if permission_count
        else "Publish verified authority before inviting a real permission request."
    )
    webhook_status = (
        "not_applicable"
        if not settings.WEBHOOK_DELIVERY_ENABLED
        else ("complete" if webhook_count else "pending")
    )
    settlement_status = "complete" if reconciliation_count else ("in_progress" if settlement_count else "pending")
    milestones = rights_milestones + [
        milestone("requester", "complete" if permission_count else "pending", request_summary, action="request" if requester_only else "permissions", count=permission_count),
        milestone(
            "webhook",
            webhook_status,
            "Outbound webhook delivery is disabled for this node."
            if webhook_status == "not_applicable"
            else "An enabled partner endpoint is configured."
            if webhook_count
            else "Configure an endpoint only when a partner is ready to receive signed events.",
            action="operations" if webhook_status != "not_applicable" else None,
            count=webhook_count,
        ),
        milestone(
            "settlement",
            settlement_status,
            "A settlement has a current reconciliation record."
            if reconciliation_count
            else "A provisional settlement exists but has not been reconciled."
            if settlement_count
            else "Reconcile payment and beneficiary records after an approved permission is used.",
            action="permissions",
            count=reconciliation_count or settlement_count,
        ),
    ]
    applicable = [row for row in milestones if row["status"] != "not_applicable"]
    completed_count = sum(row["status"] == "complete" for row in applicable)
    return {
        "organizationId": org_id,
        "organizationType": organization_type,
        "complete": bool(applicable) and completed_count == len(applicable),
        "completedCount": completed_count,
        "applicableCount": len(applicable),
        "milestones": milestones,
    }


@app.get("/v1/organizations")
def list_organizations(
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    return {"organizations": _session_organizations(db, user)}


@app.get("/v1/integrations/capabilities")
def integration_capabilities():
    return {
        "mlc": [capability.to_dict() for capability in mlc_adapter.capabilities()],
        "ddex": [capability.to_dict() for capability in ddex_adapter.capabilities()],
    }


def _observed_mlc_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "assertionType": "observed",
        "source": "mlc",
        "sourceScope": mlc_source_scope(),
        "permissionStatus": "unknown",
        "results": results,
    }


def _search_mlc_works(req: MLCWorkSearchRequest) -> Dict[str, Any]:
    title = " ".join((req.title or "").strip().split())
    writer_lastname = " ".join((req.writer_lastname or "").strip().split())
    if not title and not writer_lastname:
        raise HTTPException(status_code=422, detail="title or writer_lastname is required")
    try:
        client = mlc_adapter.require("catalog_lookup")
        results = client.search_songcode(
            title=title or None,
            writer_lastname=writer_lastname or None,
        )
    except UnsupportedCapability as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except MLCQueryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MLCClientError as error:
        logging.getLogger(__name__).warning("MLC work lookup failed: %s", error)
        raise HTTPException(status_code=502, detail="MLC lookup failed") from error
    except Exception as error:
        logging.getLogger(__name__).exception("Unexpected MLC work lookup failure")
        raise HTTPException(status_code=502, detail="MLC lookup failed") from error
    return _observed_mlc_results(results)


def _search_mlc_recordings(req: MLCRecordingSearchRequest) -> Dict[str, Any]:
    artist = " ".join((req.artist or "").strip().split())
    title = " ".join((req.title or "").strip().split())
    isrc = "".join((req.isrc or "").strip().split())
    if not artist and not title and not isrc:
        raise HTTPException(status_code=422, detail="artist, title, or isrc is required")
    try:
        client = mlc_adapter.require("catalog_lookup")
        results = client.search_recordings(
            artist=artist or None,
            title=title or None,
            isrc=isrc or None,
        )
    except UnsupportedCapability as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except MLCQueryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MLCClientError as error:
        logging.getLogger(__name__).warning("MLC recording lookup failed: %s", error)
        raise HTTPException(status_code=502, detail="MLC lookup failed") from error
    except Exception as error:
        logging.getLogger(__name__).exception("Unexpected MLC recording lookup failure")
        raise HTTPException(status_code=502, detail="MLC lookup failed") from error
    return _observed_mlc_results(results)


def _record_mlc_lookup_audit(
    db: Session,
    *,
    org_id: str,
    principal: V1Principal,
    lookup_type: str,
    query: Dict[str, Any],
    result_count: int,
) -> None:
    normalized = {key: value for key, value in query.items() if value}
    _record_v1_audit(
        db,
        org_id=org_id,
        principal=principal,
        action="registry.mlc.lookup",
        resource_type="external_registry_lookup",
        resource_id=None,
        details={
            "lookupType": lookup_type,
            "queryFields": sorted(normalized),
            "querySha256": sha256_hex(canonical_json(normalized)),
            "resultCount": result_count,
            "assertionType": "observed",
            "permissionStatus": "unknown",
        },
    )
    db.commit()


@app.post("/v1/catalog/mlc/search/works", deprecated=True)
def v1_mlc_search_works(
    req: MLCWorkSearchRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    _require_session_user(db, x_session_id)
    return _search_mlc_works(req)


@app.post("/v1/catalog/mlc/search/recordings", deprecated=True)
def v1_mlc_search_recordings(
    req: MLCRecordingSearchRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    _require_session_user(db, x_session_id)
    return _search_mlc_recordings(req)


@app.post("/v1/organizations/{org_id}/catalog/mlc/search/works")
def organization_mlc_search_works(
    org_id: str,
    req: MLCWorkSearchRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="registry:read" if authorization else None,
    )
    _require_principal_organization(
        db,
        principal=principal,
        org_id=org_id,
        required_scope="registry:read" if principal.credential else None,
    )
    result = _search_mlc_works(req)
    _record_mlc_lookup_audit(
        db,
        org_id=org_id,
        principal=principal,
        lookup_type="musical_work",
        query={"title": req.title, "writerLastName": req.writer_lastname},
        result_count=len(result["results"]),
    )
    return result


@app.post("/v1/organizations/{org_id}/catalog/mlc/search/recordings")
def organization_mlc_search_recordings(
    org_id: str,
    req: MLCRecordingSearchRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="registry:read" if authorization else None,
    )
    _require_principal_organization(
        db,
        principal=principal,
        org_id=org_id,
        required_scope="registry:read" if principal.credential else None,
    )
    result = _search_mlc_recordings(req)
    _record_mlc_lookup_audit(
        db,
        org_id=org_id,
        principal=principal,
        lookup_type="recording",
        query={"artist": req.artist, "title": req.title, "isrc": req.isrc},
        result_count=len(result["results"]),
    )
    return result


CATALOG_CSV_COLUMNS = (
    "item_type",
    "title",
    "artist",
    "iswc",
    "isrc",
    "mlc_song_code",
    "territory",
    "client_reference",
    "source_reference",
)
CATALOG_IMPORT_MAX_BYTES = 10 * 1024 * 1024
CATALOG_IMPORT_MAX_ROWS = 10000


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _catalog_identifier(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _catalog_client_reference(value: Any) -> str:
    return _compact_text(value).lower()


def _catalog_normalize_row(source: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    item_type = _compact_text(source.get("item_type")).lower()
    title = _compact_text(source.get("title"))
    artist = _compact_text(source.get("artist")) or None
    iswc = _catalog_identifier(source.get("iswc")) or None
    isrc = _catalog_identifier(source.get("isrc")) or None
    mlc_song_code = _catalog_identifier(source.get("mlc_song_code")) or None
    raw_territory = _compact_text(source.get("territory")) or "worldwide"
    territory = "worldwide" if raw_territory.lower() == "worldwide" else raw_territory.upper() if len(raw_territory) == 2 else raw_territory
    client_reference = _catalog_client_reference(source.get("client_reference")) or None
    source_reference = _compact_text(source.get("source_reference")) or None
    errors: List[str] = []
    if item_type not in {"work", "recording"}:
        errors.append("item_type must be work or recording")
    if not title:
        errors.append("title is required")
    if iswc and not re.fullmatch(r"T\d{10}", iswc):
        errors.append("iswc must contain T followed by 10 digits")
    if isrc and not re.fullmatch(r"[A-Z0-9]{12}", isrc):
        errors.append("isrc must contain 12 letters or digits")
    if mlc_song_code and not re.fullmatch(r"[A-Z0-9]{2,64}", mlc_song_code):
        errors.append("mlc_song_code must contain 2 to 64 letters or digits")
    work_key: Optional[str] = None
    if item_type == "work":
        if iswc:
            work_key = f"iswc:{iswc}"
        elif mlc_song_code:
            work_key = f"mlc:{mlc_song_code}"
        else:
            errors.append("a work requires iswc or mlc_song_code; titles are not durable identifiers")
    elif item_type == "recording":
        if isrc:
            work_key = f"isrc:{isrc}"
        else:
            errors.append("a recording requires isrc")
    normalized = {
        "work_key": work_key,
        "item_type": item_type,
        "title": title,
        "artist": artist,
        "iswc": iswc,
        "isrc": isrc,
        "mlc_song_code": mlc_song_code,
        "territory": territory,
        "client_reference": client_reference,
        "source_reference": source_reference,
    }
    return normalized, errors


def _catalog_asset_matches(asset: CatalogAssetRecord, normalized: Dict[str, Any]) -> bool:
    return all(
        getattr(asset, field) == normalized.get(field)
        for field in (
            "work_key",
            "item_type",
            "title",
            "artist",
            "iswc",
            "isrc",
            "mlc_song_code",
            "territory",
            "source_reference",
        )
    )


def _catalog_latest_asset(db: Session, *, org_id: str, work_key: str) -> Optional[CatalogAssetRecord]:
    return (
        db.query(CatalogAssetRecord)
        .filter(CatalogAssetRecord.org_id == org_id, CatalogAssetRecord.work_key == work_key)
        .order_by(CatalogAssetRecord.version.desc())
        .first()
    )


_LOCAL_CATALOG_LOCK = threading.RLock()


@contextmanager
def _catalog_write_lock(db: Session, org_id: str):
    """All catalog review/commit/assignment writers share one organization lock."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        lock_id = int(hashlib.sha256(f"clef:catalog:{org_id}".encode()).hexdigest()[:15], 16)
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
        yield
    else:
        with _LOCAL_CATALOG_LOCK:
            yield


def _catalog_review_basis(db, org_id, normalized, source):
    latest = _catalog_latest_asset(db, org_id=org_id, work_key=normalized.get("work_key"))
    assignment = _catalog_current_assignment(db, latest.id) if latest else None
    client = db.query(CatalogClientRecord).filter_by(org_id=org_id, external_reference=normalized.get("client_reference")).first() if normalized.get("client_reference") else None
    return hashlib.sha256(canonical_json({"normalized": normalized,
        "assignClient": "client_reference" in source, "incomingClientId": client.id if client else None,
        "latestId": latest.id if latest else None, "assignmentId": assignment.id if assignment else None})).hexdigest()


def _catalog_classify_row(db, org_id, source, clients_by_reference, seen):
    normalized, errors = _catalog_normalize_row(source)
    reference = normalized.get("client_reference")
    if reference and reference not in clients_by_reference:
        errors.append(f"client_reference {reference!r} does not match a managed client")
    status = "invalid" if errors else "ready"
    existing_id = None
    key = normalized.get("work_key")
    if not errors and key:
        if key in seen:
            status = "duplicate_batch" if seen[key] == normalized else "invalid"
            if status == "invalid":
                errors.append("this durable identifier appears earlier in the file with different metadata")
        else:
            seen[key] = normalized
            existing = _catalog_latest_asset(db, org_id=org_id, work_key=key)
            if existing:
                existing_id = existing.id
                assignment = _catalog_current_assignment(db, existing.id)
                incoming = clients_by_reference.get(reference)
                client_matches = "client_reference" not in source or (assignment.client_id if assignment else None) == (incoming.id if incoming else None)
                status = "duplicate_existing" if _catalog_asset_matches(existing, normalized) and client_matches else "conflict"
                if not client_matches:
                    errors.append("Managed client differs from the current assignment; review the change and explicitly resolve this row")
    return dict(normalized_json=normalized, errors=errors, status=status, existing_item_id=existing_id,
                review_basis=_catalog_review_basis(db, org_id, normalized, source))


def _catalog_preview_digest(db, batch):
    if batch.status == "committed" and batch.review_digest:
        return batch.review_digest
    rows = db.query(CatalogImportRowRecord).filter_by(batch_id=batch.id).order_by(CatalogImportRowRecord.row_number).all()
    return hashlib.sha256(canonical_json({"batchId": batch.id, "fileSha256": batch.file_sha256,
        "rows": [{"id": row.id, "basis": row.review_basis, "status": row.status,
                  "resolution": row.resolution, "note": row.resolution_note} for row in rows]})).hexdigest()


def _catalog_check_preview(db, batch, expected):
    if _catalog_preview_digest(db, batch) != expected:
        raise HTTPException(409, "The import preview changed. Reopen it and review the current rows.")


def _serialize_catalog_client(row: CatalogClientRecord) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "externalReference": row.external_reference,
        "contactEmail": row.contact_email,
        "createdAt": row.created_at,
    }


def _catalog_current_assignment(db: Session, asset_id: str) -> Optional[CatalogAssignmentRecord]:
    return (
        db.query(CatalogAssignmentRecord)
        .filter(CatalogAssignmentRecord.catalog_asset_id == asset_id)
        .order_by(CatalogAssignmentRecord.created_at.desc(), CatalogAssignmentRecord.id.desc())
        .first()
    )


def _serialize_catalog_asset(db: Session, row: CatalogAssetRecord) -> Dict[str, Any]:
    assignment = _catalog_current_assignment(db, row.id)
    client = None
    if assignment and assignment.client_id:
        client = db.query(CatalogClientRecord).filter(CatalogClientRecord.id == assignment.client_id).first()
    return {
        "id": row.id,
        "workKey": row.work_key,
        "version": row.version,
        "itemType": row.item_type,
        "title": row.title,
        "artist": row.artist,
        "iswc": row.iswc,
        "isrc": row.isrc,
        "mlcSongCode": row.mlc_song_code,
        "territory": row.territory,
        "sourceReference": row.source_reference,
        "assertionType": "catalog_metadata",
        "authorityStatus": "unverified",
        "client": _serialize_catalog_client(client) if client else None,
        "assignment": {
            "id": assignment.id,
            "reason": assignment.reason,
            "createdAt": assignment.created_at,
        } if assignment else None,
        "createdAt": row.created_at,
    }


def _catalog_batch_summary(db: Session, batch: CatalogImportBatchRecord) -> Dict[str, Any]:
    rows = db.query(CatalogImportRowRecord).filter(CatalogImportRowRecord.batch_id == batch.id).all()
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "total": len(rows),
        "counts": counts,
        "unresolved": counts.get("invalid", 0) + counts.get("conflict", 0),
        "importable": counts.get("ready", 0) + counts.get("resolved_version", 0),
        "skipped": counts.get("duplicate_batch", 0) + counts.get("duplicate_existing", 0) + counts.get("resolved_skip", 0),
    }


def _serialize_catalog_import_row(db: Session, row: CatalogImportRowRecord) -> Dict[str, Any]:
    existing = db.query(CatalogAssetRecord).filter(CatalogAssetRecord.id == row.existing_item_id).first() if row.existing_item_id else None
    return {
        "id": row.id,
        "rowNumber": row.row_number,
        "source": row.source_json,
        "normalized": row.normalized_json,
        "status": row.status,
        "errors": row.errors or [],
        "existingAsset": _serialize_catalog_asset(db, existing) if existing else None,
        "resolution": row.resolution,
        "resolutionNote": row.resolution_note,
        "importedItemId": row.imported_item_id,
    }


def _serialize_catalog_batch(db: Session, batch: CatalogImportBatchRecord, *, include_rows: bool = True) -> Dict[str, Any]:
    rows = (
        db.query(CatalogImportRowRecord)
        .filter(CatalogImportRowRecord.batch_id == batch.id)
        .order_by(CatalogImportRowRecord.row_number.asc())
        .all()
    ) if include_rows else []
    summary = _catalog_batch_summary(db, batch)
    return {
        "id": batch.id,
        "organizationId": batch.org_id,
        "filename": batch.filename,
        "fileSha256": batch.file_sha256,
        "previewDigest": _catalog_preview_digest(db, batch),
        "status": batch.status,
        "summary": summary,
        "rows": [_serialize_catalog_import_row(db, row) for row in rows],
        "createdAt": batch.created_at,
        "committedAt": batch.committed_at,
    }


def _require_catalog_batch(db: Session, *, org_id: str, batch_id: str, lock: bool = False) -> CatalogImportBatchRecord:
    query = db.query(CatalogImportBatchRecord).filter(
        CatalogImportBatchRecord.id == batch_id,
        CatalogImportBatchRecord.org_id == org_id,
    )
    if lock:
        query = query.with_for_update()
    batch = query.first()
    if not batch:
        raise HTTPException(status_code=404, detail="Catalog import batch not found")
    return batch


@app.get("/v1/organizations/{org_id}/catalog/import-template")
def catalog_import_template(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:read" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:read" if principal.credential else None)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CATALOG_CSV_COLUMNS)
    writer.writerow(["work", "Example composition", "Example artist", "T1234567890", "", "", "worldwide", "artist-001", "agreement-2026-001"])
    writer.writerow(["recording", "Example master", "Example artist", "", "USABC2600001", "", "US", "artist-001", "catalog-2026-001"])
    return Response(content=out.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=clef-catalog-template.csv"})


@app.get("/v1/organizations/{org_id}/catalog/clients")
def list_catalog_clients(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:read" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:read" if principal.credential else None)
    rows = db.query(CatalogClientRecord).filter(CatalogClientRecord.org_id == org_id).order_by(CatalogClientRecord.name.asc()).all()
    return {"clients": [_serialize_catalog_client(row) for row in rows]}


@app.post("/v1/organizations/{org_id}/catalog/clients", status_code=201)
def create_catalog_client(
    org_id: str,
    req: CatalogClientCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:write" if principal.credential else None, allowed_roles=ORG_DECISION_ROLES)
    name = _compact_text(req.name)
    external_reference = _catalog_client_reference(req.external_reference)
    contact_email = _compact_text(req.contact_email) or None
    if not name or not external_reference:
        raise HTTPException(status_code=422, detail="Client name and external reference cannot be blank")
    if contact_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact_email):
        raise HTTPException(status_code=422, detail="Client contact email is invalid")
    row = CatalogClientRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=name,
        external_reference=external_reference,
        contact_email=contact_email,
        created_by_user_id=principal.user.id if principal.user else None,
        created_by_api_credential_id=principal.credential.id if principal.credential else None,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(row)
    _record_v1_audit(db, org_id=org_id, principal=principal, action="catalog.client.created", resource_type="catalog_client", resource_id=row.id, details={"externalReference": external_reference, "name": name})
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This client reference already exists in the organization") from error
    db.refresh(row)
    return _serialize_catalog_client(row)


@app.get("/v1/organizations/{org_id}/catalog/assets")
def list_catalog_assets(
    org_id: str,
    include_history: bool = Query(default=False),
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:read" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:read" if principal.credential else None)
    rows = db.query(CatalogAssetRecord).filter(CatalogAssetRecord.org_id == org_id).order_by(CatalogAssetRecord.work_key.asc(), CatalogAssetRecord.version.desc()).all()
    if not include_history:
        latest: Dict[str, CatalogAssetRecord] = {}
        for row in rows:
            latest.setdefault(row.work_key, row)
        rows = list(latest.values())
    return {"assets": [_serialize_catalog_asset(db, row) for row in rows]}


@app.get("/v1/organizations/{org_id}/catalog/imports")
def list_catalog_imports(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:read" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:read" if principal.credential else None)
    rows = db.query(CatalogImportBatchRecord).filter(CatalogImportBatchRecord.org_id == org_id).order_by(CatalogImportBatchRecord.created_at.desc()).limit(100).all()
    return {"imports": [_serialize_catalog_batch(db, row, include_rows=False) for row in rows]}


@app.get("/v1/organizations/{org_id}/catalog/imports/{batch_id}")
def get_catalog_import(
    org_id: str,
    batch_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:read" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:read" if principal.credential else None)
    return _serialize_catalog_batch(db, _require_catalog_batch(db, org_id=org_id, batch_id=batch_id))


@app.post("/v1/organizations/{org_id}/catalog/imports/csv", status_code=201)
async def preview_catalog_import(
    org_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:write" if principal.credential else None, allowed_roles=ORG_DECISION_ROLES)
    raw_bytes = await file.read(CATALOG_IMPORT_MAX_BYTES + 1)
    if len(raw_bytes) > CATALOG_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Catalog CSV exceeds the 10 MB limit")
    if not raw_bytes:
        raise HTTPException(status_code=422, detail="Catalog CSV is empty")
    with _catalog_write_lock(db, org_id):
        file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        existing_batch = db.query(CatalogImportBatchRecord).filter(CatalogImportBatchRecord.org_id == org_id, CatalogImportBatchRecord.file_sha256 == file_sha256).first()
        if existing_batch:
            return _serialize_catalog_batch(db, existing_batch)
        try:
            decoded = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=422, detail="Catalog CSV must be UTF-8 encoded") from error
        reader = csv.DictReader(io.StringIO(decoded))
        headers = [str(header or "").strip().lower() for header in (reader.fieldnames or [])]
        if not headers or len(headers) != len(set(headers)):
            raise HTTPException(status_code=422, detail="Catalog CSV requires a non-empty header with no duplicate columns")
        unknown = sorted(set(headers) - set(CATALOG_CSV_COLUMNS))
        missing = sorted({"item_type", "title"} - set(headers))
        if unknown or missing:
            raise HTTPException(status_code=422, detail={"message": "Catalog CSV headers are invalid", "missing": missing, "unknown": unknown, "allowed": list(CATALOG_CSV_COLUMNS)})
        clients = db.query(CatalogClientRecord).filter(CatalogClientRecord.org_id == org_id).all()
        clients_by_reference = {row.external_reference: row for row in clients}
        batch = CatalogImportBatchRecord(
            id=str(uuid.uuid4()),
            org_id=org_id,
            filename=Path(file.filename or "catalog.csv").name[:255],
            file_sha256=file_sha256,
            status="preview",
            summary={},
            created_by_user_id=principal.user.id if principal.user else None,
            created_by_api_credential_id=principal.credential.id if principal.credential else None,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(batch)
        seen: Dict[str, Dict[str, Any]] = {}
        row_count = 0
        for row_number, raw_row in enumerate(reader, start=2):
            row_count += 1
            if row_count > CATALOG_IMPORT_MAX_ROWS:
                db.rollback()
                raise HTTPException(status_code=413, detail="Catalog CSV exceeds the 10,000 row limit")
            if None in raw_row:
                db.rollback()
                raise HTTPException(status_code=422, detail=f"CSV row {row_number} has more values than the header")
            source = {header: _compact_text(raw_row.get(original)) for header, original in zip(headers, reader.fieldnames or [])}
            classification = _catalog_classify_row(db, org_id, source, clients_by_reference, seen)
            db.add(CatalogImportRowRecord(
                id=str(uuid.uuid4()),
                batch_id=batch.id,
                row_number=row_number,
                source_json=source,
                **classification,
                created_at=datetime.datetime.utcnow(),
            ))
        if row_count == 0:
            db.rollback()
            raise HTTPException(status_code=422, detail="Catalog CSV contains no data rows")
        db.flush()
        batch.summary = _catalog_batch_summary(db, batch)
        _record_v1_audit(db, org_id=org_id, principal=principal, action="catalog.import.previewed", resource_type="catalog_import", resource_id=batch.id, details={"filename": batch.filename, "fileSha256": file_sha256, **batch.summary})
        try:
            db.commit()
        except IntegrityError as error:
            db.rollback()
            existing_batch = db.query(CatalogImportBatchRecord).filter(CatalogImportBatchRecord.org_id == org_id, CatalogImportBatchRecord.file_sha256 == file_sha256).first()
            if existing_batch:
                return _serialize_catalog_batch(db, existing_batch)
            raise HTTPException(status_code=409, detail="Catalog import could not be staged") from error
        db.refresh(batch)
        return _serialize_catalog_batch(db, batch)


@app.post("/v1/organizations/{org_id}/catalog/imports/{batch_id}/refresh")
def refresh_catalog_import(org_id: str, batch_id: str, req: CatalogReviewRequest,
    db: Session = Depends(get_db), x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None)):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:write" if principal.credential else None, allowed_roles=ORG_DECISION_ROLES)
    with _catalog_write_lock(db, org_id):
        batch = _require_catalog_batch(db, org_id=org_id, batch_id=batch_id, lock=True)
        _catalog_check_preview(db, batch, req.expected_preview_digest)
        if batch.status != "preview":
            raise HTTPException(409, "A committed import keeps its original review and history")
        clients = {row.external_reference: row for row in db.query(CatalogClientRecord).filter_by(org_id=org_id).all()}
        rows = db.query(CatalogImportRowRecord).filter_by(batch_id=batch.id).order_by(CatalogImportRowRecord.row_number).all()
        seen = {}
        for row in rows:
            for field, value in _catalog_classify_row(db, org_id, row.source_json, clients, seen).items():
                setattr(row, field, value)
            row.resolution = row.resolution_note = row.resolved_by_user_id = row.resolved_by_api_credential_id = row.resolved_at = None
        db.flush()
        batch.summary = _catalog_batch_summary(db, batch)
        _record_v1_audit(db, org_id=org_id, principal=principal, action="catalog.import.refreshed",
            resource_type="catalog_import", resource_id=batch.id,
            details={"previousPreviewDigest": req.expected_preview_digest, "previewDigest": _catalog_preview_digest(db, batch), **batch.summary})
        db.commit()
        return _serialize_catalog_batch(db, batch)


@app.post("/v1/organizations/{org_id}/catalog/imports/{batch_id}/rows/{row_id}/resolution")
def resolve_catalog_import_conflict(
    org_id: str,
    batch_id: str,
    row_id: str,
    req: CatalogConflictResolutionRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:write" if principal.credential else None, allowed_roles=ORG_DECISION_ROLES)
    with _catalog_write_lock(db, org_id):
        batch = _require_catalog_batch(db, org_id=org_id, batch_id=batch_id, lock=True)
        _catalog_check_preview(db, batch, req.expected_preview_digest)
        if batch.status != "preview":
            raise HTTPException(status_code=409, detail="Only a preview batch can be resolved")
        row = db.query(CatalogImportRowRecord).filter(CatalogImportRowRecord.id == row_id, CatalogImportRowRecord.batch_id == batch.id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Catalog import row not found")
        if row.status != "conflict" or not row.existing_item_id:
            raise HTTPException(status_code=409, detail="Only an existing-catalog conflict can be resolved here")
        if not row.review_basis or row.review_basis != _catalog_review_basis(db, org_id, row.normalized_json, row.source_json):
            raise HTTPException(409, "Catalog or client assignment changed. Refresh preview before resolving this row.")
        resolution = req.resolution.strip().lower()
        if resolution not in {"skip", "new_version"}:
            raise HTTPException(status_code=422, detail="Resolution must be skip or new_version")
        if not _compact_text(req.note):
            raise HTTPException(422, "Record a reason for this catalog decision")
        row.resolution = resolution
        row.resolution_note = _compact_text(req.note)
        row.status = "resolved_skip" if resolution == "skip" else "resolved_version"
        row.resolved_by_user_id = principal.user.id if principal.user else None
        row.resolved_by_api_credential_id = principal.credential.id if principal.credential else None
        row.resolved_at = datetime.datetime.utcnow()
        db.flush()
        batch.summary = _catalog_batch_summary(db, batch)
        _record_v1_audit(db, org_id=org_id, principal=principal, action=f"catalog.import.conflict.{resolution}", resource_type="catalog_import_row", resource_id=row.id, details={"batchId": batch.id, "rowNumber": row.row_number, "workKey": row.normalized_json.get("work_key"), "note": row.resolution_note})
        db.commit()
        return {**_serialize_catalog_import_row(db, row), "previewDigest": _catalog_preview_digest(db, batch)}


@app.post("/v1/organizations/{org_id}/catalog/imports/{batch_id}/commit")
def commit_catalog_import(
    org_id: str,
    batch_id: str,
    req: CatalogImportCommitRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:write" if principal.credential else None, allowed_roles=ORG_DECISION_ROLES)
    with _catalog_write_lock(db, org_id):
        if not req.confirm_import:
            raise HTTPException(status_code=422, detail="Explicit import confirmation is required")
        batch = _require_catalog_batch(db, org_id=org_id, batch_id=batch_id, lock=True)
        _catalog_check_preview(db, batch, req.expected_preview_digest)
        if batch.status == "committed":
            return _serialize_catalog_batch(db, batch)
        if batch.status != "preview":
            raise HTTPException(status_code=409, detail="Catalog import is not in preview state")
        rows = db.query(CatalogImportRowRecord).filter(CatalogImportRowRecord.batch_id == batch.id).order_by(CatalogImportRowRecord.row_number.asc()).all()
        blockers = [row for row in rows if row.status in {"invalid", "conflict"}]
        if blockers:
            raise HTTPException(status_code=409, detail={"message": "Resolve or correct all invalid and conflicting rows before commit", "rowNumbers": [row.row_number for row in blockers]})
        clients = db.query(CatalogClientRecord).filter(CatalogClientRecord.org_id == org_id).all()
        clients_by_reference = {row.external_reference: row for row in clients}
        # Validate every reviewed row against current state before the first insert.
        # Duplicate rows in this file must observe the same pre-commit catalog.
        for row in rows:
            if row.status == "resolved_skip":
                continue
            if not row.review_basis or row.review_basis != _catalog_review_basis(db, org_id, row.normalized_json, row.source_json):
                raise HTTPException(409, f"Catalog or client assignment changed for row {row.row_number}. Refresh preview and review the changes.")
        batch.review_digest = req.expected_preview_digest
        imported = 0
        for row in rows:
            if row.status not in {"ready", "resolved_version"}:
                continue
            normalized = row.normalized_json
            work_key = normalized["work_key"]
            latest = _catalog_latest_asset(db, org_id=org_id, work_key=work_key)
            if row.status == "ready" and latest:
                db.rollback()
                raise HTTPException(status_code=409, detail=f"Catalog changed after preview for {work_key}; refresh the preview and review the changes")
            if row.status == "resolved_version" and (not latest or latest.id != row.existing_item_id):
                db.rollback()
                raise HTTPException(status_code=409, detail=f"Catalog version changed after conflict resolution for {work_key}; refresh the preview and review the changes")
            client_reference = normalized.get("client_reference")
            client = clients_by_reference.get(client_reference) if client_reference else None
            if latest and "client_reference" not in row.source_json:
                # A missing column leaves the assignment unchanged. An explicit blank
                # cell is an unassignment and follows the conflict-review path above.
                current_assignment = _catalog_current_assignment(db, latest.id)
                client = next((item for item in clients if current_assignment and item.id == current_assignment.client_id), None)
            if client_reference and not client:
                db.rollback()
                raise HTTPException(status_code=409, detail=f"Managed client {client_reference!r} no longer exists")
            asset = CatalogAssetRecord(
                id=str(uuid.uuid4()),
                org_id=org_id,
                work_key=work_key,
                version=(latest.version + 1) if latest else 1,
                item_type=normalized["item_type"],
                title=normalized["title"],
                artist=normalized.get("artist"),
                iswc=normalized.get("iswc"),
                isrc=normalized.get("isrc"),
                mlc_song_code=normalized.get("mlc_song_code"),
                territory=normalized["territory"],
                source_reference=normalized.get("source_reference"),
                metadata_json={"assertionType": "catalog_metadata", "authorityStatus": "unverified", "conflictResolutionNote": row.resolution_note},
                import_batch_id=batch.id,
                import_row_number=row.row_number,
                created_by_user_id=principal.user.id if principal.user else None,
                created_by_api_credential_id=principal.credential.id if principal.credential else None,
                created_at=datetime.datetime.utcnow(),
            )
            db.add(asset)
            db.flush()
            db.add(CatalogAssignmentRecord(
                id=str(uuid.uuid4()),
                catalog_asset_id=asset.id,
                client_id=client.id if client else None,
                reason=f"Catalog import {batch.id}, row {row.row_number}" + (f": {row.resolution_note}" if row.resolution_note else ""),
                created_by_user_id=principal.user.id if principal.user else None,
                created_by_api_credential_id=principal.credential.id if principal.credential else None,
                created_at=datetime.datetime.utcnow(),
            ))
            row.imported_item_id = asset.id
            row.status = "imported"
            imported += 1
        batch.status = "committed"
        batch.committed_by_user_id = principal.user.id if principal.user else None
        batch.committed_by_api_credential_id = principal.credential.id if principal.credential else None
        batch.committed_at = datetime.datetime.utcnow()
        db.flush()
        batch.summary = _catalog_batch_summary(db, batch)
        _record_v1_audit(db, org_id=org_id, principal=principal, action="catalog.import.committed", resource_type="catalog_import", resource_id=batch.id, details={"filename": batch.filename, "imported": imported, **batch.summary})
        try:
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise HTTPException(status_code=409, detail="Catalog changed during commit; refresh the preview and review the changes") from error
        db.refresh(batch)
        return _serialize_catalog_batch(db, batch)


@app.post("/v1/organizations/{org_id}/catalog/assets/{asset_id}/assignment", status_code=201)
def assign_catalog_asset(
    org_id: str,
    asset_id: str,
    req: CatalogAssignmentCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="catalog:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="catalog:write" if principal.credential else None, allowed_roles=ORG_DECISION_ROLES)
    with _catalog_write_lock(db, org_id):
        asset = db.query(CatalogAssetRecord).filter(CatalogAssetRecord.id == asset_id, CatalogAssetRecord.org_id == org_id).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Catalog asset not found")
        latest = _catalog_latest_asset(db, org_id=org_id, work_key=asset.work_key)
        if not latest or latest.id != asset.id:
            raise HTTPException(409, "A newer catalog version exists. Reload the catalog before changing its managed client.")
        if not _compact_text(req.reason):
            raise HTTPException(422, "Record a reason for this client assignment")
        client = None
        if req.client_id:
            client = db.query(CatalogClientRecord).filter(CatalogClientRecord.id == req.client_id, CatalogClientRecord.org_id == org_id).first()
            if not client:
                raise HTTPException(status_code=422, detail="Managed client is not part of this organization")
        current = _catalog_current_assignment(db, asset.id)
        if current and current.client_id == (client.id if client else None):
            raise HTTPException(status_code=409, detail="This is already the current client assignment")
        assignment = CatalogAssignmentRecord(
            id=str(uuid.uuid4()),
            catalog_asset_id=asset.id,
            client_id=client.id if client else None,
            reason=_compact_text(req.reason),
            created_by_user_id=principal.user.id if principal.user else None,
            created_by_api_credential_id=principal.credential.id if principal.credential else None,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(assignment)
        _record_v1_audit(db, org_id=org_id, principal=principal, action="catalog.asset.assigned", resource_type="catalog_asset", resource_id=asset.id, details={"workKey": asset.work_key, "clientId": client.id if client else None, "reason": assignment.reason})
        db.commit()
        return _serialize_catalog_asset(db, asset)


@app.post("/v1/organizations")
def create_organization(
    req: OrganizationCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    slug = req.slug.strip().lower()
    if not slug or not all(char.isalnum() or char in {"-", "_"} for char in slug):
        raise HTTPException(status_code=422, detail="Organization slug must use letters, numbers, hyphens, or underscores")
    if slug.startswith("peer-"):
        raise HTTPException(status_code=422, detail="The peer- prefix is reserved for organizations represented from other nodes")
    if (settings.NODE_DEPLOYMENT_MODE == "public_sandbox" and slug.startswith("connected-example-")
            and user.email.lower() not in settings.NODE_OPERATOR_EMAILS):
        raise HTTPException(status_code=422, detail="connected-example- slugs are reserved for the operator's reference catalog")
    organization_type = req.organization_type.strip().lower()
    if organization_type not in ORGANIZATION_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported organization type")
    controlled_right_types = list(
        dict.fromkeys(
            req.controlled_right_types
            if req.controlled_right_types is not None
            else DEFAULT_CONTROLLED_RIGHTS_BY_ORGANIZATION_TYPE[organization_type]
        )
    )
    if any(right not in RIGHT_TYPES for right in controlled_right_types):
        raise HTTPException(status_code=422, detail="Select only supported controlled rights")
    if organization_type == "requester" and controlled_right_types:
        raise HTTPException(status_code=422, detail="Requester organizations cannot select controlled rights")
    if organization_type != "requester" and not controlled_right_types:
        raise HTTPException(status_code=422, detail="Select at least one supported controlled right")
    if req.ai_policy_preset not in {"review_each_ai_use", "block_all_ai"}:
        raise HTTPException(status_code=422, detail="Unsupported AI policy preset")
    territory = req.default_territory.strip()
    if not territory:
        raise HTTPException(status_code=422, detail="Default territory is required")
    if db.query(OrganizationRecord).filter(OrganizationRecord.slug == slug).first():
        raise HTTPException(status_code=409, detail="Organization slug already exists")
    profile = default_organization_profile(
        organization_type=organization_type,
        default_territory=territory,
        controlled_right_types=controlled_right_types,
        ai_policy_preset=req.ai_policy_preset,
    )
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Organization name is required")
    org = OrganizationRecord(slug=slug, name=name, profile=profile, created_by_user_id=user.id)
    db.add(org)
    db.flush()
    db.add(OrganizationMembershipRecord(org_id=org.id, user_id=user.id, role="owner"))
    _record_v1_audit(
        db,
        org_id=org.id,
        principal=V1Principal(user=user),
        action="organization.created",
        resource_type="organization",
        resource_id=org.id,
        details={
            "slug": org.slug,
            "organizationType": organization_type,
            "controlledRightTypes": controlled_right_types,
        },
    )
    db.commit()
    db.refresh(org)
    return {"id": org.id, "slug": org.slug, "name": org.name, "profile": org.profile}


@app.get("/v1/organizations/{org_id}/members")
def list_organization_members(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_membership(db, org_id=org_id, user_id=user.id)
    rows = (
        db.query(OrganizationMembershipRecord, UserRecord)
        .join(UserRecord, UserRecord.id == OrganizationMembershipRecord.user_id)
        .filter(OrganizationMembershipRecord.org_id == org_id)
        .order_by(OrganizationMembershipRecord.created_at.asc())
        .all()
    )
    return {
        "members": [
            {
                "userId": member.id,
                "email": member.email,
                "displayName": member.display_name,
                "role": membership.role,
                "createdAt": membership.created_at,
            }
            for membership, member in rows
        ]
    }


@app.post("/v1/organizations/{org_id}/members")
def add_organization_member(
    org_id: str,
    req: OrganizationMemberAddRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    actor = _require_session_user(db, x_session_id)
    _require_membership(db, org_id=org_id, user_id=actor.id, allowed_roles=ORG_ADMIN_ROLES)
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A valid member email is required")
    # Anonymous guests could otherwise enroll a real person, including the operator, in a record they control.
    if (settings.NODE_DEPLOYMENT_MODE == "public_sandbox" and actor.email.lower() not in settings.NODE_OPERATOR_EMAILS
            and not email.endswith("@sandbox.invalid")):
        raise HTTPException(status_code=422, detail="Public sandbox members use synthetic @sandbox.invalid addresses")
    role = req.role.strip().lower()
    if role not in {"admin", "rights_manager", "member"}:
        raise HTTPException(status_code=422, detail="Member role must be admin, rights_manager, or member")
    member = db.query(UserRecord).filter(UserRecord.email == email).first()
    if not member:
        member = UserRecord(email=email, display_name=email.split("@", 1)[0], role="member")
        db.add(member)
        db.flush()
    existing = (
        db.query(OrganizationMembershipRecord)
        .filter(OrganizationMembershipRecord.org_id == org_id, OrganizationMembershipRecord.user_id == member.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="This user is already an organization member")
    membership = OrganizationMembershipRecord(org_id=org_id, user_id=member.id, role=role)
    db.add(membership)
    _record_v1_audit(
        db,
        org_id=org_id,
        principal=V1Principal(user=actor),
        action="organization.member.added",
        resource_type="organization_membership",
        resource_id=membership.id,
        details={"memberUserId": member.id, "role": role},
    )
    db.commit()
    db.refresh(membership)
    return {
        "userId": member.id,
        "email": member.email,
        "displayName": member.display_name,
        "role": membership.role,
        "createdAt": membership.created_at,
        "signInUrl": settings.CONSOLE_BASE_URL,
    }


def _serialize_api_credential(row: ApiCredentialRecord) -> Dict[str, Any]:
    now = datetime.datetime.utcnow()
    if row.revoked_at:
        status = "revoked"
    elif row.expires_at <= now:
        status = "expired"
    else:
        status = "active"
    return {
        "id": row.id,
        "orgId": row.org_id,
        "name": row.name,
        "tokenPrefix": row.token_prefix,
        "scopes": row.scopes or [],
        "status": status,
        "createdAt": row.created_at,
        "expiresAt": row.expires_at,
        "lastUsedAt": row.last_used_at,
        "revokedAt": row.revoked_at,
    }


@app.post("/v1/organizations/{org_id}/api-credentials", status_code=201)
def create_api_credential(
    org_id: str,
    req: ApiCredentialCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_membership(db, org_id=org_id, user_id=user.id, allowed_roles=ORG_ADMIN_ROLES)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Credential name is required")
    scopes = list(dict.fromkeys(scope.strip() for scope in req.scopes if scope.strip()))
    unsupported = sorted(set(scopes) - API_CREDENTIAL_SCOPES)
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail={"message": "Unsupported API credential scope", "unsupportedScopes": unsupported},
        )
    if not scopes:
        raise HTTPException(status_code=422, detail="Select at least one API credential scope")
    raw_token = f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(36)}"
    credential = ApiCredentialRecord(
        org_id=org_id,
        name=name,
        token_prefix=raw_token[:20],
        token_sha256=_sha256(raw_token),
        scopes=scopes,
        created_by_user_id=user.id,
        created_at=datetime.datetime.utcnow(),
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=req.expires_in_days),
    )
    db.add(credential)
    db.flush()
    _record_v1_audit(
        db,
        org_id=org_id,
        principal=V1Principal(user=user),
        action="api_credential.created",
        resource_type="api_credential",
        resource_id=credential.id,
        details={
            "name": credential.name,
            "tokenPrefix": credential.token_prefix,
            "scopes": credential.scopes,
            "expiresAt": credential.expires_at.replace(microsecond=0).isoformat() + "Z",
        },
    )
    db.commit()
    db.refresh(credential)
    return {**_serialize_api_credential(credential), "token": raw_token}


@app.get("/v1/organizations/{org_id}/api-credentials")
def list_api_credentials(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_membership(db, org_id=org_id, user_id=user.id, allowed_roles=ORG_ADMIN_ROLES)
    rows = (
        db.query(ApiCredentialRecord)
        .filter(ApiCredentialRecord.org_id == org_id)
        .order_by(ApiCredentialRecord.created_at.desc())
        .all()
    )
    return {
        "availableScopes": sorted(API_CREDENTIAL_SCOPES),
        "credentials": [_serialize_api_credential(row) for row in rows],
    }


@app.delete("/v1/organizations/{org_id}/api-credentials/{credential_id}", status_code=204)
def revoke_api_credential(
    org_id: str,
    credential_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_membership(db, org_id=org_id, user_id=user.id, allowed_roles=ORG_ADMIN_ROLES)
    credential = (
        db.query(ApiCredentialRecord)
        .filter(
            ApiCredentialRecord.id == credential_id,
            ApiCredentialRecord.org_id == org_id,
        )
        .with_for_update()
        .first()
    )
    if not credential:
        raise HTTPException(status_code=404, detail="API credential not found")
    if credential.revoked_at is None:
        credential.revoked_at = datetime.datetime.utcnow()
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=V1Principal(user=user),
            action="api_credential.revoked",
            resource_type="api_credential",
            resource_id=credential.id,
            details={"name": credential.name, "tokenPrefix": credential.token_prefix},
        )
        db.commit()
    return Response(status_code=204)


def _validate_webhook_events(events: List[str]) -> List[str]:
    normalized = list(dict.fromkeys(value.strip() for value in events if value.strip()))
    if not normalized:
        raise HTTPException(status_code=422, detail="Select at least one webhook event")
    if "*" in normalized and len(normalized) > 1:
        raise HTTPException(status_code=422, detail="Use wildcard alone or select individual webhook events")
    unsupported = sorted(set(normalized) - set(SUPPORTED_WEBHOOK_EVENTS) - {"*"})
    if unsupported:
        raise HTTPException(status_code=422, detail={"message": "Unsupported webhook event", "unsupportedEvents": unsupported})
    return normalized


def _require_webhook_delivery_enabled() -> None:
    if not settings.WEBHOOK_DELIVERY_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Webhook partner delivery is disabled for this deployment",
        )


def _serialize_webhook_endpoint(row: WebhookEndpointRecord) -> Dict[str, Any]:
    return {
        "id": row.id,
        "organizationId": row.org_id,
        "url": row.url,
        "events": row.events or [],
        "secretHint": row.secret_hint,
        "enabled": row.enabled,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "disabledAt": row.disabled_at,
    }


def _serialize_webhook_delivery(db: Session, row: WebhookOutboxDeliveryRecord) -> Dict[str, Any]:
    event = db.query(WebhookEventRecord).filter(WebhookEventRecord.id == row.event_id).first()
    attempts = (
        db.query(WebhookAttemptRecord)
        .filter(WebhookAttemptRecord.delivery_id == row.id)
        .order_by(WebhookAttemptRecord.attempt_number.asc())
        .all()
    )
    return {
        "id": row.id,
        "endpointId": row.endpoint_id,
        "eventId": row.event_id,
        "event": event.event if event else None,
        "payload": event.payload if event else None,
        "occurredAt": event.occurred_at if event else None,
        "status": row.status,
        "attemptCount": row.attempt_count,
        "nextAttemptAt": row.next_attempt_at,
        "lastStatusCode": row.last_status_code,
        "lastError": row.last_error,
        "deliveredAt": row.delivered_at,
        "deadLetteredAt": row.dead_lettered_at,
        "createdAt": row.created_at,
        "attempts": [
            {
                "id": attempt.id,
                "attemptNumber": attempt.attempt_number,
                "requestTimestamp": attempt.request_timestamp,
                "outcome": attempt.outcome,
                "statusCode": attempt.status_code,
                "error": attempt.error,
                "durationMs": attempt.duration_ms,
                "createdAt": attempt.created_at,
            }
            for attempt in attempts
        ],
    }


@app.get("/v1/organizations/{org_id}/webhooks/events")
def list_supported_webhook_events(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_webhook_delivery_enabled()
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="webhooks:read" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="webhooks:read" if principal.credential else None)
    return {"events": sorted(SUPPORTED_WEBHOOK_EVENTS), "wildcard": "*"}


@app.get("/v1/organizations/{org_id}/webhooks")
def list_webhook_endpoints(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_webhook_delivery_enabled()
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="webhooks:read" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="webhooks:read" if principal.credential else None, allowed_roles=ORG_ADMIN_ROLES)
    rows = db.query(WebhookEndpointRecord).filter(WebhookEndpointRecord.org_id == org_id).order_by(WebhookEndpointRecord.created_at.desc()).all()
    return {"endpoints": [_serialize_webhook_endpoint(row) for row in rows]}


@app.post("/v1/organizations/{org_id}/webhooks", status_code=201)
def create_webhook_endpoint(
    org_id: str,
    req: WebhookEndpointCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_webhook_delivery_enabled()
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="webhooks:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="webhooks:write" if principal.credential else None, allowed_roles=ORG_ADMIN_ROLES)
    try:
        url = normalize_webhook_url(req.url, production=settings.APP_ENV.lower() in {"staging", "production"})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    events = _validate_webhook_events(req.events)
    endpoint_id = str(uuid.uuid4())
    secret = generate_webhook_secret()
    endpoint = WebhookEndpointRecord(
        id=endpoint_id,
        org_id=org_id,
        url=url,
        events=events,
        secret_ciphertext=webhook_secret_box.encrypt(secret, endpoint_id=endpoint_id),
        secret_hint=secret[-4:],
        enabled=True,
        created_by_user_id=principal.user.id if principal.user else None,
        created_by_api_credential_id=principal.credential.id if principal.credential else None,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
    )
    db.add(endpoint)
    _record_v1_audit(db, org_id=org_id, principal=principal, action="webhook.endpoint.created", resource_type="webhook_endpoint", resource_id=endpoint.id, details={"url": endpoint.url, "events": endpoint.events, "secretHint": endpoint.secret_hint})
    db.commit()
    db.refresh(endpoint)
    return {**_serialize_webhook_endpoint(endpoint), "signingSecret": secret}


@app.patch("/v1/organizations/{org_id}/webhooks/{endpoint_id}")
def update_webhook_endpoint(
    org_id: str,
    endpoint_id: str,
    req: WebhookEndpointUpdateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_webhook_delivery_enabled()
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="webhooks:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="webhooks:write" if principal.credential else None, allowed_roles=ORG_ADMIN_ROLES)
    endpoint = db.query(WebhookEndpointRecord).filter(WebhookEndpointRecord.id == endpoint_id, WebhookEndpointRecord.org_id == org_id).with_for_update().first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    changed: List[str] = []
    if req.url is not None:
        try:
            endpoint.url = normalize_webhook_url(req.url, production=settings.APP_ENV.lower() in {"staging", "production"})
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        changed.append("url")
    if req.events is not None:
        endpoint.events = _validate_webhook_events(req.events)
        changed.append("events")
    if req.enabled is not None and req.enabled != endpoint.enabled:
        endpoint.enabled = req.enabled
        endpoint.disabled_at = None if req.enabled else datetime.datetime.utcnow()
        changed.append("enabled")
    if not changed:
        raise HTTPException(status_code=422, detail="No webhook endpoint change was supplied")
    endpoint.updated_at = datetime.datetime.utcnow()
    _record_v1_audit(db, org_id=org_id, principal=principal, action="webhook.endpoint.updated", resource_type="webhook_endpoint", resource_id=endpoint.id, details={"changed": changed, "enabled": endpoint.enabled})
    db.commit()
    return _serialize_webhook_endpoint(endpoint)


@app.post("/v1/organizations/{org_id}/webhooks/{endpoint_id}/rotate-secret")
def rotate_webhook_secret(
    org_id: str,
    endpoint_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_webhook_delivery_enabled()
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="webhooks:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="webhooks:write" if principal.credential else None, allowed_roles=ORG_ADMIN_ROLES)
    endpoint = db.query(WebhookEndpointRecord).filter(WebhookEndpointRecord.id == endpoint_id, WebhookEndpointRecord.org_id == org_id).with_for_update().first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    secret = generate_webhook_secret()
    endpoint.secret_ciphertext = webhook_secret_box.encrypt(secret, endpoint_id=endpoint.id)
    endpoint.secret_hint = secret[-4:]
    endpoint.updated_at = datetime.datetime.utcnow()
    _record_v1_audit(db, org_id=org_id, principal=principal, action="webhook.endpoint.secret_rotated", resource_type="webhook_endpoint", resource_id=endpoint.id, details={"secretHint": endpoint.secret_hint})
    db.commit()
    return {**_serialize_webhook_endpoint(endpoint), "signingSecret": secret}


@app.post("/v1/organizations/{org_id}/webhooks/{endpoint_id}/test", status_code=201)
def create_webhook_test_delivery(
    org_id: str,
    endpoint_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_webhook_delivery_enabled()
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="webhooks:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="webhooks:write" if principal.credential else None, allowed_roles=ORG_ADMIN_ROLES)
    endpoint = db.query(WebhookEndpointRecord).filter(WebhookEndpointRecord.id == endpoint_id, WebhookEndpointRecord.org_id == org_id, WebhookEndpointRecord.enabled.is_(True)).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Enabled webhook endpoint not found")
    now = datetime.datetime.utcnow()
    event = WebhookEventRecord(id=str(uuid.uuid4()), org_id=org_id, event="webhook.test", payload={"schemaVersion": "clef.webhook-event.v1", "organizationId": org_id, "action": "webhook.test", "resource": {"type": "webhook_endpoint", "id": endpoint.id}, "actor": _principal_actor(principal, organization_id=org_id), "details": {"message": "Clef Rights Node test delivery"}}, occurred_at=now, created_at=now)
    delivery = WebhookOutboxDeliveryRecord(id=str(uuid.uuid4()), endpoint_id=endpoint.id, event_id=event.id, org_id=org_id, status="pending", attempt_count=0, next_attempt_at=now, created_at=now, updated_at=now)
    db.add(event); db.add(delivery)
    _record_v1_audit(db, org_id=org_id, principal=principal, action="webhook.test.queued", resource_type="webhook_delivery", resource_id=delivery.id, details={"endpointId": endpoint.id})
    db.commit()
    return _serialize_webhook_delivery(db, delivery)


@app.get("/v1/organizations/{org_id}/webhook-deliveries")
def list_webhook_deliveries(
    org_id: str,
    endpoint_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_webhook_delivery_enabled()
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="webhooks:read" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="webhooks:read" if principal.credential else None, allowed_roles=ORG_ADMIN_ROLES)
    query = db.query(WebhookOutboxDeliveryRecord).filter(WebhookOutboxDeliveryRecord.org_id == org_id)
    if endpoint_id:
        query = query.filter(WebhookOutboxDeliveryRecord.endpoint_id == endpoint_id)
    rows = query.order_by(WebhookOutboxDeliveryRecord.created_at.desc()).limit(limit).all()
    return {"deliveries": [_serialize_webhook_delivery(db, row) for row in rows]}


@app.post("/v1/organizations/{org_id}/webhook-deliveries/{delivery_id}/retry")
def retry_webhook_delivery(
    org_id: str,
    delivery_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_webhook_delivery_enabled()
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization, required_scope="webhooks:write" if authorization else None)
    _require_principal_organization(db, principal=principal, org_id=org_id, required_scope="webhooks:write" if principal.credential else None, allowed_roles=ORG_ADMIN_ROLES)
    delivery = db.query(WebhookOutboxDeliveryRecord).filter(WebhookOutboxDeliveryRecord.id == delivery_id, WebhookOutboxDeliveryRecord.org_id == org_id).with_for_update().first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Webhook delivery not found")
    if delivery.status not in {"retry", "dead_letter"}:
        raise HTTPException(status_code=409, detail="Only retrying or dead-lettered deliveries can be queued manually")
    delivery.status = "pending"
    delivery.next_attempt_at = datetime.datetime.utcnow()
    delivery.lease_until = None
    delivery.dead_lettered_at = None
    delivery.updated_at = datetime.datetime.utcnow()
    _record_v1_audit(db, org_id=org_id, principal=principal, action="webhook.delivery.retried", resource_type="webhook_delivery", resource_id=delivery.id, details={"endpointId": delivery.endpoint_id, "attemptCount": delivery.attempt_count})
    db.commit()
    return _serialize_webhook_delivery(db, delivery)


def _serialize_audit_event(db: Session, row: AuditEventRecord) -> Dict[str, Any]:
    actor: Dict[str, Any] = {"type": row.actor_type}
    if row.actor_user_id:
        user = db.query(UserRecord).filter(UserRecord.id == row.actor_user_id).first()
        actor.update(
            {
                "userId": row.actor_user_id,
                "email": user.email if user else None,
                "displayName": user.display_name if user else None,
            }
        )
    elif row.actor_api_credential_id:
        credential = (
            db.query(ApiCredentialRecord)
            .filter(ApiCredentialRecord.id == row.actor_api_credential_id)
            .first()
        )
        actor.update(
            {
                "credentialId": row.actor_api_credential_id,
                "credentialName": credential.name if credential else None,
                "tokenPrefix": credential.token_prefix if credential else None,
            }
        )
    org = db.query(OrganizationRecord).filter(OrganizationRecord.id == row.org_id).first() if row.org_id else None
    return {
        "id": row.id,
        "organization": {"id": org.id, "name": org.name} if org else None,
        "actor": actor,
        "action": row.action,
        "resource": {"type": row.resource_type, "id": row.resource_id},
        "details": row.details or {},
        "createdAt": row.created_at,
    }


@app.get("/v1/organizations/{org_id}/audit-events")
def list_organization_audit_events(
    org_id: str,
    action: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="audit:read" if authorization else None,
    )
    _require_principal_organization(
        db,
        principal=principal,
        org_id=org_id,
        required_scope="audit:read" if principal.credential else None,
    )
    query = db.query(AuditEventRecord).filter(AuditEventRecord.org_id == org_id)
    if action:
        query = query.filter(AuditEventRecord.action == action)
    rows = query.order_by(AuditEventRecord.created_at.desc()).limit(limit).all()
    return {"events": [_serialize_audit_event(db, row) for row in rows]}


@app.get("/v1/operator/audit-events")
def list_operator_audit_events(
    org_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_operator(user)
    query = db.query(AuditEventRecord)
    if org_id:
        query = query.filter(AuditEventRecord.org_id == org_id)
    if action:
        query = query.filter(AuditEventRecord.action == action)
    rows = query.order_by(AuditEventRecord.created_at.desc()).limit(limit).all()
    return {"events": [_serialize_audit_event(db, row) for row in rows]}


@app.get("/v1/organizations/{org_id}/rights")
def list_organization_rights(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="rights:read" if authorization else None,
    )
    _require_principal_organization(
        db,
        principal=principal,
        org_id=org_id,
        required_scope="rights:read" if principal.credential else None,
    )
    rows = (
        db.query(RightsContractRecord)
        .filter(RightsContractRecord.owner_org_id == org_id)
        .order_by(RightsContractRecord.updated_at.desc())
        .all()
    )
    return {
        "policies": [
            {
                "id": row.id,
                "orgId": org_id,
                "workKey": row.key,
                "artistName": row.artist,
                "version": row.version,
                "contract": row.contract_json,
                "matrix": row.effective_matrix,
                "updatedAt": row.updated_at,
            }
            for row in rows
        ]
    }


@app.get("/v1/organizations/{org_id}/rights/{work_key:path}")
def get_organization_rights(
    org_id: str,
    work_key: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="rights:read" if authorization else None,
    )
    _require_principal_organization(
        db,
        principal=principal,
        org_id=org_id,
        required_scope="rights:read" if principal.credential else None,
    )
    row = (
        db.query(RightsContractRecord)
        .filter(
            RightsContractRecord.owner_org_id == org_id,
            RightsContractRecord.key == work_key,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Rights policy not found")
    return {
        "id": row.id,
        "orgId": org_id,
        "workKey": row.key,
        "artistName": row.artist,
        "version": row.version,
        "contract": row.contract_json,
        "matrix": row.effective_matrix,
        "updatedAt": row.updated_at,
    }


@app.put("/v1/organizations/{org_id}/rights/{work_key}")
def put_rights_policy(
    org_id: str,
    work_key: str,
    req: RightsPolicyPutRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    with _authority_write_lock(db):
        user = _require_session_user(db, x_session_id)
        _require_membership(db, org_id=org_id, user_id=user.id, allowed_roles=ORG_DECISION_ROLES)
        org = db.query(OrganizationRecord).filter(OrganizationRecord.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        if (org.profile or {}).get("organizationType") == "requester":
            raise HTTPException(status_code=403, detail="Requester organizations cannot publish rights policies")
        contract = _validate_rights_policy(req.contract)
        record = save_contract(
            db,
            key=work_key,
            artist=req.artist_name,
            payload=contract,
            editor=user.id,
            source="organization_policy",
            note=req.note,
            owner_org_id=org_id,
            expected_version=req.expected_version,
            commit=False,
        )
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=V1Principal(user=user),
            action="rights_policy.published",
            resource_type="rights_contract",
            resource_id=record.id,
            details={"workKey": work_key, "version": record.version},
        )
        try:
            db.commit()
        except StaleDataError as error:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"message": "Rights policy changed during this save; reload before retrying"},
            ) from error
        db.refresh(record)
        return {"id": record.id, "orgId": org_id, "workKey": work_key, "version": record.version, "contract": record.contract_json}


def _normalize_authority_evidence(raw: Dict[str, Any]) -> Dict[str, Any]:
    try:
        encoded = canonical_json(raw)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Authority evidence must be JSON-serializable") from error
    if len(encoded) > 16_384:
        raise HTTPException(status_code=413, detail="Authority evidence exceeds the 16 KB limit")

    evidence = deepcopy(raw)
    source = _compact_text(evidence.get("source"))
    reference = _compact_text(
        evidence.get("reference")
        or evidence.get("mlcSongCode")
        or evidence.get("registryId")
    )
    if not source:
        raise HTTPException(status_code=422, detail="Authority evidence source is required")
    if len(source) > 120:
        raise HTTPException(status_code=422, detail="Authority evidence source exceeds 120 characters")
    if not reference:
        raise HTTPException(status_code=422, detail="A registry or document reference is required")
    if len(reference) > 500:
        raise HTTPException(status_code=422, detail="Authority evidence reference exceeds 500 characters")
    evidence["source"] = source
    if "reference" in evidence:
        evidence["reference"] = reference

    if "share" in evidence or "controlledShare" in evidence:
        share = _evidence_share(evidence)
        if share is None:
            raise HTTPException(status_code=422, detail="Controlled share must be between 0 and 100")

    document_sha256 = _compact_text(evidence.get("documentSha256"))
    if document_sha256:
        document_sha256 = document_sha256.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", document_sha256):
            raise HTTPException(status_code=422, detail="Document SHA-256 must contain exactly 64 hexadecimal characters")
        evidence["documentSha256"] = document_sha256
    else:
        evidence.pop("documentSha256", None)

    evidence_uri = _compact_text(evidence.get("evidenceUri"))
    if evidence_uri:
        if len(evidence_uri) > 2_048 or not (evidence_uri.startswith("https://") or evidence_uri.startswith("urn:")):
            raise HTTPException(status_code=422, detail="Evidence location must be an https:// URL or urn: identifier")
        evidence["evidenceUri"] = evidence_uri
    else:
        evidence.pop("evidenceUri", None)
    return evidence


@app.post("/v1/authority-claims")
def create_authority_claim(
    req: AuthorityClaimCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_membership(db, org_id=req.org_id, user_id=user.id, allowed_roles=ORG_DECISION_ROLES)
    if req.right_type not in RIGHT_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported right type")
    org = db.query(OrganizationRecord).filter(OrganizationRecord.id == req.org_id).first()
    controlled_right_types = (org.profile or {}).get("controlledRightTypes", []) if org else []
    if req.right_type not in controlled_right_types:
        raise HTTPException(status_code=403, detail="Right type is outside this organization's declared authority scope")
    if not req.evidence:
        raise HTTPException(status_code=422, detail="Authority evidence is required")
    normalized_evidence = _normalize_authority_evidence(req.evidence)
    contract = (
        db.query(RightsContractRecord)
        .filter(RightsContractRecord.id == req.rights_contract_id, RightsContractRecord.owner_org_id == req.org_id)
        .first()
    )
    if not contract:
        raise HTTPException(status_code=404, detail="Organization rights contract not found")
    claim = AuthorityClaimRecord(
        org_id=req.org_id,
        rights_contract_id=contract.id,
        work_key=contract.key,
        right_type=req.right_type,
        territory=",".join(sorted(_territory_codes(req.territory))),
        status="self_asserted",
        evidence=normalized_evidence,
        asserted_by_user_id=user.id,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return {"id": claim.id, "status": claim.status, "workKey": claim.work_key, "rightType": claim.right_type}


@app.get("/v1/organizations/{org_id}/authority-claims")
def list_organization_authority_claims(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_membership(db, org_id=org_id, user_id=user.id)
    rows = (
        db.query(AuthorityClaimRecord)
        .filter(AuthorityClaimRecord.org_id == org_id)
        .order_by(AuthorityClaimRecord.created_at.desc())
        .all()
    )
    return {
        "claims": [
            {
                "id": row.id,
                "orgId": row.org_id,
                "rightsContractId": row.rights_contract_id,
                "workKey": row.work_key,
                "rightType": row.right_type,
                "territory": row.territory,
                "status": row.status,
                "evidence": row.evidence,
                "createdAt": row.created_at,
                "reviewedAt": row.reviewed_at,
                "verifiedAt": row.verified_at,
                "revokedAt": row.revoked_at,
            }
            for row in rows
        ]
    }


@app.get("/v1/directory/authority-claims")
def directory_authority_claims(
    work_key: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="directory:read" if authorization else None,
    )
    query = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.status == "verified")
    if work_key:
        query = query.filter(AuthorityClaimRecord.work_key == work_key)
    rows = query.order_by(AuthorityClaimRecord.verified_at.desc()).limit(200).all()
    claims = []
    for row in rows:
        org = db.query(OrganizationRecord).filter(OrganizationRecord.id == row.org_id).first()
        contract = (
            db.query(RightsContractRecord)
            .filter(RightsContractRecord.id == row.rights_contract_id)
            .first()
        )
        if org and contract:
            claims.append(
                {
                    "id": row.id,
                    "organization": {"id": org.id, "name": org.name},
                    "workKey": row.work_key,
                    "workTitle": ((contract.contract_json or {}).get("metadata") or {}).get("workTitle"),
                    "artistName": contract.artist,
                    "rightType": row.right_type,
                    "territory": row.territory,
                    "verificationStatus": row.status,
                    "policyVersion": contract.version,
                    "matrix": contract.effective_matrix,
                    "aiPolicy": (contract.contract_json or {}).get("aiPolicy") or default_ai_policy("blocked"),
                }
            )
    return {"claims": claims}


def _territories_overlap(left: str, right: str) -> bool:
    try:
        left_codes, right_codes = _territory_codes(left), _territory_codes(right)
    except HTTPException:
        # Historic ambiguous territories require review rather than bypassing conflicts.
        return True
    return "worldwide" in left_codes or "worldwide" in right_codes or bool(left_codes & right_codes)


def _evidence_share(evidence: Dict[str, Any]) -> Optional[Decimal]:
    raw = evidence.get("share", evidence.get("controlledShare"))
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not value.is_finite() or value < 0 or value > 100:
        return None
    return value


def _authority_conflict_basis(
    candidate: AuthorityClaimRecord,
    existing: AuthorityClaimRecord,
) -> Optional[Dict[str, Any]]:
    if not _territories_overlap(candidate.territory, existing.territory):
        return None
    candidate_evidence = candidate.evidence or {}
    existing_evidence = existing.evidence or {}
    candidate_share = _evidence_share(candidate_evidence)
    existing_share = _evidence_share(existing_evidence)
    candidate_exclusive = candidate_evidence.get("exclusive") is True
    existing_exclusive = existing_evidence.get("exclusive") is True
    reason = None
    total_share = None
    if candidate_exclusive or existing_exclusive:
        reason = "exclusive_authority_overlap"
    elif candidate_share is None or existing_share is None:
        reason = "controlled_share_missing_or_invalid"
    else:
        total_share = candidate_share + existing_share
        if total_share > Decimal("100"):
            reason = "controlled_share_exceeds_100"
    if not reason:
        return None
    return {
        "reason": reason,
        "territories": [candidate.territory, existing.territory],
        "candidateShare": str(candidate_share) if candidate_share is not None else None,
        "existingShare": str(existing_share) if existing_share is not None else None,
        "combinedShare": str(total_share) if total_share is not None else None,
        "candidateExclusive": candidate_exclusive,
        "existingExclusive": existing_exclusive,
    }


def _serialize_authority_conflict(
    db: Session,
    conflict: AuthorityConflictRecord,
) -> Dict[str, Any]:
    claims = {
        row.id: row
        for row in db.query(AuthorityClaimRecord)
        .filter(AuthorityClaimRecord.id.in_({conflict.claim_a_id, conflict.claim_b_id}))
        .all()
    }

    def side(claim_id: str, prior_status: str) -> Dict[str, Any]:
        claim = claims.get(claim_id)
        org = (
            db.query(OrganizationRecord)
            .filter(OrganizationRecord.id == claim.org_id)
            .first()
            if claim
            else None
        )
        return {
            "claimId": claim_id,
            "organization": {"id": org.id, "name": org.name} if org else None,
            "territory": claim.territory if claim else None,
            "status": claim.status if claim else None,
            "priorStatus": prior_status,
            "evidence": claim.evidence if claim else None,
        }

    return {
        "id": conflict.id,
        "workKey": conflict.work_key,
        "rightType": conflict.right_type,
        "status": conflict.status,
        "basis": conflict.basis,
        "claimA": side(conflict.claim_a_id, conflict.claim_a_prior_status),
        "claimB": side(conflict.claim_b_id, conflict.claim_b_prior_status),
        "detectedAt": conflict.detected_at,
        "resolvedAt": conflict.resolved_at,
        "resolution": conflict.resolution,
        "resolutionNote": conflict.resolution_note,
    }


@app.post("/v1/authority-claims/{claim_id}/verify")
def verify_authority_claim(
    claim_id: str,
    req: AuthorityClaimVerifyRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    with _authority_write_lock(db):
        user = _require_session_user(db, x_session_id)
        _require_operator(user)
        claim = (
            db.query(AuthorityClaimRecord)
            .filter(AuthorityClaimRecord.id == claim_id)
            .with_for_update()
            .first()
        )
        if not claim:
            raise HTTPException(status_code=404, detail="Authority claim not found")
        if claim.status == "disputed":
            open_conflicts = (
                db.query(AuthorityConflictRecord)
                .filter(
                    AuthorityConflictRecord.status == "open",
                    (AuthorityConflictRecord.claim_a_id == claim.id)
                    | (AuthorityConflictRecord.claim_b_id == claim.id),
                )
                .all()
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Resolve the open authority conflict before verification",
                    "conflictIds": [row.id for row in open_conflicts],
                },
            )
        if claim.status != "self_asserted":
            raise HTTPException(status_code=409, detail=f"Claim cannot be verified from status {claim.status}")
        existing_claims = (
            db.query(AuthorityClaimRecord)
            .filter(
                AuthorityClaimRecord.id != claim.id,
                AuthorityClaimRecord.org_id != claim.org_id,
                AuthorityClaimRecord.work_key == claim.work_key,
                AuthorityClaimRecord.right_type == claim.right_type,
                AuthorityClaimRecord.status == "verified",
            )
            .with_for_update()
            .all()
        )
        conflicts: List[AuthorityConflictRecord] = []
        for existing in existing_claims:
            basis = _authority_conflict_basis(claim, existing)
            if not basis:
                continue
            claim_a, claim_b = sorted((claim, existing), key=lambda item: item.id)
            conflict = (
                db.query(AuthorityConflictRecord)
                .filter(
                    AuthorityConflictRecord.claim_a_id == claim_a.id,
                    AuthorityConflictRecord.claim_b_id == claim_b.id,
                )
                .first()
            )
            if not conflict:
                conflict = AuthorityConflictRecord(
                    claim_a_id=claim_a.id,
                    claim_b_id=claim_b.id,
                    work_key=claim.work_key,
                    right_type=claim.right_type,
                    basis=basis,
                    status="open",
                    claim_a_prior_status=claim_a.status,
                    claim_b_prior_status=claim_b.status,
                    detected_by_user_id=user.id,
                    detected_at=datetime.datetime.utcnow(),
                )
                db.add(conflict)
                db.flush()
            conflicts.append(conflict)
            existing.status = "disputed"
        if conflicts:
            claim.status = "disputed"
            claim.reviewed_by_user_id = user.id
            claim.reviewed_at = datetime.datetime.utcnow()
            claim.evidence = {**(claim.evidence or {}), "verificationNote": req.evidence_note}
            affected_org_ids = {claim.org_id}
            affected_org_ids.update(existing.org_id for existing in existing_claims if existing.status == "disputed")
            for org_id in affected_org_ids:
                _record_v1_audit(
                    db,
                    org_id=org_id,
                    principal=V1Principal(user=user),
                    actor_type="node_operator",
                    action="authority_claim.conflict_detected",
                    resource_type="authority_claim",
                    resource_id=claim.id,
                    details={"conflictIds": [row.id for row in conflicts], "workKey": claim.work_key},
                )
            db.commit()
            return {
                "id": claim.id,
                "status": claim.status,
                "conflicts": [_serialize_authority_conflict(db, row) for row in conflicts],
            }
        claim.status = "verified"
        claim.reviewed_by_user_id = user.id
        claim.verified_by_user_id = user.id
        claim.reviewed_at = datetime.datetime.utcnow()
        claim.verified_at = datetime.datetime.utcnow()
        claim.evidence = {**(claim.evidence or {}), "verificationNote": req.evidence_note}
        _record_v1_audit(
            db,
            org_id=claim.org_id,
            principal=V1Principal(user=user),
            actor_type="node_operator",
            action="authority_claim.verified",
            resource_type="authority_claim",
            resource_id=claim.id,
            details={"workKey": claim.work_key, "rightType": claim.right_type, "territory": claim.territory},
        )
        db.commit()
        return {"id": claim.id, "status": claim.status, "verifiedAt": claim.verified_at}


@app.post("/v1/authority-claims/{claim_id}/reject")
def reject_authority_claim(
    claim_id: str,
    req: AuthorityClaimVerifyRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    with _authority_write_lock(db):
        user = _require_session_user(db, x_session_id)
        _require_operator(user)
        claim = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.id == claim_id).with_for_update().first()
        if not claim:
            raise HTTPException(status_code=404, detail="Authority claim not found")
        if claim.status != "self_asserted":
            raise HTTPException(status_code=409, detail=f"Claim cannot be rejected from status {claim.status}")
        claim.status = "rejected"
        claim.reviewed_by_user_id = user.id
        claim.reviewed_at = datetime.datetime.utcnow()
        claim.evidence = {**(claim.evidence or {}), "verificationNote": req.evidence_note}
        _record_v1_audit(
            db,
            org_id=claim.org_id,
            principal=V1Principal(user=user),
            actor_type="node_operator",
            action="authority_claim.rejected",
            resource_type="authority_claim",
            resource_id=claim.id,
            details={"workKey": claim.work_key, "rightType": claim.right_type},
        )
        db.commit()
        return {"id": claim.id, "status": claim.status, "reviewedAt": claim.reviewed_at}


@app.get("/v1/operator/authority-claims")
def operator_authority_claims(
    status: Optional[str] = Query(default="self_asserted"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_operator(user)
    query = db.query(AuthorityClaimRecord)
    if status:
        query = query.filter(AuthorityClaimRecord.status == status)
    rows = query.order_by(AuthorityClaimRecord.created_at.asc()).limit(limit).all()
    claims = []
    for row in rows:
        org = db.query(OrganizationRecord).filter(OrganizationRecord.id == row.org_id).first()
        contract = (
            db.query(RightsContractRecord)
            .filter(RightsContractRecord.id == row.rights_contract_id)
            .first()
        )
        claims.append(
            {
                "id": row.id,
                "organization": {"id": org.id, "name": org.name} if org else None,
                "rightsContractId": row.rights_contract_id,
                "workKey": row.work_key,
                "artistName": contract.artist if contract else None,
                "rightType": row.right_type,
                "territory": row.territory,
                "status": row.status,
                "evidence": row.evidence,
                "assertedByUserId": row.asserted_by_user_id,
                "createdAt": row.created_at,
            }
        )
    return {"claims": claims}


@app.get("/v1/operator/authority-conflicts")
def operator_authority_conflicts(
    status: Optional[str] = Query(default="open"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_operator(user)
    query = db.query(AuthorityConflictRecord)
    if status:
        query = query.filter(AuthorityConflictRecord.status == status)
    rows = query.order_by(AuthorityConflictRecord.detected_at.asc()).limit(limit).all()
    return {"conflicts": [_serialize_authority_conflict(db, row) for row in rows]}


def _claim_has_other_open_conflicts(
    db: Session,
    *,
    claim_id: str,
    excluded_conflict_id: str,
) -> bool:
    return (
        db.query(AuthorityConflictRecord.id)
        .filter(
            AuthorityConflictRecord.id != excluded_conflict_id,
            AuthorityConflictRecord.status == "open",
            (AuthorityConflictRecord.claim_a_id == claim_id)
            | (AuthorityConflictRecord.claim_b_id == claim_id),
        )
        .first()
        is not None
    )


@app.post("/v1/operator/authority-conflicts/{conflict_id}/resolve")
def resolve_authority_conflict(
    conflict_id: str,
    req: AuthorityConflictResolutionRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    with _authority_write_lock(db):
        user = _require_session_user(db, x_session_id)
        _require_operator(user)
        conflict = (
            db.query(AuthorityConflictRecord)
            .filter(AuthorityConflictRecord.id == conflict_id)
            .with_for_update()
            .first()
        )
        if not conflict:
            raise HTTPException(status_code=404, detail="Authority conflict not found")
        if conflict.status != "open":
            raise HTTPException(status_code=409, detail="Authority conflict is already resolved")
        resolution = req.resolution.strip().lower()
        if resolution not in {"claim_a", "claim_b", "compatible", "neither"}:
            raise HTTPException(
                status_code=422,
                detail="resolution must be claim_a, claim_b, compatible, or neither",
            )
        claims = {
            row.id: row
            for row in db.query(AuthorityClaimRecord)
            .filter(AuthorityClaimRecord.id.in_({conflict.claim_a_id, conflict.claim_b_id}))
            .with_for_update()
            .all()
        }
        claim_a = claims.get(conflict.claim_a_id)
        claim_b = claims.get(conflict.claim_b_id)
        if not claim_a or not claim_b:
            raise HTTPException(status_code=409, detail="A conflicting authority claim is unavailable")

        conflict.status = "resolved"
        conflict.resolution = resolution
        conflict.resolution_note = req.note.strip()
        conflict.resolved_by_user_id = user.id
        conflict.resolved_at = datetime.datetime.utcnow()
        db.flush()

        def activate(claim: AuthorityClaimRecord) -> None:
            if claim.status in {"rejected", "revoked"}:
                return
            if _claim_has_other_open_conflicts(
                db,
                claim_id=claim.id,
                excluded_conflict_id=conflict.id,
            ):
                claim.status = "disputed"
                return
            claim.status = "verified"
            claim.reviewed_by_user_id = user.id
            claim.verified_by_user_id = user.id
            claim.reviewed_at = datetime.datetime.utcnow()
            claim.verified_at = claim.verified_at or datetime.datetime.utcnow()

        def deactivate(claim: AuthorityClaimRecord, prior_status: str) -> None:
            claim.reviewed_by_user_id = user.id
            claim.reviewed_at = datetime.datetime.utcnow()
            if prior_status == "verified" or claim.verified_at:
                claim.status = "revoked"
                claim.revoked_at = datetime.datetime.utcnow()
            else:
                claim.status = "rejected"

        if resolution == "claim_a":
            activate(claim_a)
            deactivate(claim_b, conflict.claim_b_prior_status)
        elif resolution == "claim_b":
            activate(claim_b)
            deactivate(claim_a, conflict.claim_a_prior_status)
        elif resolution == "compatible":
            activate(claim_a)
            activate(claim_b)
        else:
            deactivate(claim_a, conflict.claim_a_prior_status)
            deactivate(claim_b, conflict.claim_b_prior_status)
        for org_id in {claim_a.org_id, claim_b.org_id}:
            _record_v1_audit(
                db,
                org_id=org_id,
                principal=V1Principal(user=user),
                actor_type="node_operator",
                action="authority_conflict.resolved",
                resource_type="authority_conflict",
                resource_id=conflict.id,
                details={"resolution": resolution, "workKey": conflict.work_key},
            )
        db.commit()
        return _serialize_authority_conflict(db, conflict)


@app.post("/v1/permission-requests")
def create_permission_request(
    req: PermissionRequestCreate,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    with _authority_write_lock(db):
        principal = _require_v1_principal(
            db,
            x_session_id=x_session_id,
            authorization=authorization,
            required_scope="permissions:request" if authorization else None,
        )
        _require_principal_organization(
            db,
            principal=principal,
            org_id=req.requester_org_id,
            required_scope="permissions:request" if principal.credential else None,
        )
        return _submit_permission_request(
            db,
            requester_org_id=req.requester_org_id,
            authority_claim_id=req.authority_claim_id,
            intended_usage=req.intended_usage,
            territory=req.territory,
            term_start=req.term_start,
            term_end=req.term_end,
            context=req.context,
            provenance=req.provenance,
            principal=principal,
        )


def _submit_permission_request(
    db: Session,
    *,
    requester_org_id: str,
    authority_claim_id: str,
    intended_usage: str,
    territory: str,
    term_start: Optional[str],
    term_end: Optional[str],
    context: Dict[str, Any],
    provenance: Dict[str, Any],
    principal: Optional[V1Principal] = None,
    peer_node_id: Optional[str] = None,
    bind_record: Optional[Callable[[PermissionRequestRecord], None]] = None,
) -> Dict[str, Any]:
    """Evaluate and record a request; the caller holds the authority write lock.

    Exactly one requester is named: a local principal or a configured peer node.
    bind_record adds rows that must commit in the same transaction as the request.
    """
    if (principal is None) == (peer_node_id is None):
        raise RuntimeError("A permission request needs exactly one requesting actor")
    if intended_usage not in USAGE_KEYS:
        raise HTTPException(status_code=422, detail="Unsupported intended usage")
    claim = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.id == authority_claim_id).with_for_update().first()
    if not claim or claim.status != "verified":
        raise HTTPException(status_code=409, detail="A verified authority claim is required")
    if not term_start or not term_end:
        raise HTTPException(status_code=422, detail="License start and end dates are required")
    try:
        start_date = datetime.date.fromisoformat(term_start)
        end_date = datetime.date.fromisoformat(term_end)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="License dates must use YYYY-MM-DD") from error
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="License end date cannot precede the start date")
    contract = db.query(RightsContractRecord).filter(RightsContractRecord.id == claim.rights_contract_id).with_for_update().first()
    if not contract:
        raise HTTPException(status_code=409, detail="Authority policy is unavailable")
    policy_state, policy_reasons = _checked_permission_policy(
        claim, contract,
        intended_usage=intended_usage,
        territory=territory,
        context=context,
    )
    request_context = deepcopy(context)
    request_context["policyEvaluation"] = {"state": policy_state, "reasons": policy_reasons}
    permission = PermissionRequestRecord(
        requester_org_id=requester_org_id,
        authority_claim_id=claim.id,
        work_key=claim.work_key,
        intended_usage=intended_usage,
        territory=",".join(sorted(_territory_codes(territory))),
        term_start=term_start,
        term_end=term_end,
        context=request_context,
        provenance=provenance,
        license_obligations=_empty_license_obligations(),
        status="pending",
        requested_by_user_id=principal.user.id if principal and principal.user else None,
        requested_by_api_credential_id=principal.credential.id if principal and principal.credential else None,
        requested_by_peer_node_id=peer_node_id,
        requested_at=datetime.datetime.utcnow(),
    )
    db.add(permission)
    db.flush()
    if bind_record:
        bind_record(permission)
    details: Dict[str, Any] = {
        "authorityClaimId": claim.id,
        "workKey": claim.work_key,
        "intendedUsage": intended_usage,
        "policyState": policy_state,
    }
    if peer_node_id:
        details["peerNodeId"] = peer_node_id
    for org_id in {requester_org_id, claim.org_id}:
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=principal,
            actor_type=None if principal else "federated_peer",
            action="permission_request.created",
            resource_type="permission_request",
            resource_id=permission.id,
            details=details,
        )
    response: Dict[str, Any] = {"id": permission.id, "status": permission.status, "policyState": policy_state}
    if policy_state == "allowed":
        permission.status = "approved"
        permission.decided_at = datetime.datetime.utcnow()
        permission.decision_note = "Automatically approved by the published rights policy"
        for org_id in {permission.requester_org_id, claim.org_id}:
            _record_v1_audit(
                db,
                org_id=org_id,
                actor_type="policy",
                action="permission_request.approved",
                resource_type="permission_request",
                resource_id=permission.id,
                details={"contractId": contract.id, "policyVersion": contract.version},
            )
        receipt = _issue_permission_receipt(
            db,
            permission=permission,
            claim=claim,
            contract=contract,
            decision_actor={"type": "policy", "contractId": contract.id, "version": contract.version},
        )
        response.update({"status": "approved", "receipt": _serialize_receipt(receipt)})
    else:
        db.commit()
        db.refresh(permission)
    return response


@app.post("/v1/permission-requests/{permission_id}/decide")
def decide_permission_request(
    permission_id: str,
    req: PermissionDecisionRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    with _authority_write_lock(db):
        principal = _require_v1_principal(
            db,
            x_session_id=x_session_id,
            authorization=authorization,
            required_scope="permissions:decide" if authorization else None,
        )
        permission = (
            db.query(PermissionRequestRecord)
            .filter(PermissionRequestRecord.id == permission_id)
            .with_for_update()
            .first()
        )
        if not permission:
            raise HTTPException(status_code=404, detail="Permission request not found")
        if permission.status != "pending":
            raise HTTPException(status_code=409, detail=f"Permission request is already {permission.status}")
        claim = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.id == permission.authority_claim_id).with_for_update().first()
        if not claim:
            raise HTTPException(status_code=409, detail="Authority claim is unavailable")
        membership = _require_principal_organization(
            db,
            principal=principal,
            org_id=claim.org_id,
            required_scope="permissions:decide" if principal.credential else None,
            allowed_roles=ORG_DECISION_ROLES,
        )
        assignment = _require_assigned_reviewer(
            db,
            permission_id=permission.id,
            principal=principal,
        )
        decision = req.decision.strip().lower()
        if decision not in {"approved", "rejected"}:
            raise HTTPException(status_code=422, detail="decision must be approved or rejected")
        decision_note = (req.note or "").strip()
        if not decision_note:
            raise HTTPException(status_code=422, detail="A manual decision requires a concrete note")
        if decision == "approved" and (not permission.term_start or not permission.term_end):
            raise HTTPException(status_code=409, detail="A permission request without a declared license term cannot be approved")
        contract = (
            db.query(RightsContractRecord)
            .filter(RightsContractRecord.id == claim.rights_contract_id)
            .with_for_update()
            .first()
        )
        if not contract:
            raise HTTPException(status_code=409, detail="Authority policy is unavailable")
        if decision == "approved":
            _checked_permission_policy(
                claim, contract, intended_usage=permission.intended_usage,
                territory=permission.territory, context=permission.context,
            )
        if decision == "rejected" and req.obligations is not None:
            raise HTTPException(status_code=422, detail="License obligations apply only to an approval")
        obligations = (
            _normalize_license_obligations(
                req.obligations,
                attribution_required_by_policy=_policy_requires_exact_attribution(
                    contract,
                    intended_usage=permission.intended_usage,
                ),
            )
            if decision == "approved"
            else _empty_license_obligations()
        )
        permission.status = decision
        permission.decided_by_user_id = principal.user.id if principal.user else None
        permission.decided_by_api_credential_id = principal.credential.id if principal.credential else None
        permission.decision_note = decision_note
        permission.license_obligations = obligations
        permission.decided_at = datetime.datetime.utcnow()
        for org_id in {permission.requester_org_id, claim.org_id}:
            _record_v1_audit(
                db,
                org_id=org_id,
                principal=principal,
                action=f"permission_request.{decision}",
                resource_type="permission_request",
                resource_id=permission.id,
                details={
                    "workKey": permission.work_key,
                    "notePresent": True,
                    "reviewAssignmentId": assignment.id if assignment else None,
                    "licenseObligationsHash": sha256_hex(canonical_json(obligations)),
                },
            )
        response: Dict[str, Any] = {"id": permission.id, "status": permission.status}
        if decision == "approved":
            receipt = _issue_permission_receipt(
                db,
                permission=permission,
                claim=claim,
                contract=contract,
                decision_actor=_principal_actor(
                    principal,
                    organization_id=claim.org_id,
                    organization_role=membership.role if membership else None,
                ),
            )
            response["receipt"] = _serialize_receipt(receipt)
        else:
            db.commit()
            db.refresh(permission)
        return response


def _stored_permission_actor(
    db: Session,
    *,
    user_id: Optional[str],
    credential_id: Optional[str],
    organization_id: str,
) -> Dict[str, Any]:
    if credential_id:
        credential = (
            db.query(ApiCredentialRecord)
            .filter(ApiCredentialRecord.id == credential_id)
            .first()
        )
        return {
            "type": "api_credential",
            "credentialId": credential_id,
            "credentialName": credential.name if credential else None,
            "organizationId": organization_id,
        }
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first() if user_id else None
    return {
        "type": "organization_member",
        "userId": user_id,
        "email": user.email if user else None,
        "displayName": user.display_name if user else None,
        "organizationId": organization_id,
    }


def _serialize_review_assignment(
    db: Session,
    *,
    assignment: Optional[PermissionReviewAssignmentRecord],
    viewer_org_id: str,
) -> Optional[Dict[str, Any]]:
    if not assignment:
        return None
    payload: Dict[str, Any] = {
        "id": assignment.id,
        "action": assignment.action,
        "createdAt": assignment.created_at,
    }
    if viewer_org_id != assignment.authority_org_id:
        return payload
    reviewer = (
        db.query(UserRecord)
        .filter(UserRecord.id == assignment.reviewer_user_id)
        .first()
        if assignment.reviewer_user_id
        else None
    )
    payload.update(
        {
            "authorityOrganizationId": assignment.authority_org_id,
            "reviewer": (
                {
                    "userId": reviewer.id,
                    "email": reviewer.email,
                    "displayName": reviewer.display_name,
                }
                if reviewer
                else None
            ),
            "reason": assignment.reason,
            "assignedBy": _stored_permission_actor(
                db,
                user_id=assignment.assigned_by_user_id,
                credential_id=assignment.assigned_by_api_credential_id,
                organization_id=assignment.authority_org_id,
            ),
        }
    )
    return payload


def _serialize_compliance_review(
    db: Session,
    *,
    review: PermissionComplianceReviewRecord,
) -> Dict[str, Any]:
    return {
        "id": review.id,
        "outcome": review.outcome,
        "note": review.note,
        "evidence": review.evidence or {},
        "assertionType": "authority_reviewed",
        "effectOnPermission": "none",
        "reviewedBy": _stored_permission_actor(
            db,
            user_id=review.reviewed_by_user_id,
            credential_id=review.reviewed_by_api_credential_id,
            organization_id=review.authority_org_id,
        ),
        "createdAt": review.created_at,
    }


def _serialize_usage_report(
    db: Session,
    *,
    report: PermissionUsageReportRecord,
    obligations: Dict[str, Any],
) -> Dict[str, Any]:
    reviews = (
        db.query(PermissionComplianceReviewRecord)
        .filter(PermissionComplianceReviewRecord.usage_report_id == report.id)
        .order_by(
            PermissionComplianceReviewRecord.created_at.asc(),
            PermissionComplianceReviewRecord.id.asc(),
        )
        .all()
    )
    attribution = (obligations or {}).get("attribution") or {}
    expected_credit = attribution.get("creditText")
    expected_backlink = attribution.get("backlinkUrl")
    expected_metadata = attribution.get("metadataFields") or {}
    publication_reporting = (obligations or {}).get("publicationReporting") or {}
    evidence_due_days = publication_reporting.get("evidenceDueDaysAfterPublication")
    metadata_matches = {
        key: (report.metadata_payload or {}).get(key) == value
        for key, value in expected_metadata.items()
    }
    return {
        "id": report.id,
        "permissionRequestId": report.permission_request_id,
        "publicationUrl": report.publication_url,
        "publishedAt": report.published_at,
        "platform": report.platform,
        "declaredCreditText": report.declared_credit_text,
        "declaredBacklinkUrl": report.declared_backlink_url,
        "metadata": report.metadata_payload or {},
        "evidence": report.evidence or {},
        "assertionType": "requester_reported",
        "effectOnPermission": "none",
        "submittedBy": _stored_permission_actor(
            db,
            user_id=report.submitted_by_user_id,
            credential_id=report.submitted_by_api_credential_id,
            organization_id=report.requester_org_id,
        ),
        "automatedChecks": {
            "creditTextExactMatch": (
                (report.declared_credit_text or "").strip() == expected_credit
                if expected_credit
                else None
            ),
            "backlinkExactMatch": (
                (report.declared_backlink_url or "").strip() == expected_backlink
                if expected_backlink
                else None
            ),
            "metadataExactMatches": metadata_matches,
            "reportedWithinDeadline": (
                report.created_at
                <= report.published_at + datetime.timedelta(days=evidence_due_days)
                if evidence_due_days is not None
                else None
            ),
            "effect": "comparison_only",
        },
        "currentReviewOutcome": reviews[-1].outcome if reviews else "pending",
        "reviews": [
            _serialize_compliance_review(db, review=review) for review in reviews
        ],
        "createdAt": report.created_at,
    }


@app.post("/v1/permission-requests/{permission_id}/review-assignments", status_code=201)
def assign_permission_reviewer(
    permission_id: str,
    req: PermissionReviewAssignmentRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="permissions:assign" if authorization else None,
    )
    permission = (
        db.query(PermissionRequestRecord)
        .filter(PermissionRequestRecord.id == permission_id)
        .with_for_update()
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Permission request not found")
    if permission.status != "pending":
        raise HTTPException(status_code=409, detail="Only a pending request can be assigned")
    assignment_reason = req.reason.strip()
    if not assignment_reason:
        raise HTTPException(status_code=422, detail="Reviewer assignment requires a concrete reason")
    claim = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.id == permission.authority_claim_id).first()
    if not claim:
        raise HTTPException(status_code=409, detail="Permission authority is unavailable")
    _require_principal_organization(
        db,
        principal=principal,
        org_id=claim.org_id,
        required_scope="permissions:assign" if principal.credential else None,
        allowed_roles=ORG_DECISION_ROLES,
    )
    reviewer_user_id = (req.reviewer_user_id or "").strip() or None
    if reviewer_user_id:
        reviewer_membership = (
            db.query(OrganizationMembershipRecord)
            .filter(
                OrganizationMembershipRecord.org_id == claim.org_id,
                OrganizationMembershipRecord.user_id == reviewer_user_id,
                OrganizationMembershipRecord.role.in_(ORG_DECISION_ROLES),
            )
            .first()
        )
        if not reviewer_membership:
            raise HTTPException(
                status_code=422,
                detail="Reviewer must be an owner, administrator, or rights manager in the authority organization",
            )
    assignment = PermissionReviewAssignmentRecord(
        id=str(uuid.uuid4()),
        permission_request_id=permission.id,
        authority_org_id=claim.org_id,
        action="assigned" if reviewer_user_id else "cleared",
        reviewer_user_id=reviewer_user_id,
        reason=assignment_reason,
        assigned_by_user_id=principal.user.id if principal.user else None,
        assigned_by_api_credential_id=principal.credential.id if principal.credential else None,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(assignment)
    db.flush()
    _record_v1_audit(
        db,
        org_id=claim.org_id,
        principal=principal,
        action=(
            "permission_request.reviewer_assigned"
            if reviewer_user_id
            else "permission_request.reviewer_cleared"
        ),
        resource_type="permission_review_assignment",
        resource_id=assignment.id,
        details={
            "permissionRequestId": permission.id,
            "reviewerUserId": reviewer_user_id,
            "reasonPresent": True,
        },
    )
    db.commit()
    db.refresh(assignment)
    return _serialize_review_assignment(
        db,
        assignment=assignment,
        viewer_org_id=claim.org_id,
    )


@app.post("/v1/permission-requests/{permission_id}/usage-reports", status_code=201)
def create_permission_usage_report(
    permission_id: str,
    req: PermissionUsageReportCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="compliance:report" if authorization else None,
    )
    permission = (
        db.query(PermissionRequestRecord)
        .filter(PermissionRequestRecord.id == permission_id)
        .with_for_update()
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Permission request not found")
    _require_principal_organization(
        db,
        principal=principal,
        org_id=permission.requester_org_id,
        required_scope="compliance:report" if principal.credential else None,
    )
    grant = (
        db.query(PermissionReceiptRecord)
        .filter(
            PermissionReceiptRecord.permission_request_id == permission.id,
            PermissionReceiptRecord.receipt_kind == "grant",
        )
        .first()
    )
    if not grant:
        raise HTTPException(status_code=409, detail="Usage can be reported only after a signed grant exists")
    publication_url = _normalize_https_url(req.publication_url, field_name="Publication URL")
    declared_backlink_url = (
        _normalize_https_url(req.declared_backlink_url, field_name="Declared backlink")
        if req.declared_backlink_url
        else None
    )
    try:
        published_at = datetime.datetime.fromisoformat(req.published_at.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="published_at must be an ISO 8601 timestamp") from error
    if published_at.tzinfo is not None:
        published_at = published_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    if published_at > datetime.datetime.utcnow() + datetime.timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="Reported publication cannot be in the future")
    published_date = published_at.date()
    if permission.term_start and published_date < datetime.date.fromisoformat(permission.term_start):
        raise HTTPException(status_code=422, detail="Reported publication predates the licensed term")
    if permission.term_end and published_date > datetime.date.fromisoformat(permission.term_end):
        raise HTTPException(status_code=422, detail="Reported publication falls after the licensed term")
    normalized_payload = {
        "publicationUrl": publication_url,
        "publishedAt": published_at.replace(microsecond=0).isoformat() + "Z",
        "platform": (req.platform or "").strip() or None,
        "declaredCreditText": (req.declared_credit_text or "").strip() or None,
        "declaredBacklinkUrl": declared_backlink_url,
        "metadata": req.metadata,
        "evidence": req.evidence,
    }
    if len(canonical_json(normalized_payload)) > 65536:
        raise HTTPException(status_code=413, detail="Usage-report evidence is limited to 64 KiB")
    idempotency_key = req.idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status_code=422, detail="idempotency_key must not be blank")
    request_hash = sha256_hex(canonical_json(normalized_payload))
    existing = (
        db.query(PermissionUsageReportRecord)
        .filter(
            PermissionUsageReportRecord.permission_request_id == permission.id,
            PermissionUsageReportRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key was already used with different usage evidence")
        return _serialize_usage_report(
            db,
            report=existing,
            obligations=permission.license_obligations or {},
        )
    report = PermissionUsageReportRecord(
        id=str(uuid.uuid4()),
        permission_request_id=permission.id,
        requester_org_id=permission.requester_org_id,
        publication_url=publication_url,
        published_at=published_at,
        platform=normalized_payload["platform"],
        declared_credit_text=normalized_payload["declaredCreditText"],
        declared_backlink_url=declared_backlink_url,
        metadata_payload=req.metadata,
        evidence=req.evidence,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        submitted_by_user_id=principal.user.id if principal.user else None,
        submitted_by_api_credential_id=principal.credential.id if principal.credential else None,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(report)
    db.flush()
    claim = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.id == permission.authority_claim_id).first()
    for org_id in {permission.requester_org_id, claim.org_id}:
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=principal,
            action="permission_usage.reported",
            resource_type="permission_usage_report",
            resource_id=report.id,
            details={
                "permissionRequestId": permission.id,
                "publicationUrlHash": sha256_hex(publication_url.encode("utf-8")),
                "assertionType": "requester_reported",
                "effectOnPermission": "none",
            },
        )
    db.commit()
    db.refresh(report)
    return _serialize_usage_report(
        db,
        report=report,
        obligations=permission.license_obligations or {},
    )


@app.post("/v1/permission-usage-reports/{report_id}/reviews", status_code=201)
def review_permission_usage_report(
    report_id: str,
    req: PermissionComplianceReviewCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="compliance:review" if authorization else None,
    )
    report = (
        db.query(PermissionUsageReportRecord)
        .filter(PermissionUsageReportRecord.id == report_id)
        .with_for_update()
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Usage report not found")
    permission = (
        db.query(PermissionRequestRecord)
        .filter(PermissionRequestRecord.id == report.permission_request_id)
        .first()
    )
    if not permission:
        raise HTTPException(status_code=409, detail="Usage report is not linked to an available permission")
    claim = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.id == permission.authority_claim_id).first()
    if not claim:
        raise HTTPException(status_code=409, detail="Permission authority is unavailable")
    membership = _require_principal_organization(
        db,
        principal=principal,
        org_id=claim.org_id,
        required_scope="compliance:review" if principal.credential else None,
        allowed_roles=ORG_DECISION_ROLES,
    )
    _require_assigned_reviewer(db, permission_id=permission.id, principal=principal)
    outcome = req.outcome.strip().lower()
    if outcome not in COMPLIANCE_REVIEW_OUTCOMES:
        raise HTTPException(status_code=422, detail="outcome must be compliant, noncompliant, or inconclusive")
    review_note = req.note.strip()
    if not review_note:
        raise HTTPException(status_code=422, detail="Compliance review requires a concrete note")
    idempotency_key = req.idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status_code=422, detail="idempotency_key must not be blank")
    normalized_payload = {
        "outcome": outcome,
        "note": review_note,
        "evidence": req.evidence,
    }
    if len(canonical_json(normalized_payload)) > 65536:
        raise HTTPException(status_code=413, detail="Compliance-review evidence is limited to 64 KiB")
    request_hash = sha256_hex(canonical_json(normalized_payload))
    existing = (
        db.query(PermissionComplianceReviewRecord)
        .filter(
            PermissionComplianceReviewRecord.usage_report_id == report.id,
            PermissionComplianceReviewRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key was already used with a different compliance review")
        return _serialize_compliance_review(db, review=existing)
    review = PermissionComplianceReviewRecord(
        id=str(uuid.uuid4()),
        usage_report_id=report.id,
        permission_request_id=permission.id,
        authority_org_id=claim.org_id,
        outcome=outcome,
        note=review_note,
        evidence=req.evidence,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reviewed_by_user_id=principal.user.id if principal.user else None,
        reviewed_by_api_credential_id=principal.credential.id if principal.credential else None,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(review)
    db.flush()
    for org_id in {permission.requester_org_id, claim.org_id}:
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=principal,
            action="permission_usage.reviewed",
            resource_type="permission_compliance_review",
            resource_id=review.id,
            details={
                "permissionRequestId": permission.id,
                "usageReportId": report.id,
                "outcome": outcome,
                "effectOnPermission": "none",
                "reviewerRole": membership.role if membership else None,
            },
        )
    db.commit()
    db.refresh(review)
    return _serialize_compliance_review(db, review=review)


@app.post("/v1/permission-requests/{permission_id}/lifecycle-events")
def create_permission_lifecycle_event(
    permission_id: str,
    req: PermissionLifecycleRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="permissions:lifecycle" if authorization else None,
    )
    permission = (
        db.query(PermissionRequestRecord)
        .filter(PermissionRequestRecord.id == permission_id)
        .with_for_update()
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Permission request not found")
    claim = (
        db.query(AuthorityClaimRecord)
        .filter(AuthorityClaimRecord.id == permission.authority_claim_id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=409, detail="Authority claim is unavailable")

    event_type = req.event_type.strip().lower()
    if event_type not in {"dispute", "revocation", "correction"}:
        raise HTTPException(
            status_code=422,
            detail="event_type must be dispute, revocation, or correction",
        )
    allowed_from = {
        "dispute": {"approved"},
        "revocation": {"approved", "disputed"},
        "correction": {"approved", "disputed"},
    }
    if permission.status not in allowed_from[event_type]:
        raise HTTPException(
            status_code=409,
            detail=f"A {event_type} cannot be recorded from status {permission.status}",
        )

    requester_membership = None
    authority_membership = None
    if principal.user:
        requester_membership = (
            db.query(OrganizationMembershipRecord)
            .filter(
                OrganizationMembershipRecord.org_id == permission.requester_org_id,
                OrganizationMembershipRecord.user_id == principal.user.id,
            )
            .first()
        )
        authority_membership = (
            db.query(OrganizationMembershipRecord)
            .filter(
                OrganizationMembershipRecord.org_id == claim.org_id,
                OrganizationMembershipRecord.user_id == principal.user.id,
            )
            .first()
        )
    if event_type == "dispute":
        membership = authority_membership or requester_membership
        if principal.credential:
            if principal.credential.org_id not in {permission.requester_org_id, claim.org_id}:
                raise HTTPException(status_code=403, detail="API credential is not a party to this permission")
        elif not membership:
            raise HTTPException(status_code=403, detail="A party to the permission is required")
    else:
        membership = _require_principal_organization(
            db,
            principal=principal,
            org_id=claim.org_id,
            required_scope="permissions:lifecycle" if principal.credential else None,
            allowed_roles=ORG_DECISION_ROLES,
        )

    replacement_receipt = None
    if event_type == "correction":
        if not req.replacement_receipt_id:
            raise HTTPException(
                status_code=422,
                detail="A correction requires replacement_receipt_id",
            )
        replacement_receipt = (
            db.query(PermissionReceiptRecord)
            .filter(
                PermissionReceiptRecord.id == req.replacement_receipt_id,
                PermissionReceiptRecord.receipt_kind == "grant",
            )
            .first()
        )
        if not replacement_receipt or replacement_receipt.permission_request_id == permission.id:
            raise HTTPException(status_code=409, detail="A distinct replacement grant receipt is required")
        replacement_permission = (
            db.query(PermissionRequestRecord)
            .filter(
                PermissionRequestRecord.id == replacement_receipt.permission_request_id,
                PermissionRequestRecord.status == "approved",
            )
            .first()
        )
        replacement_authority = (replacement_receipt.payload or {}).get("authority") or {}
        if (
            not replacement_permission
            or replacement_permission.work_key != permission.work_key
            or replacement_authority.get("organizationId") != claim.org_id
            or replacement_authority.get("rightType") != claim.right_type
        ):
            raise HTTPException(
                status_code=409,
                detail="Replacement receipt must be an active grant for the same work, authority organization, and right",
            )
    elif req.replacement_receipt_id:
        raise HTTPException(
            status_code=422,
            detail="replacement_receipt_id is valid only for a correction",
        )

    previous_status = permission.status
    resulting_status = {
        "dispute": "disputed",
        "revocation": "revoked",
        "correction": "corrected",
    }[event_type]
    permission.status = resulting_status
    if resulting_status == "revoked":
        permission.revoked_at = datetime.datetime.utcnow()
    actor_org_id = principal.credential.org_id if principal.credential else membership.org_id
    actor = _principal_actor(
        principal,
        organization_id=actor_org_id,
        organization_role=membership.role if membership else None,
    )
    for org_id in {permission.requester_org_id, claim.org_id}:
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=principal,
            action=f"permission_request.{resulting_status}",
            resource_type="permission_request",
            resource_id=permission.id,
            details={"eventType": event_type, "previousStatus": previous_status},
        )
    receipt = _issue_permission_lifecycle_receipt(
        db,
        permission=permission,
        claim=claim,
        event_type=event_type,
        previous_status=previous_status,
        resulting_status=resulting_status,
        reason=req.reason.strip(),
        actor=actor,
        replacement_receipt=replacement_receipt,
    )
    return {
        "id": permission.id,
        "status": permission.status,
        "receipt": _serialize_receipt(receipt),
    }


@app.post("/v1/operator/permission-requests/expire-due")
def expire_due_permission_requests(
    req: PermissionExpiryRunRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
):
    user = _require_session_user(db, x_session_id)
    _require_operator(user)
    try:
        as_of = datetime.date.fromisoformat(req.as_of) if req.as_of else datetime.date.today()
    except ValueError as error:
        raise HTTPException(status_code=422, detail="as_of must use YYYY-MM-DD") from error
    receipts = expire_due_permissions(
        db,
        as_of=as_of,
        actor={"type": "node_operator", "userId": user.id, "asOf": as_of.isoformat()},
    )
    return {
        "asOf": as_of.isoformat(),
        "expiredCount": len(receipts),
        "receipts": [
            {
                "receiptId": row.id,
                "permissionRequestId": row.permission_request_id,
                "payloadHash": row.payload_hash,
            }
            for row in receipts
        ],
    }


def _serialize_permission_for_org(
    db: Session,
    *,
    permission: PermissionRequestRecord,
    viewer_org_id: str,
) -> Dict[str, Any]:
    claim = (
        db.query(AuthorityClaimRecord)
        .filter(AuthorityClaimRecord.id == permission.authority_claim_id)
        .first()
    )
    requester_org = (
        db.query(OrganizationRecord)
        .filter(OrganizationRecord.id == permission.requester_org_id)
        .first()
    )
    authority_org = (
        db.query(OrganizationRecord)
        .filter(OrganizationRecord.id == claim.org_id)
        .first()
        if claim
        else None
    )
    receipts = (
        db.query(PermissionReceiptRecord)
        .filter(PermissionReceiptRecord.permission_request_id == permission.id)
        .order_by(PermissionReceiptRecord.transparency_sequence.asc())
        .all()
    )
    grant_receipt = next((row for row in receipts if row.receipt_kind == "grant"), None)
    latest_receipt = receipts[-1] if receipts else None
    contract = (
        db.query(RightsContractRecord)
        .filter(RightsContractRecord.id == claim.rights_contract_id)
        .first()
        if claim
        else None
    )
    directions = []
    if permission.requester_org_id == viewer_org_id:
        directions.append("outbound")
    if claim and claim.org_id == viewer_org_id:
        directions.append("inbound")
    decided_by = None
    if permission.decided_by_api_credential_id:
        decision_credential = (
            db.query(ApiCredentialRecord)
            .filter(ApiCredentialRecord.id == permission.decided_by_api_credential_id)
            .first()
        )
        decided_by = {
            "type": "api_credential",
            "credentialId": permission.decided_by_api_credential_id,
            "credentialName": decision_credential.name if decision_credential else None,
        }
    elif permission.decided_by_user_id:
        decided_by = {"type": "organization_member", "userId": permission.decided_by_user_id}
    settlement = (
        db.query(SettlementRecord)
        .filter(SettlementRecord.permission_request_id == permission.id)
        .first()
    )
    assignment = _current_permission_assignment(db, permission_id=permission.id)
    usage_reports = (
        db.query(PermissionUsageReportRecord)
        .filter(PermissionUsageReportRecord.permission_request_id == permission.id)
        .order_by(
            PermissionUsageReportRecord.published_at.asc(),
            PermissionUsageReportRecord.id.asc(),
        )
        .all()
    )
    return {
        "id": permission.id,
        "directions": directions,
        "requester": {
            "organizationId": permission.requester_org_id,
            "organizationName": requester_org.name if requester_org else None,
        },
        "authority": {
            "claimId": claim.id if claim else None,
            "organizationId": claim.org_id if claim else None,
            "organizationName": authority_org.name if authority_org else None,
            "rightType": claim.right_type if claim else None,
            "verificationStatus": claim.status if claim else None,
        },
        "workKey": permission.work_key,
        "workTitle": (((contract.contract_json or {}).get("metadata") or {}).get("workTitle") if contract else None),
        "intendedUsage": permission.intended_usage,
        "territory": permission.territory,
        "termStart": permission.term_start,
        "termEnd": permission.term_end,
        "context": permission.context,
        "provenance": permission.provenance,
        "licenseObligations": permission.license_obligations or _empty_license_obligations(),
        "decisionRequirements": {
            "exactAttributionRequired": (
                _policy_requires_exact_attribution(
                    contract,
                    intended_usage=permission.intended_usage,
                )
                if contract
                else False
            ),
        },
        "status": permission.status,
        "decisionNote": permission.decision_note,
        "requestedBy": _permission_request_actor_payload(db, permission),
        "decidedBy": decided_by,
        "requestedAt": permission.requested_at,
        "decidedAt": permission.decided_at,
        "receiptId": grant_receipt.id if grant_receipt else None,
        "latestReceiptId": latest_receipt.id if latest_receipt else None,
        "settlementId": settlement.id if settlement else None,
        "reviewAssignment": _serialize_review_assignment(
            db,
            assignment=assignment,
            viewer_org_id=viewer_org_id,
        ),
        "usageReports": [
            _serialize_usage_report(
                db,
                report=report,
                obligations=permission.license_obligations or {},
            )
            for report in usage_reports
        ],
        "lifecycleRecords": [
            {
                "receiptId": row.id,
                "eventType": row.receipt_kind,
                "status": (row.payload or {}).get("status"),
                "reason": ((row.payload or {}).get("event") or {}).get("reason"),
                "priorReceiptId": row.prior_receipt_id,
                "replacementReceiptId": ((row.payload or {}).get("event") or {}).get("replacementReceiptId"),
                "createdAt": row.created_at,
            }
            for row in receipts
            if row.receipt_kind in {"dispute", "revocation", "correction", "expiry"}
        ],
    }


@app.get("/v1/organizations/{org_id}/permission-requests")
def list_organization_permission_requests(
    org_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="permissions:read" if authorization else None,
    )
    _require_principal_organization(
        db,
        principal=principal,
        org_id=org_id,
        required_scope="permissions:read" if principal.credential else None,
    )
    authority_claim_ids = [
        row.id
        for row in db.query(AuthorityClaimRecord.id)
        .filter(AuthorityClaimRecord.org_id == org_id)
        .all()
    ]
    query = db.query(PermissionRequestRecord)
    if authority_claim_ids:
        query = query.filter(
            (PermissionRequestRecord.requester_org_id == org_id)
            | (PermissionRequestRecord.authority_claim_id.in_(authority_claim_ids))
        )
    else:
        query = query.filter(PermissionRequestRecord.requester_org_id == org_id)
    rows = query.order_by(PermissionRequestRecord.requested_at.desc()).all()
    return {
        "permissionRequests": [
            _serialize_permission_for_org(db, permission=row, viewer_org_id=org_id)
            for row in rows
        ]
    }


def _require_permission_party(
    db: Session, *, principal: V1Principal,
    permission: PermissionRequestRecord, claim: Optional[AuthorityClaimRecord],
) -> str:
    candidate_org_ids = {permission.requester_org_id}
    if claim:
        candidate_org_ids.add(claim.org_id)
    viewer_org_id = None
    if principal.credential:
        if principal.credential.org_id in candidate_org_ids:
            viewer_org_id = principal.credential.org_id
    else:
        for org_id in candidate_org_ids:
            membership = (
                db.query(OrganizationMembershipRecord)
                .filter(
                    OrganizationMembershipRecord.org_id == org_id,
                    OrganizationMembershipRecord.user_id == principal.user.id,
                )
                .first()
            )
            if membership:
                viewer_org_id = org_id
                break
    if not viewer_org_id:
        raise HTTPException(status_code=403, detail="Permission access requires a party organization")
    return viewer_org_id


@app.get("/v1/permission-requests/{permission_id}")
def get_permission_request(
    permission_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="permissions:read" if authorization else None,
    )
    permission = (
        db.query(PermissionRequestRecord)
        .filter(PermissionRequestRecord.id == permission_id)
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Permission request not found")
    claim = (
        db.query(AuthorityClaimRecord)
        .filter(AuthorityClaimRecord.id == permission.authority_claim_id)
        .first()
    )
    viewer_org_id = _require_permission_party(db, principal=principal, permission=permission, claim=claim)
    return _serialize_permission_for_org(
        db, permission=permission, viewer_org_id=viewer_org_id
    )


SETTLEMENT_ROYALTY_BASES = {"gross_revenue", "net_revenue", "net_receipts"}
SETTLEMENT_ENTRY_KINDS = {
    "reserve",
    "reserve_release",
    "royalty_adjustment_increase",
    "royalty_adjustment_decrease",
    "payment_received",
    "payment_reversal",
    "payout",
    "payout_reversal",
}


def _financial_actor(
    db: Session,
    *,
    user_id: Optional[str],
    credential_id: Optional[str],
) -> Dict[str, Any]:
    if credential_id:
        credential = db.query(ApiCredentialRecord).filter(ApiCredentialRecord.id == credential_id).first()
        return {
            "type": "api_credential",
            "credentialId": credential_id,
            "credentialName": credential.name if credential else None,
            "organizationId": credential.org_id if credential else None,
        }
    user = db.query(UserRecord).filter(UserRecord.id == user_id).first() if user_id else None
    return {
        "type": "organization_member",
        "userId": user_id,
        "email": user.email if user else None,
    }


def _settlement_context(
    db: Session,
    *,
    settlement_id: Optional[str] = None,
    permission_id: Optional[str] = None,
    lock: bool = False,
) -> tuple[Optional[SettlementRecord], PermissionRequestRecord, AuthorityClaimRecord]:
    settlement_query = db.query(SettlementRecord)
    if settlement_id:
        settlement_query = settlement_query.filter(SettlementRecord.id == settlement_id)
    elif permission_id:
        settlement_query = settlement_query.filter(SettlementRecord.permission_request_id == permission_id)
    else:
        raise RuntimeError("A settlement or permission identifier is required")
    if lock:
        settlement_query = settlement_query.with_for_update()
    settlement = settlement_query.first()
    if settlement_id and not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    effective_permission_id = settlement.permission_request_id if settlement else permission_id
    permission = (
        db.query(PermissionRequestRecord)
        .filter(PermissionRequestRecord.id == effective_permission_id)
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Permission request not found")
    claim = (
        db.query(AuthorityClaimRecord)
        .filter(AuthorityClaimRecord.id == permission.authority_claim_id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=409, detail="Authority claim is unavailable")
    return settlement, permission, claim


def _require_settlement_party(
    db: Session,
    *,
    principal: V1Principal,
    settlement: SettlementRecord,
    required_scope: Optional[str] = None,
) -> str:
    party_org_ids = {settlement.requester_org_id, settlement.authority_org_id}
    if principal.credential:
        if principal.credential.org_id not in party_org_ids:
            raise HTTPException(status_code=403, detail="API credential is not a party to this settlement")
        if required_scope and required_scope not in set(principal.credential.scopes or []):
            raise HTTPException(status_code=403, detail=f"API credential requires scope {required_scope}")
        return principal.credential.org_id
    for org_id in party_org_ids:
        membership = (
            db.query(OrganizationMembershipRecord)
            .filter(
                OrganizationMembershipRecord.org_id == org_id,
                OrganizationMembershipRecord.user_id == principal.user.id,
            )
            .first()
        )
        if membership:
            return org_id
    raise HTTPException(status_code=403, detail="Settlement access requires a party organization")


def _settlement_entries(db: Session, settlement_id: str) -> List[SettlementEntryRecord]:
    return (
        db.query(SettlementEntryRecord)
        .filter(SettlementEntryRecord.settlement_id == settlement_id)
        .order_by(SettlementEntryRecord.created_at.asc(), SettlementEntryRecord.id.asc())
        .all()
    )


def _settlement_beneficiaries(db: Session, settlement_id: str) -> List[SettlementBeneficiaryRecord]:
    return (
        db.query(SettlementBeneficiaryRecord)
        .filter(SettlementBeneficiaryRecord.settlement_id == settlement_id)
        .order_by(SettlementBeneficiaryRecord.identifier.asc(), SettlementBeneficiaryRecord.id.asc())
        .all()
    )


def _allocate_minor_units(
    total_minor: int,
    beneficiaries: List[SettlementBeneficiaryRecord],
) -> Dict[str, int]:
    allocations: Dict[str, int] = {}
    remainders: List[tuple[int, str, str]] = []
    assigned = 0
    for beneficiary in beneficiaries:
        numerator = total_minor * beneficiary.share_bps
        amount = numerator // 10000
        allocations[beneficiary.id] = amount
        assigned += amount
        remainders.append((numerator % 10000, beneficiary.identifier, beneficiary.id))
    remaining = total_minor - assigned
    for _, _, beneficiary_id in sorted(remainders, key=lambda row: (-row[0], row[1], row[2]))[:remaining]:
        allocations[beneficiary_id] += 1
    return allocations


def _settlement_totals(
    settlement: SettlementRecord,
    beneficiaries: List[SettlementBeneficiaryRecord],
    entries: List[SettlementEntryRecord],
) -> Dict[str, Any]:
    signed_kinds = {
        "reserve": 1,
        "reserve_release": -1,
        "royalty_accrual": 1,
        "royalty_adjustment_increase": 1,
        "royalty_adjustment_decrease": -1,
        "payment_received": 1,
        "payment_reversal": -1,
        "payout": 1,
        "payout_reversal": -1,
    }
    reserve_minor = sum(
        signed_kinds.get(row.kind, 0) * row.amount_minor
        for row in entries
        if row.kind in {"reserve", "reserve_release"}
    )
    royalty_minor = sum(
        signed_kinds.get(row.kind, 0) * row.amount_minor
        for row in entries
        if row.kind.startswith("royalty_")
    )
    payment_minor = sum(
        signed_kinds.get(row.kind, 0) * row.amount_minor
        for row in entries
        if row.kind in {"payment_received", "payment_reversal"}
    )
    payout_minor = sum(
        signed_kinds.get(row.kind, 0) * row.amount_minor
        for row in entries
        if row.kind in {"payout", "payout_reversal"}
    )
    if min(reserve_minor, royalty_minor, payment_minor, payout_minor) < 0:
        raise HTTPException(status_code=409, detail="Settlement ledger contains an invalid negative balance")
    obligation_minor = (
        max(settlement.minimum_commitment_minor, royalty_minor)
        if settlement.minimum_recoupable
        else settlement.minimum_commitment_minor + royalty_minor
    )
    allocations = _allocate_minor_units(obligation_minor, beneficiaries)
    payout_by_beneficiary = {
        beneficiary.id: sum(
            signed_kinds.get(row.kind, 0) * row.amount_minor
            for row in entries
            if row.beneficiary_id == beneficiary.id and row.kind in {"payout", "payout_reversal"}
        )
        for beneficiary in beneficiaries
    }
    beneficiary_totals = [
        {
            "beneficiaryId": beneficiary.id,
            "identifier": beneficiary.identifier,
            "name": beneficiary.name,
            "shareBps": beneficiary.share_bps,
            "obligationMinor": allocations[beneficiary.id],
            "payoutMinor": payout_by_beneficiary[beneficiary.id],
            "varianceMinor": payout_by_beneficiary[beneficiary.id] - allocations[beneficiary.id],
        }
        for beneficiary in beneficiaries
    ]
    balanced = (
        obligation_minor > 0
        and payment_minor == obligation_minor
        and payout_minor == obligation_minor
        and all(row["varianceMinor"] == 0 for row in beneficiary_totals)
    )
    return {
        "currency": settlement.currency,
        "minimumCommitmentMinor": settlement.minimum_commitment_minor,
        "minimumRecoupable": settlement.minimum_recoupable,
        "reserveMinor": reserve_minor,
        "royaltyAccruedMinor": royalty_minor,
        "obligationMinor": obligation_minor,
        "paymentReceivedMinor": payment_minor,
        "payoutMinor": payout_minor,
        "paymentVarianceMinor": payment_minor - obligation_minor,
        "payoutVarianceMinor": payout_minor - obligation_minor,
        "beneficiaries": beneficiary_totals,
        "balanced": balanced,
    }


def _settlement_ledger_digest(
    settlement: SettlementRecord,
    beneficiaries: List[SettlementBeneficiaryRecord],
    entries: List[SettlementEntryRecord],
) -> str:
    payload = {
        "settlement": {
            "id": settlement.id,
            "permissionRequestId": settlement.permission_request_id,
            "requesterOrganizationId": settlement.requester_org_id,
            "authorityOrganizationId": settlement.authority_org_id,
            "currency": settlement.currency,
            "minimumCommitmentMinor": settlement.minimum_commitment_minor,
            "minimumRecoupable": settlement.minimum_recoupable,
            "royaltyRateBps": settlement.royalty_rate_bps,
            "royaltyBasis": settlement.royalty_basis,
            "terms": settlement.terms or {},
        },
        "beneficiaries": [
            {
                "id": row.id,
                "beneficiaryOrganizationId": row.beneficiary_org_id,
                "name": row.name,
                "identifier": row.identifier,
                "shareBps": row.share_bps,
            }
            for row in beneficiaries
        ],
        "entries": [
            {
                "id": row.id,
                "kind": row.kind,
                "amountMinor": row.amount_minor,
                "beneficiaryId": row.beneficiary_id,
                "periodStart": row.period_start,
                "periodEnd": row.period_end,
                "externalReference": row.external_reference,
                "evidence": row.evidence or {},
                "calculation": row.calculation or {},
                "idempotencyKey": row.idempotency_key,
                "requestHash": row.request_hash,
                "createdAt": row.created_at.replace(microsecond=0).isoformat() + "Z",
            }
            for row in entries
        ],
    }
    return sha256_hex(canonical_json(payload))


def _serialize_settlement_entry(db: Session, row: SettlementEntryRecord) -> Dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "amountMinor": row.amount_minor,
        "beneficiaryId": row.beneficiary_id,
        "periodStart": row.period_start,
        "periodEnd": row.period_end,
        "externalReference": row.external_reference,
        "evidence": row.evidence or {},
        "calculation": row.calculation or {},
        "idempotencyKey": row.idempotency_key,
        "recordedBy": _financial_actor(
            db,
            user_id=row.recorded_by_user_id,
            credential_id=row.recorded_by_api_credential_id,
        ),
        "createdAt": row.created_at,
    }


def _serialize_reconciliation(db: Session, row: SettlementReconciliationRecord) -> Dict[str, Any]:
    return {
        "id": row.id,
        "receiptId": row.receipt_id,
        "status": row.status,
        "assertionType": row.assertion_type,
        "entryCount": row.entry_count,
        "ledgerDigest": row.ledger_digest,
        "totals": row.totals,
        "evidence": row.evidence or {},
        "idempotencyKey": row.idempotency_key,
        "recordedBy": _financial_actor(
            db,
            user_id=row.recorded_by_user_id,
            credential_id=row.recorded_by_api_credential_id,
        ),
        "createdAt": row.created_at,
    }


def _serialize_settlement(db: Session, settlement: SettlementRecord) -> Dict[str, Any]:
    beneficiaries = _settlement_beneficiaries(db, settlement.id)
    entries = _settlement_entries(db, settlement.id)
    reconciliations = (
        db.query(SettlementReconciliationRecord)
        .filter(SettlementReconciliationRecord.settlement_id == settlement.id)
        .order_by(
            SettlementReconciliationRecord.created_at.asc(),
            SettlementReconciliationRecord.id.asc(),
        )
        .all()
    )
    digest = _settlement_ledger_digest(settlement, beneficiaries, entries)
    latest = reconciliations[-1] if reconciliations else None
    reconciliation_current = bool(latest and latest.ledger_digest == digest)
    assertion_type = latest.assertion_type if reconciliation_current else "provisional"
    permission = (
        db.query(PermissionRequestRecord)
        .filter(PermissionRequestRecord.id == settlement.permission_request_id)
        .first()
    )
    status = "paid" if assertion_type == "paid" else "active" if permission and permission.status == "approved" else "provisional"
    return {
        "id": settlement.id,
        "permissionRequestId": settlement.permission_request_id,
        "requesterOrganizationId": settlement.requester_org_id,
        "authorityOrganizationId": settlement.authority_org_id,
        "currency": settlement.currency,
        "minimumCommitmentMinor": settlement.minimum_commitment_minor,
        "minimumRecoupable": settlement.minimum_recoupable,
        "royaltyRateBps": settlement.royalty_rate_bps,
        "royaltyBasis": settlement.royalty_basis,
        "terms": settlement.terms or {},
        "status": status,
        "assertionType": assertion_type,
        "ledgerDigest": digest,
        "reconciliationCurrent": reconciliation_current,
        "totals": _settlement_totals(settlement, beneficiaries, entries),
        "beneficiaries": [
            {
                "id": row.id,
                "beneficiaryOrganizationId": row.beneficiary_org_id,
                "name": row.name,
                "identifier": row.identifier,
                "shareBps": row.share_bps,
            }
            for row in beneficiaries
        ],
        "entries": [_serialize_settlement_entry(db, row) for row in entries],
        "reconciliations": [_serialize_reconciliation(db, row) for row in reconciliations],
        "createdBy": _financial_actor(
            db,
            user_id=settlement.created_by_user_id,
            credential_id=settlement.created_by_api_credential_id,
        ),
        "createdAt": settlement.created_at,
    }


def _audit_settlement_action(
    db: Session,
    *,
    settlement: SettlementRecord,
    principal: V1Principal,
    action: str,
    resource_type: str,
    resource_id: str,
    details: Dict[str, Any],
) -> None:
    for org_id in {settlement.requester_org_id, settlement.authority_org_id}:
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=principal,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )


def _has_grant_receipt(db: Session, permission_id: str) -> bool:
    return bool(
        db.query(PermissionReceiptRecord.id)
        .filter(
            PermissionReceiptRecord.permission_request_id == permission_id,
            PermissionReceiptRecord.receipt_kind == "grant",
        )
        .first()
    )


@app.post("/v1/permission-requests/{permission_id}/settlement", status_code=201)
def create_settlement(
    permission_id: str,
    req: SettlementCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="settlements:write" if authorization else None,
    )
    existing, permission, claim = _settlement_context(db, permission_id=permission_id)
    _require_principal_organization(
        db,
        principal=principal,
        org_id=claim.org_id,
        required_scope="settlements:write" if principal.credential else None,
        allowed_roles=ORG_DECISION_ROLES,
    )
    if existing:
        raise HTTPException(status_code=409, detail="This permission already has settlement terms")
    if permission.status not in {"pending", "approved"}:
        raise HTTPException(status_code=409, detail=f"Settlement terms cannot be created for a {permission.status} permission")
    currency = req.currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise HTTPException(status_code=422, detail="currency must be a three-letter ISO-style code")
    royalty_basis = req.royalty_basis.strip().lower()
    if royalty_basis not in SETTLEMENT_ROYALTY_BASES:
        raise HTTPException(status_code=422, detail="Unsupported royalty basis")
    if req.minimum_commitment_minor == 0 and req.royalty_rate_bps == 0:
        raise HTTPException(status_code=422, detail="Settlement terms require a positive minimum or royalty rate")
    if sum(row.share_bps for row in req.beneficiaries) != 10000:
        raise HTTPException(status_code=422, detail="Beneficiary shares must total exactly 10,000 basis points")
    identifiers = [row.identifier.strip() for row in req.beneficiaries]
    if len({identifier.casefold() for identifier in identifiers}) != len(identifiers):
        raise HTTPException(status_code=422, detail="Beneficiary identifiers must be unique")
    if not req.confirm_immutable_terms:
        raise HTTPException(
            status_code=422,
            detail="Confirm that settlement terms and beneficiary shares are final and immutable",
        )
    beneficiary_org_ids = {row.beneficiary_org_id for row in req.beneficiaries if row.beneficiary_org_id}
    if beneficiary_org_ids:
        known_org_ids = {
            row.id
            for row in db.query(OrganizationRecord.id)
            .filter(OrganizationRecord.id.in_(beneficiary_org_ids))
            .all()
        }
        if known_org_ids != beneficiary_org_ids:
            raise HTTPException(status_code=422, detail="A beneficiary organization does not exist on this node")
    settlement = SettlementRecord(
        permission_request_id=permission.id,
        requester_org_id=permission.requester_org_id,
        authority_org_id=claim.org_id,
        currency=currency,
        minimum_commitment_minor=req.minimum_commitment_minor,
        minimum_recoupable=req.minimum_recoupable,
        royalty_rate_bps=req.royalty_rate_bps,
        royalty_basis=royalty_basis,
        terms=req.terms,
        created_by_user_id=principal.user.id if principal.user else None,
        created_by_api_credential_id=principal.credential.id if principal.credential else None,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(settlement)
    db.flush()
    for beneficiary in req.beneficiaries:
        name = beneficiary.name.strip()
        identifier = beneficiary.identifier.strip()
        if not name or not identifier:
            raise HTTPException(status_code=422, detail="Beneficiary name and identifier cannot be blank")
        db.add(
            SettlementBeneficiaryRecord(
                settlement_id=settlement.id,
                beneficiary_org_id=beneficiary.beneficiary_org_id,
                name=name,
                identifier=identifier,
                share_bps=beneficiary.share_bps,
                created_at=datetime.datetime.utcnow(),
            )
        )
    db.flush()
    _audit_settlement_action(
        db,
        settlement=settlement,
        principal=principal,
        action="settlement.terms.created",
        resource_type="settlement",
        resource_id=settlement.id,
        details={
            "permissionRequestId": permission.id,
            "currency": currency,
            "minimumCommitmentMinor": settlement.minimum_commitment_minor,
            "royaltyRateBps": settlement.royalty_rate_bps,
            "beneficiaryCount": len(req.beneficiaries),
            "immutableTermsConfirmed": True,
            "assertionType": "provisional",
        },
    )
    db.commit()
    db.refresh(settlement)
    return _serialize_settlement(db, settlement)


@app.get("/v1/permission-requests/{permission_id}/settlement")
def get_permission_settlement(
    permission_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="settlements:read" if authorization else None,
    )
    settlement, _, _ = _settlement_context(db, permission_id=permission_id)
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    _require_settlement_party(
        db,
        principal=principal,
        settlement=settlement,
        required_scope="settlements:read" if principal.credential else None,
    )
    return _serialize_settlement(db, settlement)


def _create_financial_entry(
    *,
    settlement: SettlementRecord,
    principal: V1Principal,
    kind: str,
    amount_minor: int,
    beneficiary_id: Optional[str],
    period_start: Optional[str],
    period_end: Optional[str],
    external_reference: Optional[str],
    evidence: Dict[str, Any],
    calculation: Dict[str, Any],
    idempotency_key: str,
    request_hash: str,
) -> SettlementEntryRecord:
    return SettlementEntryRecord(
        settlement_id=settlement.id,
        kind=kind,
        amount_minor=amount_minor,
        beneficiary_id=beneficiary_id,
        period_start=period_start,
        period_end=period_end,
        external_reference=external_reference,
        evidence=evidence,
        calculation=calculation,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        recorded_by_user_id=principal.user.id if principal.user else None,
        recorded_by_api_credential_id=principal.credential.id if principal.credential else None,
        created_at=datetime.datetime.utcnow(),
    )


@app.post("/v1/settlements/{settlement_id}/entries", status_code=201)
def create_settlement_entry(
    settlement_id: str,
    req: SettlementEntryCreateRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="settlements:write" if authorization else None,
    )
    settlement, permission, claim = _settlement_context(db, settlement_id=settlement_id, lock=True)
    kind = req.kind.strip().lower()
    if kind not in SETTLEMENT_ENTRY_KINDS:
        raise HTTPException(status_code=422, detail="Unsupported settlement entry kind")
    # A repeated key must pass the same party/role checks as a new operation.
    # Check before comparing cached data, which itself reveals private evidence.
    requester_kind = kind in {"reserve", "reserve_release"}
    actor_org_id = settlement.requester_org_id if requester_kind else settlement.authority_org_id
    _require_principal_organization(
        db,
        principal=principal,
        org_id=actor_org_id,
        required_scope="settlements:write" if principal.credential else None,
        allowed_roles=None if requester_kind else ORG_DECISION_ROLES,
    )
    idempotency_key = req.idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status_code=422, detail="A non-blank idempotency key is required")
    request_payload = req.model_dump(mode="json")
    request_payload["kind"] = kind
    request_payload["idempotency_key"] = idempotency_key
    request_hash = sha256_hex(canonical_json(request_payload))
    existing = (
        db.query(SettlementEntryRecord)
        .filter(
            SettlementEntryRecord.settlement_id == settlement.id,
            SettlementEntryRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for different entry data")
        return _serialize_settlement_entry(db, existing)

    if kind in {"reserve", "payment_received", "payout", "royalty_adjustment_increase"} and not _has_grant_receipt(db, permission.id):
        if kind != "reserve":
            raise HTTPException(status_code=409, detail="A signed grant receipt is required before recording this entry")
    beneficiary = None
    if kind in {"payout", "payout_reversal"}:
        if not req.beneficiary_id:
            raise HTTPException(status_code=422, detail="Payout entries require a beneficiary")
        beneficiary = (
            db.query(SettlementBeneficiaryRecord)
            .filter(
                SettlementBeneficiaryRecord.id == req.beneficiary_id,
                SettlementBeneficiaryRecord.settlement_id == settlement.id,
            )
            .first()
        )
        if not beneficiary:
            raise HTTPException(status_code=422, detail="Beneficiary is not part of this settlement")
    elif req.beneficiary_id:
        raise HTTPException(status_code=422, detail="Only payout entries may identify a beneficiary")
    if kind != "reserve" and (not (req.external_reference or "").strip() or not req.evidence):
        raise HTTPException(status_code=422, detail="This entry requires an external reference and evidence")

    beneficiaries = _settlement_beneficiaries(db, settlement.id)
    current_entries = _settlement_entries(db, settlement.id)
    current_totals = _settlement_totals(settlement, beneficiaries, current_entries)
    if kind == "reserve_release" and req.amount_minor > current_totals["reserveMinor"]:
        raise HTTPException(status_code=409, detail="Reserve release exceeds the recorded reserve")
    if kind == "royalty_adjustment_decrease" and req.amount_minor > current_totals["royaltyAccruedMinor"]:
        raise HTTPException(status_code=409, detail="Royalty decrease exceeds accrued royalties")
    if kind == "payment_reversal" and req.amount_minor > current_totals["paymentReceivedMinor"]:
        raise HTTPException(status_code=409, detail="Payment reversal exceeds recorded payments")
    if kind == "payout_reversal":
        beneficiary_paid = next(
            row["payoutMinor"]
            for row in current_totals["beneficiaries"]
            if row["beneficiaryId"] == beneficiary.id
        )
        if req.amount_minor > beneficiary_paid:
            raise HTTPException(status_code=409, detail="Payout reversal exceeds this beneficiary's recorded payout")
    entry = _create_financial_entry(
        settlement=settlement,
        principal=principal,
        kind=kind,
        amount_minor=req.amount_minor,
        beneficiary_id=beneficiary.id if beneficiary else None,
        period_start=None,
        period_end=None,
        external_reference=(req.external_reference or "").strip() or None,
        evidence=req.evidence,
        calculation={},
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    db.add(entry)
    db.flush()
    _audit_settlement_action(
        db,
        settlement=settlement,
        principal=principal,
        action=f"settlement.entry.{kind}",
        resource_type="settlement_entry",
        resource_id=entry.id,
        details={
            "settlementId": settlement.id,
            "permissionRequestId": permission.id,
            "amountMinor": entry.amount_minor,
            "currency": settlement.currency,
            "beneficiaryId": entry.beneficiary_id,
            "externalReference": entry.external_reference,
        },
    )
    db.commit()
    db.refresh(entry)
    return _serialize_settlement_entry(db, entry)


@app.post("/v1/settlements/{settlement_id}/royalty-calculations", status_code=201)
def calculate_settlement_royalty(
    settlement_id: str,
    req: RoyaltyCalculationRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="settlements:write" if authorization else None,
    )
    settlement, permission, claim = _settlement_context(db, settlement_id=settlement_id, lock=True)
    _require_principal_organization(
        db,
        principal=principal,
        org_id=claim.org_id,
        required_scope="settlements:write" if principal.credential else None,
        allowed_roles=ORG_DECISION_ROLES,
    )
    if not _has_grant_receipt(db, permission.id):
        raise HTTPException(status_code=409, detail="A signed grant receipt is required before calculating royalties")
    try:
        period_start = datetime.date.fromisoformat(req.period_start)
        period_end = datetime.date.fromisoformat(req.period_end)
        term_start = datetime.date.fromisoformat(permission.term_start or "")
        term_end = datetime.date.fromisoformat(permission.term_end or "")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Royalty and permission dates must use YYYY-MM-DD") from error
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="Royalty period start must not follow period end")
    if period_start < term_start or period_end > term_end:
        raise HTTPException(status_code=422, detail="Royalty period must fall within the granted license term")
    idempotency_key = req.idempotency_key.strip()
    external_reference = req.external_reference.strip()
    if not idempotency_key or not external_reference:
        raise HTTPException(status_code=422, detail="Non-blank idempotency and statement references are required")
    request_payload = req.model_dump(mode="json")
    request_payload["idempotency_key"] = idempotency_key
    request_payload["external_reference"] = external_reference
    request_hash = sha256_hex(canonical_json(request_payload))
    existing = (
        db.query(SettlementEntryRecord)
        .filter(
            SettlementEntryRecord.settlement_id == settlement.id,
            SettlementEntryRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for different royalty data")
        return _serialize_settlement_entry(db, existing)
    accruals = (
        db.query(SettlementEntryRecord)
        .filter(
            SettlementEntryRecord.settlement_id == settlement.id,
            SettlementEntryRecord.kind == "royalty_accrual",
        )
        .all()
    )
    for accrual in accruals:
        existing_start = datetime.date.fromisoformat(accrual.period_start)
        existing_end = datetime.date.fromisoformat(accrual.period_end)
        if period_start <= existing_end and period_end >= existing_start:
            raise HTTPException(status_code=409, detail="Royalty period overlaps an existing accrual; append an evidenced adjustment instead")
    royalty_minor = (req.basis_amount_minor * settlement.royalty_rate_bps + 5000) // 10000
    if royalty_minor <= 0:
        raise HTTPException(status_code=409, detail="These terms calculate to a zero royalty; no accrual was recorded")
    entry = _create_financial_entry(
        settlement=settlement,
        principal=principal,
        kind="royalty_accrual",
        amount_minor=royalty_minor,
        beneficiary_id=None,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        external_reference=external_reference,
        evidence=req.evidence,
        calculation={
            "basis": settlement.royalty_basis,
            "basisAmountMinor": req.basis_amount_minor,
            "royaltyRateBps": settlement.royalty_rate_bps,
            "rounding": "nearest_minor_unit_half_up",
            "royaltyAmountMinor": royalty_minor,
        },
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    db.add(entry)
    db.flush()
    _audit_settlement_action(
        db,
        settlement=settlement,
        principal=principal,
        action="settlement.royalty.calculated",
        resource_type="settlement_entry",
        resource_id=entry.id,
        details={
            "settlementId": settlement.id,
            "periodStart": entry.period_start,
            "periodEnd": entry.period_end,
            "basisAmountMinor": req.basis_amount_minor,
            "royaltyAmountMinor": royalty_minor,
            "currency": settlement.currency,
        },
    )
    db.commit()
    db.refresh(entry)
    return _serialize_settlement_entry(db, entry)


def _build_settlement_reconciliation_receipt(
    db: Session,
    *,
    receipt_id: str,
    reconciliation_id: str,
    settlement: SettlementRecord,
    permission: PermissionRequestRecord,
    claim: AuthorityClaimRecord,
    beneficiaries: List[SettlementBeneficiaryRecord],
    entries: List[SettlementEntryRecord],
    totals: Dict[str, Any],
    digest: str,
    evidence: Dict[str, Any],
    principal: V1Principal,
) -> PermissionReceiptRecord:
    grant = (
        db.query(PermissionReceiptRecord)
        .filter(
            PermissionReceiptRecord.permission_request_id == permission.id,
            PermissionReceiptRecord.receipt_kind == "grant",
        )
        .first()
    )
    if not grant:
        raise HTTPException(status_code=409, detail="A signed grant receipt is required before reconciliation")
    permission_prior = (
        db.query(PermissionReceiptRecord)
        .filter(PermissionReceiptRecord.permission_request_id == permission.id)
        .order_by(PermissionReceiptRecord.transparency_sequence.desc())
        .first()
    )
    transparency_prior = (
        db.query(PermissionReceiptRecord)
        .order_by(PermissionReceiptRecord.transparency_sequence.desc())
        .first()
    )
    sequence = 1 if not transparency_prior else transparency_prior.transparency_sequence + 1
    previous_entry_hash = transparency_prior.entry_hash if transparency_prior else None
    requester_org = db.query(OrganizationRecord).filter(OrganizationRecord.id == settlement.requester_org_id).first()
    authority_org = db.query(OrganizationRecord).filter(OrganizationRecord.id == settlement.authority_org_id).first()
    issued_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    assertion_type = "paid" if totals["balanced"] else "provisional"
    disclosure_plan = data_privacy.plan_disclosure(db, claim.org_id, permission.requester_org_id)
    payload = {
        "disclosure": disclosure_plan.private_manifest(),
        "schemaVersion": SETTLEMENT_SCHEMA_VERSION,
        "receiptId": receipt_id,
        "node": {"id": settings.NODE_ID, "keyId": receipt_signer.key_id},
        "issuedAt": issued_at,
        "status": assertion_type,
        "permission": {
            "requestId": permission.id,
            "grantReceiptId": grant.id,
            "grantPayloadHash": grant.payload_hash,
            "workKey": permission.work_key,
            "intendedUsage": permission.intended_usage,
            "territory": permission.territory,
            "termStart": permission.term_start,
            "termEnd": permission.term_end,
        },
        "requester": {
            "organizationId": settlement.requester_org_id,
            "name": requester_org.name if requester_org else None,
        },
        "authority": {
            "claimId": claim.id,
            "organizationId": settlement.authority_org_id,
            "name": authority_org.name if authority_org else None,
            "rightType": claim.right_type,
        },
        "settlement": {
            "id": settlement.id,
            "reconciliationId": reconciliation_id,
            "currency": settlement.currency,
            "minimumCommitmentMinor": settlement.minimum_commitment_minor,
            "minimumRecoupable": settlement.minimum_recoupable,
            "royaltyRateBps": settlement.royalty_rate_bps,
            "royaltyBasis": settlement.royalty_basis,
            "terms": settlement.terms or {},
            "beneficiaries": [
                {
                    "id": row.id,
                    "beneficiaryOrganizationId": row.beneficiary_org_id,
                    "name": row.name,
                    "identifier": row.identifier,
                    "shareBps": row.share_bps,
                }
                for row in beneficiaries
            ],
            "entries": [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "amountMinor": row.amount_minor,
                    "beneficiaryId": row.beneficiary_id,
                    "periodStart": row.period_start,
                    "periodEnd": row.period_end,
                    "externalReference": row.external_reference,
                    "evidenceHash": sha256_hex(canonical_json(row.evidence or {})),
                    "calculation": row.calculation or {},
                }
                for row in entries
            ],
            "entryCount": len(entries),
            "ledgerDigest": digest,
            "totals": totals,
            "reconciliationStatus": "balanced" if totals["balanced"] else "unbalanced",
            "assertionType": assertion_type,
            "reconciliationEvidence": evidence,
        },
        "decision": {
            "actor": _principal_actor(principal, organization_id=settlement.authority_org_id),
            "priorReceiptId": permission_prior.id if permission_prior else grant.id,
            "priorPayloadHash": permission_prior.payload_hash if permission_prior else grant.payload_hash,
        },
    }
    signed = receipt_signer.sign_receipt(
        payload=payload,
        transparency_sequence=sequence,
        previous_entry_hash=previous_entry_hash,
    )
    receipt_row = PermissionReceiptRecord(
        id=receipt_id,
        permission_request_id=permission.id,
        receipt_kind="settlement_reconciliation",
        prior_receipt_id=permission_prior.id if permission_prior else grant.id,
        schema_version=SETTLEMENT_SCHEMA_VERSION,
        node_id=settings.NODE_ID,
        payload=payload,
        payload_hash=signed["proof"]["payloadHash"],
        signature=signed["proof"]["signature"],
        public_key=signed["proof"]["publicKey"],
        key_id=signed["proof"]["keyId"],
        transparency_sequence=sequence,
        previous_entry_hash=previous_entry_hash,
        entry_hash=signed["transparency"]["entryHash"],
        created_at=datetime.datetime.utcnow(),
    )

    db.add(receipt_row)
    data_privacy.attach_disclosure(db, row=receipt_row, plan=disclosure_plan, signer=receipt_signer)
    return receipt_row


@app.post("/v1/settlements/{settlement_id}/reconciliations", status_code=201)
def reconcile_settlement(
    settlement_id: str,
    req: SettlementReconcileRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="settlements:reconcile" if authorization else None,
    )
    settlement, permission, claim = _settlement_context(db, settlement_id=settlement_id, lock=True)
    _require_principal_organization(
        db,
        principal=principal,
        org_id=claim.org_id,
        required_scope="settlements:reconcile" if principal.credential else None,
        allowed_roles=ORG_DECISION_ROLES,
    )
    if not _has_grant_receipt(db, permission.id):
        raise HTTPException(status_code=409, detail="A signed grant receipt is required before reconciliation")
    beneficiaries = _settlement_beneficiaries(db, settlement.id)
    entries = _settlement_entries(db, settlement.id)
    totals = _settlement_totals(settlement, beneficiaries, entries)
    digest = _settlement_ledger_digest(settlement, beneficiaries, entries)
    idempotency_key = req.idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status_code=422, detail="A non-blank idempotency key is required")
    request_payload = {**req.model_dump(mode="json"), "idempotency_key": idempotency_key, "ledger_digest": digest}
    request_hash = sha256_hex(canonical_json(request_payload))
    existing = (
        db.query(SettlementReconciliationRecord)
        .filter(
            SettlementReconciliationRecord.settlement_id == settlement.id,
            SettlementReconciliationRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different ledger state")
        return _serialize_reconciliation(db, existing)
    with _transparency_write_lock(db):
        try:
            reconciliation_id = str(uuid.uuid4())
            receipt_id = str(uuid.uuid4())
            receipt = _build_settlement_reconciliation_receipt(
                db,
                receipt_id=receipt_id,
                reconciliation_id=reconciliation_id,
                settlement=settlement,
                permission=permission,
                claim=claim,
                beneficiaries=beneficiaries,
                entries=entries,
                totals=totals,
                digest=digest,
                evidence=req.evidence,
                principal=principal,
            )
            db.add(receipt)
            row = SettlementReconciliationRecord(
                id=reconciliation_id,
                settlement_id=settlement.id,
                receipt_id=receipt_id,
                status="balanced" if totals["balanced"] else "unbalanced",
                assertion_type="paid" if totals["balanced"] else "provisional",
                entry_count=len(entries),
                ledger_digest=digest,
                totals=totals,
                evidence=req.evidence,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                recorded_by_user_id=principal.user.id if principal.user else None,
                recorded_by_api_credential_id=principal.credential.id if principal.credential else None,
                created_at=datetime.datetime.utcnow(),
            )
            db.add(row)
            db.flush()
            _audit_settlement_action(
                db,
                settlement=settlement,
                principal=principal,
                action="settlement.reconciliation.recorded",
                resource_type="settlement_reconciliation",
                resource_id=row.id,
                details={
                    "settlementId": settlement.id,
                    "permissionRequestId": permission.id,
                    "receiptId": receipt_id,
                    "status": row.status,
                    "assertionType": row.assertion_type,
                    "ledgerDigest": digest,
                    "obligationMinor": totals["obligationMinor"],
                    "paymentReceivedMinor": totals["paymentReceivedMinor"],
                    "payoutMinor": totals["payoutMinor"],
                    "currency": settlement.currency,
                },
            )
            db.commit()
            db.refresh(row)
            return _serialize_reconciliation(db, row)
        except Exception:
            db.rollback()
            raise


def _mwl_export_context(
    db: Session,
    *,
    permission_id: str,
) -> tuple[PermissionRequestRecord, AuthorityClaimRecord, OrganizationRecord, OrganizationRecord]:
    permission = (
        db.query(PermissionRequestRecord)
        .filter(PermissionRequestRecord.id == permission_id)
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Permission request not found")
    claim = (
        db.query(AuthorityClaimRecord)
        .filter(AuthorityClaimRecord.id == permission.authority_claim_id)
        .first()
    )
    if not claim or claim.status != "verified" or claim.right_type != "composition":
        raise HTTPException(
            status_code=409,
            detail="DDEX MWL export requires a verified composition authority claim",
        )
    if permission.intended_usage == "derivative_remix" or permission.intended_usage.startswith("ai_"):
        raise HTTPException(
            status_code=409,
            detail="DDEX MWL cannot represent Clef derivative-remix or AI permission scope",
        )
    permission_territory = permission.territory.strip().lower()
    claim_territory = claim.territory.strip().lower()
    if permission_territory not in {"us", "worldwide"} or claim_territory not in {
        "us",
        "worldwide",
    }:
        raise HTTPException(
            status_code=409,
            detail="DDEX MWL 1.0.1 export requires authority and requested permission covering the US",
        )
    requester_org = (
        db.query(OrganizationRecord)
        .filter(OrganizationRecord.id == permission.requester_org_id)
        .first()
    )
    authority_org = (
        db.query(OrganizationRecord).filter(OrganizationRecord.id == claim.org_id).first()
    )
    if not requester_org or not authority_org:
        raise HTTPException(status_code=409, detail="Permission organizations are unavailable")
    return permission, claim, requester_org, authority_org


def _require_ddex_party_access(
    db: Session,
    *,
    principal: V1Principal,
    permission: PermissionRequestRecord,
    claim: AuthorityClaimRecord,
    required_scope: str,
    allowed_roles: Optional[set[str]] = None,
) -> str:
    party_org_ids = {permission.requester_org_id, claim.org_id}
    if principal.credential:
        if principal.credential.org_id not in party_org_ids:
            raise HTTPException(
                status_code=403,
                detail="API credential organization is not a party to this DDEX exchange",
            )
        if required_scope not in set(principal.credential.scopes or []):
            raise HTTPException(
                status_code=403,
                detail=f"API credential requires scope {required_scope}",
            )
        return principal.credential.org_id
    if not principal.user:
        raise HTTPException(status_code=401, detail="Authenticated actor required")
    membership_query = db.query(OrganizationMembershipRecord).filter(
        OrganizationMembershipRecord.org_id.in_(party_org_ids),
        OrganizationMembershipRecord.user_id == principal.user.id,
    )
    if allowed_roles:
        membership_query = membership_query.filter(
            OrganizationMembershipRecord.role.in_(allowed_roles)
        )
    membership = membership_query.first()
    if not membership:
        raise HTTPException(
            status_code=403,
            detail="Organization membership for a DDEX exchange party is required",
        )
    return membership.org_id


def _serialize_ddex_acknowledgement(
    db: Session,
    row: DdexAcknowledgementRecord,
    *,
    include_payload: bool = False,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "id": row.id,
        "exchangeId": row.exchange_id,
        "acknowledgementType": row.acknowledgement_type,
        "status": row.status,
        "assertionType": "observed",
        "effectOnPermission": "none",
        "partnerMessageId": row.partner_message_id,
        "mediaType": row.media_type,
        "payloadSha256": row.payload_sha256,
        "evidence": row.evidence or {},
        "idempotencyKey": row.idempotency_key,
        "requestHash": row.request_hash,
        "recordedBy": _financial_actor(
            db,
            user_id=row.recorded_by_user_id,
            credential_id=row.recorded_by_api_credential_id,
        ),
        "receivedAt": row.received_at,
    }
    if include_payload:
        result["payload"] = row.payload_text
    return result


def _ddex_xml_response(
    *,
    payload: bytes,
    exchange: DdexExchangeRecord,
    permission_id: str,
) -> Response:
    return Response(
        content=payload,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{exchange.message_id}.xml"',
            "X-Clef-DDEX-Exchange-Id": exchange.id,
            "X-Clef-DDEX-Profile": MWL_PROFILE,
            "X-Clef-Permission-Request-Id": permission_id,
            "X-Clef-Rights-Scope": "composition-only",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/v1/permission-requests/{permission_id}/ddex/mwl/license-request")
def export_mwl_license_request(
    permission_id: str,
    req: MWLExportRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="ddex:write" if authorization else None,
    )
    if not req.confirm_composition_only_scope:
        raise HTTPException(status_code=422, detail="Confirm that this MWL export represents US musical-work rights only")
    permission, _, _, authority_org = _mwl_export_context(db, permission_id=permission_id)
    _require_principal_organization(
        db,
        principal=principal,
        org_id=permission.requester_org_id,
        required_scope="ddex:write" if principal.credential else None,
    )
    message_id = str(uuid.uuid4())
    try:
        ddex_adapter.require("permission_request_exchange")
        payload = build_license_request(
            sender_dpid=ddex_adapter.dpid or "",
            sender_name=ddex_adapter.sender_name or "",
            recipient_dpid=ddex_adapter.partner_dpid or "",
            recipient_name=ddex_adapter.partner_name or "",
            rights_controller_identifier=authority_org.id,
            rights_controller_name=authority_org.name,
            rights_controller_role=req.rights_controller_role,
            message_id=message_id,
            license_request_id=permission.id,
            terms=_mwl_terms(req, permission),
            created_at=datetime.datetime.now(datetime.timezone.utc),
            is_test=not settings.DDEX_LIVE_MESSAGES,
        )
        ddex_adapter.validate_mwl(payload)
    except UnsupportedCapability as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except MWLSchemaValidationError as error:
        logging.getLogger(__name__).exception("Generated DDEX MWL request failed schema validation")
        raise HTTPException(status_code=500, detail="Generated DDEX message failed schema validation") from error
    except MWLExportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    exchange = _persist_ddex_exchange(
        db,
        permission=permission,
        message_id=message_id,
        message_type="LicenseRequestMessage",
        payload=payload,
        principal=principal,
    )
    return _ddex_xml_response(payload=payload, exchange=exchange, permission_id=permission.id)


@app.post("/v1/permission-requests/{permission_id}/ddex/mwl/license-decision")
def export_mwl_license_decision(
    permission_id: str,
    req: MWLExportRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="ddex:write" if authorization else None,
    )
    if not req.confirm_composition_only_scope:
        raise HTTPException(status_code=422, detail="Confirm that this MWL export represents US musical-work rights only")
    permission, claim, _, authority_org = _mwl_export_context(db, permission_id=permission_id)
    _require_principal_organization(
        db,
        principal=principal,
        org_id=claim.org_id,
        required_scope="ddex:write" if principal.credential else None,
        allowed_roles=ORG_DECISION_ROLES,
    )
    if permission.status not in {"approved", "rejected"}:
        raise HTTPException(status_code=409, detail="Permission must be decided before exporting a DDEX decision")
    receipt = (
        db.query(PermissionReceiptRecord)
        .filter(PermissionReceiptRecord.permission_request_id == permission.id)
        .first()
    )
    if permission.status == "approved" and not receipt:
        raise HTTPException(status_code=409, detail="Approved permission has no signed Clef receipt")
    message_id = str(uuid.uuid4())
    decision_id = receipt.id if receipt else f"rejection-{permission.id}"
    try:
        ddex_adapter.require("permission_request_exchange")
        payload = build_license_decision(
            sender_dpid=ddex_adapter.dpid or "",
            sender_name=ddex_adapter.sender_name or "",
            recipient_dpid=ddex_adapter.partner_dpid or "",
            recipient_name=ddex_adapter.partner_name or "",
            rights_controller_identifier=authority_org.id,
            rights_controller_name=authority_org.name,
            rights_controller_role=req.rights_controller_role,
            message_id=message_id,
            license_request_id=permission.id,
            decision=permission.status,
            decision_id=decision_id,
            terms=_mwl_terms(req, permission),
            created_at=datetime.datetime.now(datetime.timezone.utc),
            is_test=not settings.DDEX_LIVE_MESSAGES,
            rejection_reason=req.rejection_reason,
            rejection_note=permission.decision_note,
        )
        ddex_adapter.validate_mwl(payload)
    except UnsupportedCapability as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except MWLSchemaValidationError as error:
        logging.getLogger(__name__).exception("Generated DDEX MWL decision failed schema validation")
        raise HTTPException(status_code=500, detail="Generated DDEX message failed schema validation") from error
    except MWLExportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    exchange = _persist_ddex_exchange(
        db,
        permission=permission,
        message_id=message_id,
        message_type="LicenseMessage",
        payload=payload,
        principal=principal,
    )
    return _ddex_xml_response(payload=payload, exchange=exchange, permission_id=permission.id)


@app.get("/v1/ddex/exchanges/{exchange_id}")
def get_ddex_exchange(
    exchange_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="ddex:read" if authorization else None,
    )
    exchange = (
        db.query(DdexExchangeRecord).filter(DdexExchangeRecord.id == exchange_id).first()
    )
    if not exchange:
        raise HTTPException(status_code=404, detail="DDEX exchange not found")
    permission, claim, _, _ = _mwl_export_context(
        db, permission_id=exchange.permission_request_id
    )
    _require_ddex_party_access(
        db,
        principal=principal,
        permission=permission,
        claim=claim,
        required_scope="ddex:read",
    )
    payload = exchange.payload_xml.encode("utf-8")
    if hashlib.sha256(payload).hexdigest() != exchange.payload_sha256:
        raise HTTPException(status_code=500, detail="Stored DDEX exchange integrity check failed")
    return _ddex_xml_response(
        payload=payload,
        exchange=exchange,
        permission_id=permission.id,
    )


@app.post(
    "/v1/ddex/exchanges/{exchange_id}/acknowledgements",
    status_code=201,
)
def record_ddex_acknowledgement(
    exchange_id: str,
    req: DdexAcknowledgementRequest,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="ddex:write" if authorization else None,
    )
    exchange = (
        db.query(DdexExchangeRecord).filter(DdexExchangeRecord.id == exchange_id).first()
    )
    if not exchange:
        raise HTTPException(status_code=404, detail="DDEX exchange not found")
    permission, claim, _, _ = _mwl_export_context(
        db, permission_id=exchange.permission_request_id
    )
    actor_org_id = _require_ddex_party_access(
        db,
        principal=principal,
        permission=permission,
        claim=claim,
        required_scope="ddex:write",
        allowed_roles=ORG_DECISION_ROLES,
    )
    acknowledgement_type = req.acknowledgement_type.strip().lower()
    status = req.status.strip().lower()
    if acknowledgement_type not in {"transport", "business"}:
        raise HTTPException(status_code=422, detail="Acknowledgement type must be transport or business")
    if status not in {"received", "processing", "accepted", "rejected", "error"}:
        raise HTTPException(status_code=422, detail="Unsupported acknowledgement status")
    partner_message_id = (req.partner_message_id or "").strip() or None
    media_type = (req.media_type or "").strip() or None
    payload = req.payload if req.payload not in {None, ""} else None
    evidence = req.evidence or {}
    if not partner_message_id and payload is None and not evidence:
        raise HTTPException(
            status_code=422,
            detail="Record a partner message identifier, response payload, or external evidence",
        )
    if len(canonical_json(evidence)) > 16_384:
        raise HTTPException(status_code=422, detail="Acknowledgement evidence exceeds 16 KB")
    idempotency_key = req.idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status_code=422, detail="A non-blank idempotency key is required")
    payload_sha256 = sha256_hex(payload.encode("utf-8")) if payload is not None else None
    request_payload = {
        "acknowledgementType": acknowledgement_type,
        "status": status,
        "partnerMessageId": partner_message_id,
        "mediaType": media_type,
        "payloadSha256": payload_sha256,
        "evidence": evidence,
        "idempotencyKey": idempotency_key,
    }
    request_hash = sha256_hex(canonical_json(request_payload))
    existing = (
        db.query(DdexAcknowledgementRecord)
        .filter(
            DdexAcknowledgementRecord.exchange_id == exchange.id,
            DdexAcknowledgementRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key was already used for different acknowledgement data",
            )
        return _serialize_ddex_acknowledgement(db, existing, include_payload=True)
    row = DdexAcknowledgementRecord(
        exchange_id=exchange.id,
        acknowledgement_type=acknowledgement_type,
        status=status,
        partner_message_id=partner_message_id,
        media_type=media_type,
        payload_sha256=payload_sha256,
        payload_text=payload,
        evidence=evidence,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        recorded_by_user_id=principal.user.id if principal.user else None,
        recorded_by_api_credential_id=(
            principal.credential.id if principal.credential else None
        ),
        received_at=datetime.datetime.utcnow(),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        replay = (
            db.query(DdexAcknowledgementRecord)
            .filter(
                DdexAcknowledgementRecord.exchange_id == exchange.id,
                DdexAcknowledgementRecord.idempotency_key == idempotency_key,
            )
            .first()
        )
        if replay and replay.request_hash == request_hash:
            return _serialize_ddex_acknowledgement(db, replay, include_payload=True)
        if replay:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key was already used for different acknowledgement data",
            ) from error
        raise
    for org_id in {permission.requester_org_id, claim.org_id}:
        _record_v1_audit(
            db,
            org_id=org_id,
            principal=principal,
            action="ddex_acknowledgement.recorded",
            resource_type="ddex_acknowledgement",
            resource_id=row.id,
            details={
                "exchangeId": exchange.id,
                "messageId": exchange.message_id,
                "acknowledgementType": acknowledgement_type,
                "status": status,
                "assertionType": "observed",
                "effectOnPermission": "none",
                "partnerMessageId": partner_message_id,
                "payloadSha256": payload_sha256,
                "recordingOrganizationId": actor_org_id,
            },
        )
    db.commit()
    db.refresh(row)
    return _serialize_ddex_acknowledgement(db, row, include_payload=True)


@app.get("/v1/ddex/exchanges/{exchange_id}/acknowledgements")
def list_ddex_acknowledgements(
    exchange_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="ddex:read" if authorization else None,
    )
    exchange = (
        db.query(DdexExchangeRecord).filter(DdexExchangeRecord.id == exchange_id).first()
    )
    if not exchange:
        raise HTTPException(status_code=404, detail="DDEX exchange not found")
    permission, claim, _, _ = _mwl_export_context(
        db, permission_id=exchange.permission_request_id
    )
    _require_ddex_party_access(
        db,
        principal=principal,
        permission=permission,
        claim=claim,
        required_scope="ddex:read",
    )
    rows = (
        db.query(DdexAcknowledgementRecord)
        .filter(DdexAcknowledgementRecord.exchange_id == exchange.id)
        .order_by(DdexAcknowledgementRecord.received_at.asc())
        .all()
    )
    return [_serialize_ddex_acknowledgement(db, row) for row in rows]


@app.get("/v1/ddex/acknowledgements/{acknowledgement_id}")
def get_ddex_acknowledgement(
    acknowledgement_id: str,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(
        db,
        x_session_id=x_session_id,
        authorization=authorization,
        required_scope="ddex:read" if authorization else None,
    )
    row = (
        db.query(DdexAcknowledgementRecord)
        .filter(DdexAcknowledgementRecord.id == acknowledgement_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="DDEX acknowledgement not found")
    exchange = (
        db.query(DdexExchangeRecord).filter(DdexExchangeRecord.id == row.exchange_id).first()
    )
    if not exchange:
        raise HTTPException(status_code=409, detail="Acknowledged DDEX exchange is unavailable")
    permission, claim, _, _ = _mwl_export_context(
        db, permission_id=exchange.permission_request_id
    )
    _require_ddex_party_access(
        db,
        principal=principal,
        permission=permission,
        claim=claim,
        required_scope="ddex:read",
    )
    return _serialize_ddex_acknowledgement(db, row, include_payload=True)


@app.get("/v1/receipts/{receipt_id}")
def get_permission_receipt(
    receipt_id: str,
    response: Response,
    db: Session = Depends(get_db),
    x_session_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    principal = _require_v1_principal(db, x_session_id=x_session_id, authorization=authorization)
    row = db.query(PermissionReceiptRecord).filter(PermissionReceiptRecord.id == receipt_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Receipt not found")
    required_scope = "settlements:read" if row.schema_version == SETTLEMENT_SCHEMA_VERSION else "permissions:read"
    if principal.credential and required_scope not in set(principal.credential.scopes or []):
        raise HTTPException(status_code=403, detail=f"API credential requires scope {required_scope}")
    permission = db.query(PermissionRequestRecord).filter(PermissionRequestRecord.id == row.permission_request_id).first()
    if not permission:
        raise HTTPException(status_code=404, detail="Receipt permission is unavailable")
    claim = db.query(AuthorityClaimRecord).filter(AuthorityClaimRecord.id == permission.authority_claim_id).first()
    _require_permission_party(db, principal=principal, permission=permission, claim=claim)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization, X-Session-Id"
    return _serialize_receipt(row)


def _recognized_receipt_signer(receipt: Dict[str, Any]) -> Optional[str]:
    """This node or a configured peer, matched by both pinned key and node ID."""
    proof = receipt.get("proof") if isinstance(receipt, dict) else None
    payload = receipt.get("payload") if isinstance(receipt, dict) else None
    key = proof.get("publicKey") if isinstance(proof, dict) else None
    node = payload.get("node") if isinstance(payload, dict) else None
    node_id = node.get("id") if isinstance(node, dict) else None
    if node_id == receipt_signer.node_id:
        if key == receipt_signer.public_key_b64:
            return "this_node"
        if key in {item.strip() for item in settings.NODE_RETIRED_SIGNING_PUBLIC_KEYS_B64.split(",") if item.strip()}:
            return "this_node_retired_key"
    for peer in app.state.federation_config.peers:
        if key in (*peer.keys, *peer.retired_keys) and node_id == peer.node_id:
            return f"peer:{peer.id}"
    return None


@app.post("/v1/receipts/verify")
def verify_permission_receipt(req: ReceiptVerifyRequest):
    result = ReceiptSigner.verify_receipt(req.receipt)
    # A self-consistent signature proves only that some key signed it; trust needs a known signer.
    signer = _recognized_receipt_signer(req.receipt)
    error = result.error
    if result.valid and not signer:
        error = "Signed by a key this node does not recognize. Establish the issuing node's key before relying on it."
    return {
        "valid": result.valid and signer is not None,
        "payloadHashValid": result.payload_hash_valid,
        "signatureValid": result.signature_valid,
        "transparencyHashValid": result.transparency_hash_valid,
        "signer": signer,
        "error": error,
    }


@app.get("/v1/transparency/head")
def transparency_head(db: Session = Depends(get_db)):
    row = db.query(PermissionReceiptRecord).order_by(PermissionReceiptRecord.transparency_sequence.desc()).first()
    if not row:
        return {"sequence": 0, "entryHash": None}
    return {"sequence": row.transparency_sequence, "entryHash": row.entry_hash}


@app.get("/v1/transparency/entries")
def transparency_entries(
    from_sequence: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(PermissionReceiptRecord)
        .filter(PermissionReceiptRecord.transparency_sequence >= from_sequence)
        .order_by(PermissionReceiptRecord.transparency_sequence.asc())
        .limit(limit)
        .all()
    )
    return {
        "entries": [
            {
                "sequence": row.transparency_sequence,
                "payloadHash": row.payload_hash,
                "previousEntryHash": row.previous_entry_hash,
                "entryHash": row.entry_hash,
            }
            for row in rows
        ]
    }


# --- Root endpoint ---
@app.get("/")
async def root():
    return {"service": "Clef Rights Node API", "version": "0.3.0", "docs": "/docs"}


def _public_reconciliation_status(db: Session, receipt_id: str) -> Dict[str, Any]:
    """Expose freshness of this assertion using retained ledger records, without amounts or parties."""
    reconciliation = db.query(SettlementReconciliationRecord).filter_by(receipt_id=receipt_id).first()
    settlement = db.get(SettlementRecord, reconciliation.settlement_id) if reconciliation else None
    if not settlement:
        return {"reconciliationCurrent": False, "settlementAssertion": "unavailable"}
    digest = _settlement_ledger_digest(settlement, _settlement_beneficiaries(db, settlement.id),
                                     _settlement_entries(db, settlement.id))
    current = reconciliation.ledger_digest == digest
    assertion = reconciliation.assertion_type if current else "provisional"
    return {"reconciliationCurrent": current,
            "settlementAssertion": assertion if assertion in {"paid", "provisional"} else "unavailable"}


from privacy_routes import register_privacy_routes
from sandbox_tour import register_sandbox_tour
from federation_routes import register_federation_routes
from authority_withdrawal import register_authority_withdrawal
register_authority_withdrawal(
    app, get_db=get_db, require_user=_require_session_user, require_membership=_require_membership,
    audit=_record_v1_audit, write_lock=_authority_write_lock,
)
catalog_publications = register_federation_routes(
    app, settings=settings, signer=receipt_signer, get_db=get_db, require_user=_require_session_user,
    require_membership=_require_membership, require_principal=_require_v1_principal,
    audit=_record_v1_audit, write_lock=_transparency_write_lock, default_ai_policy=default_ai_policy,
    vocabulary={"usage": USAGE_KEYS, "restrictions": RESTRICTION_KEYS, "inputs": AI_INPUT_KEYS,
                "modelScopes": AI_MODEL_SCOPE_KEYS, "limits": AI_LIMIT_KEYS, "safeguards": AI_SAFEGUARD_KEYS},
)
from federated_requests import register_federated_request_routes
register_federated_request_routes(
    app, signer=receipt_signer, get_db=get_db, require_principal=_require_v1_principal,
    require_principal_org=_require_principal_organization, submit_request=_submit_permission_request,
    serialize_receipt=_serialize_receipt, write_lock=_authority_write_lock,
    current_publication=catalog_publications.current_payload,
)
register_sandbox_tour(
    app, settings=settings, get_db=get_db, require_user=_require_session_user,
    default_ai_policy=default_ai_policy, usage_keys=USAGE_KEYS,
    restriction_keys=RESTRICTION_KEYS, safeguard_keys=AI_SAFEGUARD_KEYS,
)
register_privacy_routes(
    app, get_db=get_db, require_user=_require_session_user, require_membership=_require_membership,
    require_principal=_require_v1_principal, require_party=_require_permission_party,
    audit=_record_v1_audit, write_lock=_transparency_write_lock, signer=receipt_signer,
    settlement_status=_public_reconciliation_status,
)
