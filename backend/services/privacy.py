"""Disclosure planning before signing; erasure never re-signs altered evidence."""
from __future__ import annotations
import datetime as dt
import hmac
import secrets
import uuid
from dataclasses import dataclass
from typing import Any
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from models import (OrganizationPrivacyRecord, ReceiptDisclosureRecord, PrivacyErasureRequestRecord,
    PermissionReceiptRecord, PermissionRequestRecord, AuthorityClaimRecord, CatalogClientRecord,
    CatalogAssetRecord, RightsContractRecord, OrganizationMembershipRecord, AuditEventRecord, UserRecord)
from services.receipts import ReceiptSigner, canonical_json, sha256_hex

PUBLIC_SCHEMA = "clef.public-receipt.v1"
COMMITMENT_ALGORITHM = "CLEF-PRIVATE-RECEIPT-SHA256-1"
PUBLIC_FIELDS = ["schemaVersion", "receiptId", "node", "issuedAt", "statusAtIssue", "kind", "privateEvidenceCommitment"]
AUDIO_HANDLING = "Audio files remain in the organization's delivery system. Clef records permitted inputs and requested safeguards; that delivery system provides access control, watermarking and usage measurement."
KINDS = {"grant", "dispute", "revocation", "correction", "expiry", "settlement_reconciliation"}
STATUSES = {"permissioned", "disputed", "revoked", "corrected", "expired", "paid", "provisional"}
RETAINED = [
    "Signed-receipt hashes, signatures, minimal erasure audit and the public commitment",
    "Linked agreements, policy versions, authority evidence and permission requests",
    "Catalog metadata and import history, identity and membership records",
    "Financial, compliance, DDEX and webhook records, including previously delivered copies",
    "Downloaded exports, recipient copies, backups and operational logs: operator follow-up required",
]


def iso(value):
    return value.replace(microsecond=0).isoformat() + "Z" if value else None


def settings_for(db, org_id):
    row = db.get(OrganizationPrivacyRecord, org_id)
    return {"publishPublicReceipts": bool(row and row.publish_public_receipts),
            "receiptRetentionDays": row.receipt_retention_days if row else None,
            "legalHold": bool(row and row.legal_hold), "version": row.version if row else 0}


def settings_response(db, org_id):
    return {"settings": settings_for(db, org_id), "publicReceiptFields": PUBLIC_FIELDS,
            "audioHandling": AUDIO_HANDLING, "erasureScopes": ["receipt_copy", "client_contact_email"]}


@dataclass(frozen=True)
class DisclosurePlan:
    public_id: str
    nonce: str
    authority_org_id: str
    requester_org_id: str
    publish: bool
    retain_until: dt.datetime | None
    authorizations: dict[str, int]

    def private_manifest(self):
        return {"profile": PUBLIC_SCHEMA, "publicReceiptId": self.public_id if self.publish else None,
                "publicationAuthorized": self.publish, "authorizations": self.authorizations,
                "commitmentNonce": self.nonce, "retainUntil": iso(self.retain_until)}


def plan_disclosure(db, authority_org_id, requester_org_id, *, now=None, legacy=False):
    now = now or dt.datetime.utcnow()
    policies = {org: settings_for(db, org) for org in {authority_org_id, requester_org_id}}
    days = [p["receiptRetentionDays"] for p in policies.values() if p["receiptRetentionDays"] is not None]
    return DisclosurePlan(str(uuid.uuid4()), secrets.token_hex(32), authority_org_id, requester_org_id,
        not legacy and all(p["publishPublicReceipts"] for p in policies.values()),
        now + dt.timedelta(days=max(days)) if days else None,
        {org: policy["version"] for org, policy in policies.items()})


def private_commitment(receipt, nonce):
    return sha256_hex(canonical_json({"domain": COMMITMENT_ALGORITHM, "nonce": nonce, "receipt": receipt}))


def envelope(row):
    if not row.payload:
        raise HTTPException(status_code=410, detail="This stored private receipt copy was erased. Previously exported originals remain independently verifiable.")
    return {"payload": row.payload,
        "proof": {"algorithm": "Ed25519", "canonicalization": "CLEF-CANONICAL-JSON-1",
                  "payloadHash": row.payload_hash, "keyId": row.key_id, "publicKey": row.public_key, "signature": row.signature},
        "transparency": {"sequence": row.transparency_sequence, "previousEntryHash": row.previous_entry_hash,
                         "payloadHash": row.payload_hash, "entryHash": row.entry_hash}}


