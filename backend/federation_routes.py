"""Explicit catalog publication and live searches of a configured peer network."""
import asyncio
import datetime as dt
import secrets
import time
from types import SimpleNamespace
import uuid
from fastapi import Depends, Header, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import AuthorityClaimRecord, CatalogPublicationRecord, OrganizationRecord, RightsContractRecord
from services.federation import (ClosedModel, DESCRIPTOR_SCHEMA, DiscoveryPayload, FederationConfig, PeerSearchInput,
    PublicEntry, SCHEMA, SearchInput, STATEMENT_TTL, TERMS_SCHEMA, decode_key, query_peer, sign_discovery, validate_policy)
from services.receipts import canonical_json, sha256_hex


class PublicationPreviewInput(ClosedModel):
    authority_claim_id: str = Field(min_length=1, max_length=100)


class PublicationInput(PublicationPreviewInput):
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_publication: bool


class WithdrawalInput(ClosedModel):
    expected_revision: int = Field(ge=1)


def register_federation_routes(app, *, settings, signer, get_db, require_user, require_membership,
                               require_principal, audit, write_lock, vocabulary, default_ai_policy):
    config = FederationConfig.from_settings(settings, signer)
    app.state.federation_config = config
    if settings.NODE_NEXT_SIGNING_PUBLIC_KEY_B64:
        decode_key(settings.NODE_NEXT_SIGNING_PUBLIC_KEY_B64)

    def enabled(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Authorization, X-Session-Id"
        current = app.state.federation_config
        if not current.enabled:
            raise HTTPException(404, "Catalog federation is not enabled on this node")
        return current

    def admin(db, org_id, token, response):
        enabled(response)
        user = require_user(db, token)
        require_membership(db, org_id=org_id, user_id=user.id, allowed_roles={"owner", "admin"})
        return user

    def own_claim(db, org_id, claim_id, *, lock=False):
        query = db.query(AuthorityClaimRecord).filter_by(id=claim_id, org_id=org_id)
        claim = (query.with_for_update() if lock else query).first()
        if not claim:
            raise HTTPException(404, "Authority claim not found")
        return claim

    def projection(db, claim, revision):
        contract = db.get(RightsContractRecord, claim.rights_contract_id)
        org = db.get(OrganizationRecord, claim.org_id)
        if not contract or not org or contract.owner_org_id != claim.org_id or claim.status != "verified":
            raise HTTPException(409, "Publication requires current verified authority for this organization's policy")
        raw = contract.contract_json or {}
        matrix = contract.effective_matrix or {}
        ai = raw.get("aiPolicy") or default_ai_policy("blocked")
        policy = {}
        for section, keys in vocabulary.items():
            source = matrix if section in {"usage", "restrictions"} else ai
            fallback = None if section == "limits" else True if section == "safeguards" else "denied" if section == "restrictions" else "blocked"
            policy[section] = {key: (source.get(section) or {}).get(key, fallback) for key in keys}
        # Stored policies may hold 30.0; publication carries whole numbers only.
        policy["limits"] = {key: int(value) if type(value) is float and value.is_integer() else value
                            for key, value in policy["limits"].items()}
        metadata = raw.get("metadata") or {}
        references = {"isrc": metadata.get("recordingIsrc"), "iswc": metadata.get("compositionIswc")}
        if claim.work_key.startswith("isrc:"):
            references["isrc"] = claim.work_key[5:]
        if claim.work_key.startswith("iswc:"):
            references["iswc"] = claim.work_key[5:]
        try:
            validate_policy(policy, vocabulary)
            payload = PublicEntry.model_validate({
                "publicationId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"clef:publication:{claim.id}")),
                "organization": {"id": org.id, "name": org.name}, "authorityClaimId": claim.id,
                "workKey": claim.work_key, "workTitle": metadata.get("workTitle") or claim.work_key,
                "artistName": contract.artist, "rightType": claim.right_type, "territory": claim.territory,
                "policyVersion": contract.version, "publicationRevision": revision,
                "synthetic": metadata.get("synthetic") is True,
                "catalogReferences": references, "policy": policy,
            }).model_dump()
        except (ValueError, ValidationError) as error:
            raise HTTPException(409, "Review the catalog identifiers and policy fields before publishing") from error
        if not any(state != "blocked" for state in policy["usage"].values()):
            raise HTTPException(409, "This policy blocks every use; update it before publishing availability")
        # Private evidence affects freshness without becoming a public search field.
        basis = sha256_hex(canonical_json({"claim": {"status": claim.status, "evidence": claim.evidence},
            "contract": raw, "payload": payload}))
        return payload, basis

    def next_preview(db, org_id, claim_id, *, lock=False):
        claim = own_claim(db, org_id, claim_id, lock=lock)
        if lock:
            db.query(RightsContractRecord).filter_by(id=claim.rights_contract_id).with_for_update().first()
        row = db.query(CatalogPublicationRecord).filter_by(authority_claim_id=claim.id).first()
        revision = row.revision + 1 if row else 1
        payload, basis = projection(db, claim, revision)
        return row, payload, basis

    def current_payload(db, row):
        if row.withdrawn_at:
            return None
        claim = db.get(AuthorityClaimRecord, row.authority_claim_id)
        if not claim or claim.org_id != row.org_id:
            return None
        try:
            payload, basis = projection(db, claim, row.revision)
        except HTTPException:
            return None
        return payload if basis == row.basis_hash and payload == row.public_payload else None

    def describe(db, row):
        current = current_payload(db, row)
        return {"id": row.id, "authorityClaimId": row.authority_claim_id,
                "revision": row.revision, "status": "withdrawn" if row.withdrawn_at else "published" if current else "needs_review",
                "publicFields": current or row.public_payload,
                "approvedAt": row.approved_at, "withdrawnAt": row.withdrawn_at}

    def log(db, org_id, user, action, row, digest=None):
        audit(db, org_id=org_id, actor_type="organization_member", actor_user_id=user.id,
            action=action, resource_type="catalog_publication", resource_id=row.id,
            details={"revision": row.revision, "publicFieldsHash": digest})

    @app.get("/v1/organizations/{org_id}/catalog/publications")
    def publications(org_id: str, response: Response, cursor: str | None = Query(default=None, max_length=100),
                     limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        admin(db, org_id, x_session_id, response)
        query = db.query(CatalogPublicationRecord).filter_by(org_id=org_id)
        if cursor:
            if not query.filter_by(id=cursor).first():
                raise HTTPException(404, "Publication cursor not found in this organization")
            query = query.filter(CatalogPublicationRecord.id > cursor)
        rows = query.order_by(CatalogPublicationRecord.id).limit(limit + 1).all()
        page = rows[:limit]
        return {"publications": [describe(db, row) for row in page],
                "nextCursor": page[-1].id if len(rows) > limit else None}

    @app.post("/v1/organizations/{org_id}/catalog/publications/preview")
    def preview(org_id: str, req: PublicationPreviewInput, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        admin(db, org_id, x_session_id, response)
        _, payload, basis = next_preview(db, org_id, req.authority_claim_id)
        return {"publicFields": payload, "previewDigest": basis,
                "distribution": "Public catalog search on this node and its connected peers",
                "freshnessSeconds": STATEMENT_TTL}

    @app.post("/v1/organizations/{org_id}/catalog/publications")
    def publish(org_id: str, req: PublicationInput, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = admin(db, org_id, x_session_id, response)
        if not req.confirm_publication:
            raise HTTPException(422, "Confirm the public fields shown in the preview")
        with write_lock(db):
            row, payload, basis = next_preview(db, org_id, req.authority_claim_id, lock=True)
            # An exact retry succeeds only while its previously consented publication is still current.
            if row and not row.withdrawn_at and req.preview_digest == row.basis_hash and current_payload(db, row):
                return describe(db, row)
            if req.preview_digest != basis:
                raise HTTPException(409, "The publication or policy changed. Review a fresh preview.")
            if not row:
                row = CatalogPublicationRecord(id=payload["publicationId"], org_id=org_id, authority_claim_id=req.authority_claim_id)
                db.add(row)
            row.public_payload = payload
            row.search_text = " ".join([payload["workTitle"], payload["artistName"], payload["workKey"],
                payload["organization"]["name"], *[v for v in payload["catalogReferences"].values() if v]]).casefold()
            row.basis_hash = basis; row.revision = payload["publicationRevision"]
            row.approved_by_user_id = user.id; row.approved_at = dt.datetime.utcnow(); row.withdrawn_at = None
            log(db, org_id, user, "catalog.publication.approved", row, sha256_hex(canonical_json(payload)))
            try:
                db.commit()
            except IntegrityError as error:
                db.rollback()
                raise HTTPException(409, "Publication changed. Reload before publishing.") from error
            return describe(db, row)

    @app.post("/v1/organizations/{org_id}/catalog/publications/{publication_id}/withdraw")
    def withdraw(org_id: str, publication_id: str, req: WithdrawalInput, response: Response, db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)):
        user = admin(db, org_id, x_session_id, response)
        with write_lock(db):
            row = db.query(CatalogPublicationRecord).filter_by(id=publication_id, org_id=org_id).with_for_update().first()
            if not row:
                raise HTTPException(404, "Publication not found")
            if row.revision != req.expected_revision:
                raise HTTPException(409, "Publication changed. Reload before withdrawing.")
            if not row.withdrawn_at:
                log(db, org_id, user, "catalog.publication.withdrawn", row, sha256_hex(canonical_json(row.public_payload)))
                row.withdrawn_at = dt.datetime.utcnow()
                # Retain the consent digest and audit event; clear the distributed projection here.
                row.public_payload = {}; row.search_text = ""
                db.commit()
            return describe(db, row)

    def local_statement(db, request, current):
        # A bounded candidate window makes query cost explicit even when old publications need review.
        rows = db.query(CatalogPublicationRecord).filter(CatalogPublicationRecord.withdrawn_at.is_(None),
            CatalogPublicationRecord.search_text.contains(request.query.casefold(), autoescape=True)).order_by(CatalogPublicationRecord.id).limit(201).all()
        entries = []
        for row in rows[:200]:
            payload = current_payload(db, row)
            if payload:
                entries.append(payload)
        now = int(time.time())
        payload = DiscoveryPayload(schemaVersion=SCHEMA, nodeId=signer.node_id, origin=current.origin,
            query=request.query, nonce=request.nonce, issuedAt=now, expiresAt=now + STATEMENT_TTL,
            truncated=len(rows) > 200 or len(entries) > request.limit, entries=entries[:request.limit])
        return sign_discovery(signer, payload)

    def advertise(response):
        response.headers["Link"] = '</.well-known/clef-node>; rel="describedby"'

    @app.post("/v1/federation/catalog/search")
    def public_search(req: PeerSearchInput, response: Response, db: Session = Depends(get_db)):
        current = enabled(response)
        advertise(response)
        return local_statement(db, req, current)

    @app.get("/v1/public/catalog/publications/{publication_id}")
    def public_terms(publication_id: str, response: Response, db: Session = Depends(get_db)):
        """The signed public terms of one published entry, readable without an account."""
        current = enabled(response)
        advertise(response)
        row = db.get(CatalogPublicationRecord, publication_id)
        entry = current_payload(db, row) if row else None
        if not entry:
            raise HTTPException(404, "No current publication with that ID on this node")
        now = int(time.time())
        return signer.sign_statement({"schemaVersion": TERMS_SCHEMA, "nodeId": signer.node_id, "origin": current.origin,
            "issuedAt": now, "expiresAt": now + STATEMENT_TTL, "entry": entry,
            "requests": {"acceptsFrom": "configured-peer-nodes-and-local-accounts",
                         "peerEndpoint": "/v1/federation/inbound/permission-requests",
                         "localEndpoint": "/v1/permission-requests"}})

    @app.get("/.well-known/clef-node")
    def descriptor(response: Response):
        current = enabled(response)
        now = int(time.time())
        keys = [{"keyId": signer.key_id, "publicKey": signer.public_key_b64, "status": "current"}]
        if settings.NODE_NEXT_SIGNING_PUBLIC_KEY_B64:
            keys.append({"publicKey": settings.NODE_NEXT_SIGNING_PUBLIC_KEY_B64, "status": "next"})
        return signer.sign_statement({"schemaVersion": DESCRIPTOR_SCHEMA, "nodeId": signer.node_id,
            "origin": current.origin, "issuedAt": now, "expiresAt": now + 3600, "keys": keys,
            "protocols": [SCHEMA, TERMS_SCHEMA, "clef.permission-request.v1", "clef.permission-status-query.v1",
                          "clef.permission-status.v1"],
            "endpoints": {"catalogSearch": "/v1/federation/catalog/search",
                          "publicTerms": "/v1/public/catalog/publications/{publicationId}",
                          "permissionRequests": "/v1/federation/inbound/permission-requests",
                          "permissionStatus": "/v1/federation/inbound/permission-requests/status"},
            "trust": "Requests are accepted only from peer nodes this operator configured with pinned keys. "
                     "A valid signature identifies the signing node; it does not establish ownership."})

    @app.post("/v1/federation/search")
    async def search(req: SearchInput, response: Response, db: Session = Depends(get_db),
                     x_session_id: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        current = enabled(response)
        # Database and signing work stays off the event loop that waits on peers.
        await run_in_threadpool(require_principal, db, x_session_id=x_session_id, authorization=authorization,
                                required_scope="directory:read" if authorization else None)
        request = PeerSearchInput(**req.model_dump(), nonce=secrets.token_urlsafe(32))
        own = await run_in_threadpool(local_statement, db, request, current)
        # Release the read transaction before waiting on network peers.
        await run_in_threadpool(db.rollback)
        peers = await asyncio.gather(*[query_peer(peer, request, vocabulary, allow_loopback=current.allow_loopback) for peer in current.peers])
        sources = [{"id": "local", "nodeId": signer.node_id, "origin": current.origin, "status": "ok",
                    "entries": own["payload"]["entries"], "statement": own,
                    "expiresAt": own["payload"]["expiresAt"], "truncated": own["payload"]["truncated"]}, *peers]
        return {"query": req.query, "checkedAt": int(time.time()), "partial": any(p["status"] != "ok" for p in peers),
                "truncated": any(p.get("truncated", False) for p in sources), "sources": sources,
                "results": [{"entry": entry, "source": {k: source[k] for k in ("id", "nodeId", "origin", "expiresAt")}}
                            for source in sources for entry in source["entries"]]}

    return SimpleNamespace(current_payload=current_payload)
