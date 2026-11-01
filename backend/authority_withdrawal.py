"""Human withdrawal of an organization's own authority assertion."""
import datetime as dt
from collections import Counter
from fastapi import Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session
from models import AuthorityClaimRecord, AuditEventRecord, PermissionRequestRecord
from services.receipts import canonical_json, sha256_hex

ACTION = "authority_claim.withdrawn"
WITHDRAWABLE = {"self_asserted", "verified", "disputed"}


class WithdrawalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=2000)
    confirm_withdrawal: bool

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value):
        if not value.strip():
            raise ValueError("A concise withdrawal reason is required")
        return value.strip()


def claim_digest(claim):
    return sha256_hex(canonical_json({"id": claim.id, "orgId": claim.org_id,
        "policyId": claim.rights_contract_id, "workKey": claim.work_key, "rightType": claim.right_type,
        "territory": claim.territory, "status": claim.status, "evidence": claim.evidence,
        "reviewedAt": claim.reviewed_at.isoformat() if claim.reviewed_at else None,
        "verifiedAt": claim.verified_at.isoformat() if claim.verified_at else None,
        "revokedAt": claim.revoked_at.isoformat() if claim.revoked_at else None}))


def register_authority_withdrawal(app, *, get_db, require_user, require_membership, audit, write_lock):
    def authorized(db, org_id, token, response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization, X-Session-Id"
        user = require_user(db, token)
        require_membership(db, org_id=org_id, user_id=user.id, allowed_roles={"owner", "admin", "rights_manager"})
        return user

    def own_claim(db, org_id, claim_id, *, lock=False):
        query = db.query(AuthorityClaimRecord).filter_by(id=claim_id, org_id=org_id)
        row = (query.with_for_update() if lock else query).first()
        if not row:
            raise HTTPException(404, "Authority claim not found in this organization")
        return row

    def describe(db, claim):
        counts = Counter(status for (status,) in db.query(PermissionRequestRecord.status).filter_by(authority_claim_id=claim.id).all())
        return {"claimId": claim.id, "status": claim.status, "workKey": claim.work_key,
                "rightType": claim.right_type, "territory": claim.territory,
                "canWithdraw": claim.status in WITHDRAWABLE, "expectedDigest": claim_digest(claim),
                "pendingRequests": counts["pending"], "approvedGrants": counts["approved"],
                "revokedAt": claim.revoked_at}

    @app.get("/v1/organizations/{org_id}/authority-claims/{claim_id}/withdrawal-preview")
    def preview(org_id: str, claim_id: str, response: Response, db: Session = Depends(get_db),
                x_session_id: str | None = Header(default=None)):
        authorized(db, org_id, x_session_id, response)
        return describe(db, own_claim(db, org_id, claim_id))

    @app.post("/v1/organizations/{org_id}/authority-claims/{claim_id}/withdraw")
    def withdraw(org_id: str, claim_id: str, req: WithdrawalInput, response: Response, db: Session = Depends(get_db),
                 x_session_id: str | None = Header(default=None)):
        user = authorized(db, org_id, x_session_id, response)
        if not req.confirm_withdrawal:
            raise HTTPException(422, "Confirm withdrawal of this authority assertion")
        with write_lock(db):
            claim = own_claim(db, org_id, claim_id, lock=True)
            if claim.status == "revoked":
                previous = db.query(AuditEventRecord).filter_by(org_id=org_id, action=ACTION, resource_id=claim.id).order_by(AuditEventRecord.created_at.desc()).first()
                if previous and previous.details.get("previousDigest") == req.expected_digest and previous.details.get("reason") == req.reason:
                    return describe(db, claim)
                raise HTTPException(409, "This authority assertion is already revoked; review its history")
            if claim.status not in WITHDRAWABLE or claim_digest(claim) != req.expected_digest:
                raise HTTPException(409, "The authority record changed. Review a fresh withdrawal preview.")
            before = describe(db, claim)
            claim.status = "revoked"
            claim.revoked_at = dt.datetime.utcnow()
            # Original evidence-review attribution and all grant receipts remain intact.
            audit(db, org_id=org_id, action=ACTION, resource_type="authority_claim", resource_id=claim.id,
                  actor_type="organization_member", actor_user_id=user.id,
                  details={"previousDigest": req.expected_digest, "previousStatus": before["status"], "reason": req.reason,
                           "pendingRequests": before["pendingRequests"], "approvedGrants": before["approvedGrants"]})
            db.commit()
            return describe(db, claim)