def attach_disclosure(db, *, row, plan, signer):
    """Called within the same sequence lock and transaction as private issuance."""
    original = envelope(row)
    commitment = private_commitment(original, plan.nonce)
    public = None
    if plan.publish:
        if row.receipt_kind not in KINDS or row.payload.get("status") not in STATUSES:
            raise ValueError("Unsupported public receipt state")
        prior = db.query(ReceiptDisclosureRecord).filter(ReceiptDisclosureRecord.public_sequence.isnot(None)).order_by(ReceiptDisclosureRecord.public_sequence.desc()).first()
        public_payload = {"schemaVersion": PUBLIC_SCHEMA, "receiptId": plan.public_id,
            "node": {"id": signer.node_id, "keyId": signer.key_id}, "issuedAt": row.payload["issuedAt"],
            "statusAtIssue": row.payload["status"], "kind": row.receipt_kind,
            "privateEvidenceCommitment": {"algorithm": COMMITMENT_ALGORITHM, "value": commitment}}
        public = signer.sign_receipt(payload=public_payload,
            transparency_sequence=prior.public_sequence + 1 if prior else 1,
            previous_entry_hash=prior.public_entry_hash if prior else None)
    disclosure = ReceiptDisclosureRecord(receipt_id=row.id, public_id=plan.public_id,
        authority_org_id=plan.authority_org_id, requester_org_id=plan.requester_org_id,
        commitment_nonce=plan.nonce, private_commitment=commitment, public_receipt=public,
        public_sequence=public["transparency"]["sequence"] if public else None,
        public_entry_hash=public["transparency"]["entryHash"] if public else None, retain_until=plan.retain_until)
    db.add(disclosure)
    return disclosure


def verify_commitment(public, private, nonce):
    if not isinstance(nonce, str) or len(nonce) != 64:
        return False
    if any(not isinstance(value, dict) or not isinstance(value.get("payload"), dict) for value in (public, private)):
        return False
    if not ReceiptSigner.verify_receipt(public).valid or not ReceiptSigner.verify_receipt(private).valid:
        return False
    manifest = private.get("payload", {}).get("disclosure") or {}
    if not isinstance(manifest, dict):
        return False
    if (public["proof"]["publicKey"] != private["proof"]["publicKey"]
            or public["proof"]["keyId"] != private["proof"]["keyId"]
            or not manifest.get("publicationAuthorized")
            or manifest.get("publicReceiptId") != public["payload"].get("receiptId")
            or manifest.get("commitmentNonce") != nonce):
        return False
    commitment = (public.get("payload") or {}).get("privateEvidenceCommitment") or {}
    if not isinstance(commitment, dict):
        return False
    return (public["payload"].get("schemaVersion") == PUBLIC_SCHEMA
            and commitment.get("algorithm") == COMMITMENT_ALGORITHM
            and isinstance(commitment.get("value"), str)
            and hmac.compare_digest(commitment["value"], private_commitment(private, nonce)))


def disclosure_response(row):
    published = bool(row.public_receipt and not row.withdrawn_at)
    return {"publicReceiptId": row.public_id, "publicUrl": f"/v1/public/receipts/{row.public_id}" if published else None,
            "published": published, "withdrawn": bool(row.withdrawn_at), "privateCopyErased": bool(row.erased_at),
            "retainUntil": iso(row.retain_until), "commitmentOpening":
                {"nonce": row.commitment_nonce, "algorithm": COMMITMENT_ALGORITHM} if row.commitment_nonce else None}


def request_response(row):
    return {"id": row.id, "kind": row.kind, "resourceId": row.resource_id, "status": row.status,
            "requiredOrganizationIds": row.required_org_ids, "approvedOrganizationIds": row.approved_org_ids,
            "createdAt": iso(row.created_at), "completedAt": iso(row.completed_at)}


def party_receipt(db, org_id, receipt_id):
    result = db.query(PermissionReceiptRecord, PermissionRequestRecord, AuthorityClaimRecord).join(
        PermissionRequestRecord, PermissionReceiptRecord.permission_request_id == PermissionRequestRecord.id).join(
        AuthorityClaimRecord, PermissionRequestRecord.authority_claim_id == AuthorityClaimRecord.id).filter(
        PermissionReceiptRecord.id == receipt_id,
        or_(PermissionRequestRecord.requester_org_id == org_id, AuthorityClaimRecord.org_id == org_id)).first()
    if not result:
        raise HTTPException(status_code=404, detail="Receipt not found in this organization's records")
    return result


