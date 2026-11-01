"""Human-administered privacy operations and a minimal public receipt surface."""
import datetime as dt
import uuid
from typing import Any, Literal
from fastapi import Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from models import (OrganizationPrivacyRecord, ReceiptDisclosureRecord, PrivacyErasureRequestRecord,
                    PermissionReceiptRecord, PermissionRequestRecord, CatalogClientRecord)
from services import privacy
from services.receipts import SETTLEMENT_SCHEMA_VERSION, canonical_json, sha256_hex


class PrivacySettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    publish_public_receipts: bool
    receipt_retention_days: int | None = Field(default=None, ge=1, le=36500)
    legal_hold: bool
    expected_version: int = Field(ge=0)


class ErasureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["receipt_copy", "client_contact_email"]
    resource_id: str = Field(min_length=1, max_length=100)


class ExecuteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_request_id: str


class CommitmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_receipt: dict[str, Any]
    private_receipt: dict[str, Any]
    nonce: str = Field(min_length=64, max_length=64)


def register_privacy_routes(app, *, get_db, require_user, require_membership, require_principal,
                            require_party, audit, write_lock, signer, settlement_status):
    def no_store(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization, X-Session-Id"

    def admin(db, org_id, session_id, response):
        no_store(response)
        user = require_user(db, session_id)
        require_membership(db, org_id=org_id, user_id=user.id, allowed_roles={"owner", "admin"})
        return user

    def log(db, org_id, user, action, resource_id, details=None):
        audit(db, org_id=org_id, action=action, resource_type="data_privacy", resource_id=resource_id,
              actor_type="organization_member", actor_user_id=user.id, details=details or {})

    def case(db, org_id, request_id):
        row = db.get(PrivacyErasureRequestRecord, request_id)
        if not row or org_id not in row.required_org_ids:
            raise HTTPException(status_code=404, detail="Erasure request not found")
        return row

    @app.get("/v1/organizations/{org_id}/privacy")
    def get_settings(org_id: str, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        admin(db, org_id, x_session_id, response)
        return privacy.settings_response(db, org_id)

    @app.put("/v1/organizations/{org_id}/privacy")
    def put_settings(org_id: str, req: PrivacySettingsInput, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = admin(db, org_id, x_session_id, response)
        with write_lock(db):
            current = privacy.settings_for(db, org_id)
            if current["version"] != req.expected_version:
                raise HTTPException(status_code=409, detail="Privacy settings changed. Reload before saving.")
            row = db.get(OrganizationPrivacyRecord, org_id)
            if not row:
                row = OrganizationPrivacyRecord(org_id=org_id)
                db.add(row)
            row.publish_public_receipts = req.publish_public_receipts
            row.receipt_retention_days = req.receipt_retention_days
            row.legal_hold = req.legal_hold
            row.version = current["version"] + 1
            log(db, org_id, user, "privacy.settings.updated", org_id, {"version": row.version,
                "publicReceipts": row.publish_public_receipts, "retentionDays": row.receipt_retention_days,
                "legalHold": row.legal_hold})
            db.commit()
        return privacy.settings_response(db, org_id)

    @app.get("/v1/organizations/{org_id}/privacy/export")
    def export(org_id: str, resource: str, response: Response, cursor: str | None = Query(default=None, max_length=100),
               limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = admin(db, org_id, x_session_id, response)
        result = privacy.export_page(db, org_id, resource, cursor, limit)
        log(db, org_id, user, "privacy.export.created", org_id, {"resource": resource, "recordCount": len(result["records"])})
        db.commit()
        return result

    @app.get("/v1/organizations/{org_id}/privacy/requests")
    def list_requests(org_id: str, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        admin(db, org_id, x_session_id, response)
        receipts = db.query(ReceiptDisclosureRecord.receipt_id).filter(or_(ReceiptDisclosureRecord.authority_org_id == org_id, ReceiptDisclosureRecord.requester_org_id == org_id))
        rows = db.query(PrivacyErasureRequestRecord).filter(or_(PrivacyErasureRequestRecord.org_id == org_id,
            and_(PrivacyErasureRequestRecord.kind == "receipt_copy", PrivacyErasureRequestRecord.resource_id.in_(receipts)))).order_by(PrivacyErasureRequestRecord.created_at.desc()).all()
        return {"requests": [privacy.request_response(row) for row in rows]}

    @app.post("/v1/organizations/{org_id}/privacy/requests", status_code=201)
    def create_request(org_id: str, req: ErasureInput, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = admin(db, org_id, x_session_id, response)
        with write_lock(db):
            if req.kind == "receipt_copy":
                receipt, permission, claim = privacy.party_receipt(db, org_id, req.resource_id)
                if not receipt.payload: raise HTTPException(status_code=409, detail="The private receipt copy is already erased")
                required = sorted({claim.org_id, permission.requester_org_id})
                resource_hash = receipt.payload_hash
                if not db.get(ReceiptDisclosureRecord, receipt.id):
                    # Legacy copies gain retention/erasure tracking only. Their signed bytes stay intact.
                    plan = privacy.plan_disclosure(db, claim.org_id, permission.requester_org_id, now=receipt.created_at, legacy=True)
                    privacy.attach_disclosure(db, row=receipt, plan=plan, signer=signer)
            else:
                client = db.query(CatalogClientRecord).filter_by(id=req.resource_id, org_id=org_id).first()
                if not client: raise HTTPException(status_code=404, detail="Managed client not found")
                if not client.contact_email: raise HTTPException(status_code=409, detail="The client has no stored contact email")
                required = [org_id]
                resource_hash = sha256_hex(canonical_json(client.contact_email))
            existing = db.query(PrivacyErasureRequestRecord).filter_by(kind=req.kind, resource_id=req.resource_id,
                resource_hash=resource_hash, status="requested").first()
            if existing:
                db.commit()
                return privacy.request_response(existing)
            row = PrivacyErasureRequestRecord(id=str(uuid.uuid4()), org_id=org_id, kind=req.kind, resource_id=req.resource_id,
                resource_hash=resource_hash, required_org_ids=required, approved_org_ids=[], status="requested")
            db.add(row)
            for party in required:
                log(db, party, user, "privacy.erasure.requested", row.id, {"kind": req.kind})
            db.commit(); db.refresh(row)
            return privacy.request_response(row)

    @app.get("/v1/organizations/{org_id}/privacy/requests/{request_id}/preview")
    def preview(org_id: str, request_id: str, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        admin(db, org_id, x_session_id, response)
        return privacy.erasure_preview(db, case(db, org_id, request_id))

    @app.post("/v1/organizations/{org_id}/privacy/requests/{request_id}/approve")
    def approve(org_id: str, request_id: str, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = admin(db, org_id, x_session_id, response)
        with write_lock(db):
            row = case(db, org_id, request_id)
            if row.status == "completed": return privacy.request_response(row)
            if org_id not in row.approved_org_ids:
                row.approved_org_ids = sorted({*row.approved_org_ids, org_id})
                log(db, org_id, user, "privacy.erasure.approved", row.id)
            db.commit(); db.refresh(row)
            return privacy.request_response(row)

    @app.post("/v1/organizations/{org_id}/privacy/requests/{request_id}/execute")
    def execute(org_id: str, request_id: str, req: ExecuteInput, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = admin(db, org_id, x_session_id, response)
        if req.confirm_request_id != request_id:
            raise HTTPException(status_code=422, detail="Confirm the exact erasure request ID")
        with write_lock(db):
            row = case(db, org_id, request_id)
            if row.status == "completed":
                return {"request": privacy.request_response(row), "erased": [], "retained": privacy.RETAINED}
            result = privacy.erasure_preview(db, row)
            if not result["canExecute"]:
                raise HTTPException(status_code=409, detail={"message": "Erasure is blocked", "blockedBy": result["blockedBy"]})
            now = dt.datetime.utcnow()
            if row.kind == "receipt_copy":
                receipt = db.get(PermissionReceiptRecord, row.resource_id)
                disclosure = db.get(ReceiptDisclosureRecord, row.resource_id)
                # Delete the entire stored signed payload. Never present the tombstone as a signed receipt.
                receipt.payload = {}
                disclosure.commitment_nonce = None
                disclosure.erased_at = now
            else:
                db.get(CatalogClientRecord, row.resource_id).contact_email = None
            row.status = "completed"; row.completed_at = now
            for party in row.required_org_ids:
                log(db, party, user, "privacy.erasure.completed", row.id, {"kind": row.kind, "scope": "stored_copy"})
            db.commit(); db.refresh(row)
            return {"request": privacy.request_response(row), "erased": result["willErase"], "retained": result["retained"]}

    @app.post("/v1/organizations/{org_id}/privacy/receipts/{receipt_id}/withdraw-public")
    def withdraw(org_id: str, receipt_id: str, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = admin(db, org_id, x_session_id, response)
        with write_lock(db):
            privacy.party_receipt(db, org_id, receipt_id)
            row = db.get(ReceiptDisclosureRecord, receipt_id)
            if not row or not row.public_receipt: raise HTTPException(status_code=404, detail="No public receipt was issued")
            if not row.withdrawn_at:
                row.withdrawn_at = dt.datetime.utcnow()
                log(db, org_id, user, "privacy.public_receipt.withdrawn", receipt_id)
                db.commit()
            return {"withdrawn": True}

    @app.get("/v1/receipts/{receipt_id}/disclosure")
    def disclosure(receipt_id: str, response: Response, db: Session = Depends(get_db),
                   x_session_id: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        no_store(response)
        principal = require_principal(db, x_session_id=x_session_id, authorization=authorization)
        receipt = db.get(PermissionReceiptRecord, receipt_id)
        if not receipt: raise HTTPException(status_code=404, detail="Receipt not found")
        scope = "settlements:read" if receipt.schema_version == SETTLEMENT_SCHEMA_VERSION else "permissions:read"
        if principal.credential and scope not in set(principal.credential.scopes or []):
            raise HTTPException(status_code=403, detail=f"API credential requires scope {scope}")
        permission = db.get(PermissionRequestRecord, receipt.permission_request_id)
        if not permission: raise HTTPException(status_code=404, detail="Permission not found")
        from models import AuthorityClaimRecord
        claim = db.get(AuthorityClaimRecord, permission.authority_claim_id)
        require_party(db, principal=principal, permission=permission, claim=claim)
        row = db.get(ReceiptDisclosureRecord, receipt_id)
        if not row:
            return {"publicReceiptId": None, "publicUrl": None, "published": False, "withdrawn": False,
                    "privateCopyErased": not bool(receipt.payload), "retainUntil": None, "commitmentOpening": None}
        return privacy.disclosure_response(row)

    def published(db, public_id, response):
        response.headers["Cache-Control"] = "no-store"
        row = db.query(ReceiptDisclosureRecord).filter_by(public_id=public_id, withdrawn_at=None).first()
        if not row or not row.public_receipt: raise HTTPException(status_code=404, detail="Public receipt unavailable")
        return row

    @app.get("/v1/public/receipts/{public_id}")
    def public_receipt(public_id: str, response: Response, db: Session = Depends(get_db)):
        return published(db, public_id, response).public_receipt

    @app.get("/v1/public/receipts/{public_id}/status")
    def public_status(public_id: str, response: Response, db: Session = Depends(get_db)):
        row = published(db, public_id, response)
        receipt = db.get(PermissionReceiptRecord, row.receipt_id)
        permission = db.get(PermissionRequestRecord, receipt.permission_request_id)
        status = permission.status if permission else "unavailable"
        if status not in {"approved", "rejected", "pending", "revoked", "disputed", "corrected", "expired"}: status = "unavailable"
        recorded_status = status
        if status == "approved":
            try:
                if dt.date.fromisoformat(permission.term_end or "") < dt.datetime.utcnow().date():
                    status = "expired"
            except ValueError:
                status = "unavailable"
        result = {"publicReceiptId": row.public_id, "currentStatus": status,
                  "recordedPermissionStatus": recorded_status,
                  "privateCopyErased": bool(row.erased_at), "checkedAt": privacy.iso(dt.datetime.utcnow())}
        if receipt.receipt_kind == "settlement_reconciliation":
            result.update(settlement_status(db, receipt.id))
        return result

    @app.get("/v1/public/transparency/entries")
    def public_entries(response: Response, from_sequence: int = Query(default=1, ge=1), limit: int = Query(default=100, ge=1, le=1000), db: Session = Depends(get_db)):
        response.headers["Cache-Control"] = "no-store"
        rows = db.query(ReceiptDisclosureRecord).filter(ReceiptDisclosureRecord.public_sequence >= from_sequence).order_by(ReceiptDisclosureRecord.public_sequence).limit(limit).all()
        return {"entries": [row.public_receipt["transparency"] for row in rows]}

    @app.post("/v1/receipts/commitment/verify")
    def verify_opening(req: CommitmentInput, response: Response):
        no_store(response)
        return {"valid": privacy.verify_commitment(req.public_receipt, req.private_receipt, req.nonce)}
