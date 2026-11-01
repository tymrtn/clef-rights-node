"""Permission requests between configured nodes.

The requester's node signs the request; the source node decides it under its
own policy and answers with a signed status that carries its receipts. Buyer
sessions and credentials never leave the requester's node.
"""
import datetime as dt
import hashlib
import secrets
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from fastapi import Body, Depends, Header, HTTPException, Query, Response
from pydantic import Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (AuthorityClaimRecord, CatalogPublicationRecord, FederatedInboundRequestRecord, FederatedOutboundRequestRecord,
    OrganizationMembershipRecord, OrganizationRecord, PermissionReceiptRecord, PermissionRequestRecord)
from services.federation import (ClosedModel, MAX_BYTES, MAX_REQUEST_BYTES, PermissionRequestPayload,
    PermissionStatusPayload, PeerBusy, PeerRejected, REQUEST_SCHEMA, REQUEST_TIMEOUT, REQUEST_TTL, STATUS_QUERY_SCHEMA,
    STATUS_SCHEMA, StatusQueryPayload, check_window, peer_post, reserved, verify_peer_signature, verify_status)
from services.receipts import canonical_json, sha256_hex

LIFECYCLE_KINDS = ("grant", "dispute", "revocation", "correction", "expiry")
MAX_STATUS_RECEIPTS = 20
# Outbound states before the source has answered with a verified status.
UNCONFIRMED = {"sending", "unconfirmed", "not_received"}
# Client errors that say "try again" rather than "no".
RETRYABLE = {408, 425, 429}


def utc(value):
    return value.replace(microsecond=0).isoformat() + "Z" if value else None


class OutboundRequestInput(ClosedModel):
    source_id: str = Field(min_length=1, max_length=60)
    publication_id: str = Field(min_length=1, max_length=100)
    requester_org_id: str = Field(min_length=1, max_length=100)
    intended_usage: str = Field(min_length=1, max_length=100)
    territory: str = Field(default="worldwide", min_length=1, max_length=500)
    term_start: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    term_end: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    context: dict[str, Any] = Field(default_factory=dict)