def erasure_preview(db, request):
    blocked = []
    hold = any(settings_for(db, org)["legalHold"] for org in request.required_org_ids)
    if hold: blocked.append("A party organization has an active legal hold")
    if set(request.approved_org_ids) != set(request.required_org_ids):
        blocked.append("Every party organization must approve this erasure request")
    retain_until = None
    if request.kind == "receipt_copy":
        row = db.get(PermissionReceiptRecord, request.resource_id)
        disclosure = db.get(ReceiptDisclosureRecord, request.resource_id)
        if disclosure: retain_until = disclosure.retain_until
        # A later retention extension can postpone erasure, never shorten the issuance minimum.
        for org in request.required_org_ids:
            days = settings_for(db, org)["receiptRetentionDays"]
            if days and row:
                candidate = row.created_at + dt.timedelta(days=days)
                retain_until = max(retain_until, candidate) if retain_until else candidate
        if retain_until and retain_until > dt.datetime.utcnow(): blocked.append("The minimum retention period has not elapsed")
        if not row or not row.payload: blocked.append("The private receipt copy is already erased or unavailable")
        elif request.resource_hash != row.payload_hash: blocked.append("The selected record changed; create a fresh erasure request")
        will_erase = ["The complete stored private receipt payload", "The secret opening of its public commitment"]
    else:
        row = db.get(CatalogClientRecord, request.resource_id)
        if not row or row.org_id != request.org_id or not row.contact_email:
            blocked.append("The managed-client contact email is already erased or unavailable")
        elif request.resource_hash != sha256_hex(canonical_json(row.contact_email)):
            blocked.append("The contact email changed; create a fresh erasure request")
        will_erase = ["The selected managed client's contact email"]
    if request.status == "completed": blocked.append("This scoped erasure request is complete")
    return {"request": request_response(request), "willErase": will_erase, "retained": RETAINED,
            "blockedBy": blocked, "canExecute": not blocked, "retainUntil": iso(retain_until), "legalHold": hold}


EXPORT_MODELS = {"clients": CatalogClientRecord, "catalog": CatalogAssetRecord, "policies": RightsContractRecord,
                 "claims": AuthorityClaimRecord, "permissions": PermissionRequestRecord, "receipts": PermissionReceiptRecord,
                 "members": OrganizationMembershipRecord, "audit": AuditEventRecord}


def export_page(db, org_id, resource, cursor, limit):
    model = EXPORT_MODELS.get(resource)
    if not model: raise HTTPException(status_code=422, detail="Unknown export resource")
    query = db.query(model)
    if resource == "policies": query = query.filter(model.owner_org_id == org_id)
    elif resource in {"permissions", "receipts"}:
        if resource == "receipts": query = query.join(PermissionRequestRecord, model.permission_request_id == PermissionRequestRecord.id)
        query = query.join(AuthorityClaimRecord, PermissionRequestRecord.authority_claim_id == AuthorityClaimRecord.id).filter(
            or_(PermissionRequestRecord.requester_org_id == org_id, AuthorityClaimRecord.org_id == org_id))
    else: query = query.filter(model.org_id == org_id)
    # Exporting audit history must not add a new row to its own paginated result.
    if resource == "audit": query = query.filter(model.action != "privacy.export.created")
    if cursor: query = query.filter(model.id > cursor)
    rows = query.order_by(model.id).limit(limit + 1).all()
    records = []
    for row in rows[:limit]:
        if resource == "receipts":
            records.append({"id": row.id, "erased": not bool(row.payload), "receipt": envelope(row) if row.payload else None,
                            "payloadHash": row.payload_hash})
        else:
            record = {col.name: getattr(row, col.name) for col in model.__table__.columns}
            if resource == "members":
                user = db.get(UserRecord, row.user_id)
                record["email"] = user.email if user else None
                record["displayName"] = user.display_name if user else None
            records.append(record)
    return {"schemaVersion": "clef.organization-export.v1", "organizationId": org_id, "resource": resource,
            "records": records, "nextCursor": rows[limit-1].id if len(rows) > limit else None,
            "exportedAt": iso(dt.datetime.utcnow())}