def register_federated_request_routes(app, *, signer, get_db, require_principal, require_principal_org,
                                      submit_request, serialize_receipt, write_lock, current_publication):
    def enabled(response):
        response.headers["Cache-Control"] = "no-store"
        current = app.state.federation_config
        if not current.enabled:
            raise HTTPException(404, "Catalog federation is not enabled on this node")
        return current

    def configured_peer(current, *, node_id=None, peer_id=None):
        for peer in current.peers:
            if (node_id and peer.node_id == node_id) or (peer_id and peer.id == peer_id):
                return peer
        return None

    # --- Source node: requests arriving from configured peers ---

    def verified_from_peer(current, statement, model, schema):
        """Identify the claimed requester node, then require that peer's pinned signature."""
        try:
            size = len(canonical_json(statement))
        except ValueError as error:
            raise HTTPException(422, "Signed statements use finite JSON numbers") from error
        if size > MAX_REQUEST_BYTES:
            raise HTTPException(413, "Signed requests are limited to 64 KiB")
        payload = statement.get("payload")
        node = payload.get("requesterNode") if isinstance(payload, dict) else None
        claimed = node.get("nodeId") if isinstance(node, dict) else None
        peer = configured_peer(current, node_id=claimed) if isinstance(claimed, str) else None
        if not peer:
            raise HTTPException(403, "This node accepts requests only from its configured peer nodes")
        try:
            verify_peer_signature(statement, peer)
            payload = model.model_validate(statement["payload"]).model_dump()
            check_window(payload["issuedAt"], payload["expiresAt"], REQUEST_TTL)
        except (ValueError, ValidationError, InvalidSignature) as error:
            raise HTTPException(401, "The signed statement did not verify against the configured peer") from error
        if (payload["schemaVersion"] != schema or payload["requesterNode"]["origin"] != peer.origin
                or payload["sourceNodeId"] != signer.node_id):
            raise HTTPException(401, "The signed statement names another node")
        return peer, payload

    def requester_organization(db, peer, requester):
        """A peer's organization is represented here by a member-less requester organization."""
        digest = hashlib.sha256(f"{peer.node_id}\0{requester['id']}".encode()).hexdigest()[:24]
        slug = f"peer-{digest}"
        org = db.query(OrganizationRecord).filter_by(slug=slug).first()
        if org and (((org.profile or {}).get("federation") or {}).get("peerNodeId") != peer.node_id
                    or org.profile["federation"].get("remoteOrganizationId") != requester["id"]
                    or db.query(OrganizationMembershipRecord).filter_by(org_id=org.id).first()):
            # Local creation reserves peer- slugs; anything else here predates that guard or was altered.
            raise HTTPException(409, "This node's record for the requesting organization is inconsistent; its operator must review it")
        if not org:
            org = OrganizationRecord(slug=slug, name=requester["name"], created_by_user_id=None, profile={
                "organizationType": "requester",
                "federation": {"peerNodeId": peer.node_id, "origin": peer.origin, "remoteOrganizationId": requester["id"]}})
            db.add(org); db.flush()
        elif org.name != requester["name"]:
            org.name = requester["name"]
        return org

    def status_statement(db, inbound, nonce=None):
        permission = db.get(PermissionRequestRecord, inbound.permission_request_id)
        rows = (db.query(PermissionReceiptRecord)
            .filter(PermissionReceiptRecord.permission_request_id == permission.id,
                    PermissionReceiptRecord.receipt_kind.in_(LIFECYCLE_KINDS))
            .order_by(PermissionReceiptRecord.transparency_sequence).all())
        # An erased private copy is withheld here exactly as it is from a local party.
        receipts = [serialize_receipt(row) for row in rows if row.payload]
        now = int(time.time())
        while True:
            # The newest receipts carry the current state, so older ones give way to the size limits first.
            kept = receipts[-MAX_STATUS_RECEIPTS:] if receipts else []
            payload = PermissionStatusPayload(schemaVersion=STATUS_SCHEMA, nodeId=signer.node_id,
                origin=app.state.federation_config.origin, requestId=inbound.request_id, requesterNodeId=inbound.peer_node_id,
                nonce=nonce, permissionRequestId=permission.id, status=permission.status,
                policyState=((permission.context or {}).get("policyEvaluation") or {}).get("state"),
                decidedAt=permission.decided_at.replace(microsecond=0).isoformat() + "Z" if permission.decided_at else None,
                decisionNote=permission.decision_note, receipts=kept, receiptsOmitted=len(rows) - len(kept),
                issuedAt=now, expiresAt=now + REQUEST_TTL).model_dump()
            statement = signer.sign_statement(payload)
            if len(canonical_json(statement)) <= MAX_BYTES:
                return statement
            if not kept:
                raise HTTPException(507, "This request's status exceeds the federation transport budget")
            receipts = kept[1:]

    @app.post("/v1/federation/inbound/permission-requests")
    def inbound_request(response: Response, statement: dict = Body(...), db: Session = Depends(get_db)):
        current = enabled(response)
        peer, payload = verified_from_peer(current, statement, PermissionRequestPayload, REQUEST_SCHEMA)
        statement_hash = sha256_hex(canonical_json(statement))

        def replay():
            existing = db.query(FederatedInboundRequestRecord).filter_by(
                peer_node_id=peer.node_id, request_id=payload["requestId"]).first()
            if existing and existing.statement_hash != statement_hash:
                raise HTTPException(409, "This request ID was already used for a different request")
            return existing

        with write_lock(db):
            existing = replay()
            if existing:
                return status_statement(db, existing)
            publication = locked_current(db, payload["publicationId"])

            def bind(permission):
                db.add(FederatedInboundRequestRecord(peer_node_id=peer.node_id, request_id=payload["requestId"],
                    statement_hash=statement_hash, statement=statement, permission_request_id=permission.id))
                db.flush()

            try:
                org = requester_organization(db, peer, payload["requester"])
                submit_request(db, requester_org_id=org.id, authority_claim_id=publication.authority_claim_id,
                    intended_usage=payload["intendedUsage"], territory=payload["territory"],
                    term_start=payload["termStart"], term_end=payload["termEnd"], context=payload["context"],
                    provenance={"federation": {"peerNodeId": peer.node_id, "requestId": payload["requestId"],
                                               "requestStatementHash": statement_hash,
                                               "publicationId": publication.id,
                                               "publicationRevision": publication.revision}},
                    peer_node_id=peer.node_id, bind_record=bind)
            except IntegrityError:
                # A concurrent delivery of the same request committed first.
                db.rollback()
                existing = replay()
                if not existing:
                    raise HTTPException(503, "The request conflicted with a concurrent change. Retry it.")
            inbound = db.query(FederatedInboundRequestRecord).filter_by(
                peer_node_id=peer.node_id, request_id=payload["requestId"]).one()
            return status_statement(db, inbound)

    @app.post("/v1/federation/inbound/permission-requests/status")
    def inbound_status(response: Response, statement: dict = Body(...), db: Session = Depends(get_db)):
        current = enabled(response)
        peer, payload = verified_from_peer(current, statement, StatusQueryPayload, STATUS_QUERY_SCHEMA)
        inbound = db.query(FederatedInboundRequestRecord).filter_by(
            peer_node_id=peer.node_id, request_id=payload["requestId"]).first()
        if not inbound:
            raise HTTPException(404, "This node has no request with that ID from the asking peer")
        return status_statement(db, inbound, nonce=payload["nonce"])

    def locked_current(db, publication_id):
        """Check, lock claim then publication (the order publication changes use), and check again."""
        publication = db.get(CatalogPublicationRecord, publication_id)
        if not publication or not current_publication(db, publication):
            raise HTTPException(409, "This catalog entry is not currently published")
        db.query(AuthorityClaimRecord).filter_by(id=publication.authority_claim_id).with_for_update().first()
        publication = (db.query(CatalogPublicationRecord).filter_by(id=publication_id)
                       .with_for_update().populate_existing().first())
        if not publication or not current_publication(db, publication):
            raise HTTPException(409, "This catalog entry is not currently published")
        return publication

    # --- Requester node: requests this node signs for its organizations ---

    def describe(row):
        status = (row.status_statement or {}).get("payload") or {}
        return {"id": row.id, "sourceId": row.peer_id, "sourceNodeId": row.peer_node_id, "sourceOrigin": row.peer_origin,
                "publicationId": row.publication_id, "requesterOrgId": row.requester_org_id, "status": row.status,
                "remotePermissionId": row.remote_permission_id, "receipts": status.get("receipts", []),
                "decisionNote": status.get("decisionNote"), "decidedAt": status.get("decidedAt"),
                "policyState": status.get("policyState"), "requestStatement": row.request_statement,
                "statusStatement": row.status_statement, "createdAt": utc(row.created_at), "refreshedAt": utc(row.refreshed_at)}

    def exchange(db, row, peer, current, path, body):
        """Send one signed statement and record only a verified answer as the request's status."""
        # Return the database connection to the pool while waiting on the network.
        db.commit()
        try:
            with reserved(peer):
                answer = peer_post(peer, path, canonical_json(body), allow_loopback=current.allow_loopback,
                                   timeout=REQUEST_TIMEOUT, reject_detail=True)
            nonce = body["payload"].get("nonce") if body["payload"]["schemaVersion"] == STATUS_QUERY_SCHEMA else None
            status = verify_status(answer, peer, request_id=row.id, requester_node_id=signer.node_id, nonce=nonce)
        except PeerBusy as error:
            raise HTTPException(503, "This node is already waiting on that source. Try again shortly.") from error
        except PeerRejected as error:
            if error.status in RETRYABLE:
                if row.status == "sending":
                    row.status = "unconfirmed"
                row.refreshed_at = dt.datetime.utcnow(); db.commit()
                raise HTTPException(502, f"The source node asked this node to retry later: {error.detail}") from error
            if error.status == 404 and row.status in UNCONFIRMED:
                row.status = "not_received"
            elif row.status in UNCONFIRMED:
                row.status = "not_accepted"
                row.status_statement = {"declined": {"httpStatus": error.status, "detail": error.detail}}
            row.refreshed_at = dt.datetime.utcnow(); db.commit()
            raise HTTPException(409, f"The source node answered: {error.detail}") from error
        except (ValueError, OSError, InvalidSignature, ValidationError) as error:
            if row.status == "sending":
                row.status = "unconfirmed"
            row.refreshed_at = dt.datetime.utcnow(); db.commit()
            raise HTTPException(502, "The source node did not return a verifiable answer. Refresh to retry.") from error
        row.status = status["status"]; row.remote_permission_id = status["permissionRequestId"]
        row.status_statement = answer; row.refreshed_at = dt.datetime.utcnow()
        db.commit()
        return describe(row)

    def own_row(db, principal, request_id, scope):
        row = db.get(FederatedOutboundRequestRecord, request_id)
        if not row:
            raise HTTPException(404, "Federated request not found")
        require_principal_org(db, principal=principal, org_id=row.requester_org_id,
                              required_scope=scope if principal.credential else None)
        return row

    @app.post("/v1/federation/permission-requests")
    def send_request(req: OutboundRequestInput, response: Response, db: Session = Depends(get_db),
                     x_session_id: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        current = enabled(response)
        principal = require_principal(db, x_session_id=x_session_id, authorization=authorization,
                                      required_scope="permissions:request" if authorization else None)
        require_principal_org(db, principal=principal, org_id=req.requester_org_id,
                              required_scope="permissions:request" if principal.credential else None)
        org = db.get(OrganizationRecord, req.requester_org_id)
        if (org.profile or {}).get("federation"):
            raise HTTPException(403, "An organization represented from another node cannot send requests from here")
        if req.source_id == "local":
            with write_lock(db):
                publication = locked_current(db, req.publication_id)
                result = submit_request(db, requester_org_id=org.id, authority_claim_id=publication.authority_claim_id,
                    intended_usage=req.intended_usage, territory=req.territory, term_start=req.term_start,
                    term_end=req.term_end, context=req.context, provenance={}, principal=principal)
            return {"source": "local", **result}
        peer = configured_peer(current, peer_id=req.source_id)
        if not peer:
            raise HTTPException(404, "That source is not a configured peer of this node")
        now = int(time.time())
        try:
            payload = PermissionRequestPayload(schemaVersion=REQUEST_SCHEMA, requestId=secrets.token_urlsafe(24),
                requesterNode={"nodeId": signer.node_id, "origin": current.origin}, sourceNodeId=peer.node_id,
                requester={"id": org.id, "name": org.name}, publicationId=req.publication_id,
                intendedUsage=req.intended_usage, territory=req.territory, termStart=req.term_start,
                termEnd=req.term_end, context=req.context, issuedAt=now, expiresAt=now + REQUEST_TTL).model_dump()
        except ValidationError as error:
            raise HTTPException(422, "Review the request fields before sending") from error
        statement = signer.sign_statement(payload)
        if len(canonical_json(statement)) > MAX_REQUEST_BYTES:
            raise HTTPException(413, "Signed requests are limited to 64 KiB")
        # Record the signed intent before the network call, so an interrupted send stays inspectable.
        row = FederatedOutboundRequestRecord(id=payload["requestId"], requester_org_id=org.id, peer_id=peer.id,
            peer_node_id=peer.node_id, peer_origin=peer.origin, publication_id=req.publication_id,
            request_statement=statement, status="sending",
            requested_by_user_id=principal.user.id if principal.user else None,
            requested_by_api_credential_id=principal.credential.id if principal.credential else None)
        db.add(row); db.commit()
        return exchange(db, row, peer, current, "/v1/federation/inbound/permission-requests", statement)

    @app.get("/v1/organizations/{org_id}/federation/permission-requests")
    def list_requests(org_id: str, response: Response, limit: int = Query(default=50, ge=1, le=200),
                      db: Session = Depends(get_db), x_session_id: str | None = Header(default=None),
                      authorization: str | None = Header(default=None)):
        enabled(response)
        principal = require_principal(db, x_session_id=x_session_id, authorization=authorization,
                                      required_scope="permissions:read" if authorization else None)
        require_principal_org(db, principal=principal, org_id=org_id,
                              required_scope="permissions:read" if principal.credential else None)
        rows = (db.query(FederatedOutboundRequestRecord).filter_by(requester_org_id=org_id)
                .order_by(FederatedOutboundRequestRecord.created_at.desc()).limit(limit).all())
        return {"requests": [describe(row) for row in rows]}

    @app.get("/v1/federation/permission-requests/{request_id}")
    def get_request(request_id: str, response: Response, db: Session = Depends(get_db),
                    x_session_id: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        enabled(response)
        principal = require_principal(db, x_session_id=x_session_id, authorization=authorization,
                                      required_scope="permissions:read" if authorization else None)
        return describe(own_row(db, principal, request_id, "permissions:read"))

    @app.post("/v1/federation/permission-requests/{request_id}/refresh")
    def refresh_request(request_id: str, response: Response, db: Session = Depends(get_db),
                        x_session_id: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        current = enabled(response)
        principal = require_principal(db, x_session_id=x_session_id, authorization=authorization,
                                      required_scope="permissions:read" if authorization else None)
        row = own_row(db, principal, request_id, "permissions:read")
        peer = configured_peer(current, node_id=row.peer_node_id)
        if not peer:
            raise HTTPException(409, "That source is no longer a configured peer of this node")
        sent = row.request_statement["payload"]
        if row.status in UNCONFIRMED and sent["expiresAt"] > int(time.time()):
            # The source treats an identical signed request as the same request.
            return exchange(db, row, peer, current, "/v1/federation/inbound/permission-requests", row.request_statement)
        now = int(time.time())
        query = StatusQueryPayload(schemaVersion=STATUS_QUERY_SCHEMA, requestId=row.id,
            requesterNode={"nodeId": signer.node_id, "origin": current.origin}, sourceNodeId=peer.node_id,
            nonce=secrets.token_urlsafe(32), issuedAt=now, expiresAt=now + REQUEST_TTL).model_dump()
        return exchange(db, row, peer, current, "/v1/federation/inbound/permission-requests/status",
                        signer.sign_statement(query))
