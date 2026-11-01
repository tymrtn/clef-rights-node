"""Signed permission requests between configured nodes, decided by the source node's own policy.

One app plays both nodes: the peer pin is this node's own key and peer_post is routed
through the test client, so every statement is still signed, sent as bytes and verified.
The separate-process proof lives in scripts/run_federation_preview.py --verify.
"""
import copy
import datetime
import time
import uuid

import pytest
import federated_requests
from models import AuditEventRecord, CatalogPublicationRecord, FederatedInboundRequestRecord, OrganizationRecord, PermissionRequestRecord
from services import federation
from services.federation import FederationConfig, Peer, PeerRejected
from services.receipts import ReceiptSigner, canonical_json
from test_api import app, client, SessionLocal, receipt_signer
from test_federation import connected, preview_and_publish  # noqa: F401
from test_sandbox_tour import approval, guest  # noqa: F401

ORIGIN = "https://node.example.test"
SOURCE = Peer("label", ORIGIN, receipt_signer.node_id, receipt_signer.public_key_b64)


def transport(peer, path, body, *, allow_loopback, timeout, reject_detail=False):
    response = client.post(path, content=body, headers={"Content-Type": "application/json"})
    if response.status_code == 200:
        return response.json()
    if reject_detail and 400 <= response.status_code < 500:
        raise PeerRejected(response.status_code, response.json()["detail"])
    raise ValueError("Peer returned an unsuccessful response")


@pytest.fixture
def network(connected, monkeypatch):
    headers, tour, side, _ = connected
    publication, _, _ = preview_and_publish(connected)
    monkeypatch.setattr(app.state, "federation_config", FederationConfig(True, ORIGIN, (SOURCE,)))
    monkeypatch.setattr(federated_requests, "peer_post", transport)
    request = {"source_id": "label", "publication_id": publication["id"], "requester_org_id": tour["requester"]["id"],
               "intended_usage": side["request"]["intended_usage"], "territory": side["request"]["territory"],
               "term_start": side["request"]["term_start"], "term_end": side["request"]["term_end"],
               "context": side["request"]["context"]}
    return headers, tour, side, publication, request


def send(headers, request):
    response = client.post("/v1/federation/permission-requests", headers=headers, json=request)
    assert response.status_code == 200, response.text
    return response.json()


def signed_request(**changes):
    now = int(time.time())
    payload = {"schemaVersion": federation.REQUEST_SCHEMA, "requestId": uuid.uuid4().hex,
               "requesterNode": {"nodeId": receipt_signer.node_id, "origin": ORIGIN}, "sourceNodeId": receipt_signer.node_id,
               "requester": {"id": "remote-org-1", "name": "Fictional Requester Studio"}, "publicationId": "",
               "intendedUsage": "ai_grounded_generation", "territory": "US", "termStart": "2026-12-01",
               "termEnd": "2027-01-31", "context": {}, "issuedAt": now, "expiresAt": now + 300}
    payload.update(changes)
    return payload


def test_cross_node_request_is_decided_by_the_source_and_returns_a_verifiable_receipt(network):
    headers, tour, side, publication, request = network
    sent = send(headers, request)
    assert sent["status"] == "pending" and sent["remotePermissionId"] and sent["receipts"] == []
    with SessionLocal() as db:
        permission = db.get(PermissionRequestRecord, sent["remotePermissionId"])
        assert permission.requested_by_peer_node_id == receipt_signer.node_id
        assert permission.requested_by_user_id is None and permission.requested_by_api_credential_id is None
        represented = db.get(OrganizationRecord, permission.requester_org_id)
        assert represented.profile["federation"]["remoteOrganizationId"] == tour["requester"]["id"]
        assert represented.created_by_user_id is None and represented.id != tour["requester"]["id"]
        assert permission.provenance["federation"]["publicationId"] == publication["id"]
        actors = {row.actor_type for row in db.query(AuditEventRecord).filter_by(resource_id=permission.id)}
        assert "federated_peer" in actors
    decision = client.post(f"/v1/permission-requests/{sent['remotePermissionId']}/decide", headers=headers, json=approval())
    assert decision.status_code == 200, decision.text
    refreshed = client.post(f"/v1/federation/permission-requests/{sent['id']}/refresh", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    result = refreshed.json()
    assert result["status"] == "approved" and len(result["receipts"]) == 1
    receipt = result["receipts"][0]
    assert ReceiptSigner.verify_receipt(receipt).valid
    assert receipt["payload"]["permission"]["requestedBy"] == {"type": "federated_peer", "nodeId": receipt_signer.node_id,
        "organizationId": receipt["payload"]["requester"]["organizationId"]}
    listed = client.get(f"/v1/organizations/{tour['requester']['id']}/federation/permission-requests", headers=headers).json()
    assert [row["id"] for row in listed["requests"]] == [sent["id"]]
    assert listed["requests"][0]["createdAt"].endswith("Z") and listed["requests"][0]["refreshedAt"].endswith("Z")


def test_rejection_reaches_the_requester_as_a_signed_status(network):
    headers, _, _, _, request = network
    sent = send(headers, request)
    note = "Fictional decline: the requested territory is outside this mandate"
    assert client.post(f"/v1/permission-requests/{sent['remotePermissionId']}/decide", headers=headers,
        json={"decision": "rejected", "note": note}).status_code == 200
    result = client.post(f"/v1/federation/permission-requests/{sent['id']}/refresh", headers=headers).json()
    assert result["status"] == "rejected" and result["decisionNote"] == note and result["receipts"] == []
    status = federation.verify_status(result["statusStatement"], SOURCE, request_id=sent["id"],
                                      requester_node_id=receipt_signer.node_id, nonce=result["statusStatement"]["payload"]["nonce"])
    assert status["status"] == "rejected"


def test_identical_redelivery_is_idempotent_and_a_reused_id_is_refused(network):
    _, _, _, publication, _ = network
    payload = signed_request(publicationId=publication["id"])
    statement = receipt_signer.sign_statement(payload)
    first = client.post("/v1/federation/inbound/permission-requests", json=statement)
    again = client.post("/v1/federation/inbound/permission-requests", json=statement)
    assert first.status_code == again.status_code == 200, first.text
    assert first.json()["payload"]["permissionRequestId"] == again.json()["payload"]["permissionRequestId"]
    altered = receipt_signer.sign_statement({**payload, "territory": "CA"})
    assert client.post("/v1/federation/inbound/permission-requests", json=altered).status_code == 409
    with SessionLocal() as db:
        assert db.query(FederatedInboundRequestRecord).filter_by(request_id=payload["requestId"]).count() == 1


@pytest.mark.parametrize("attack,expected", [("unconfigured", 403), ("forged_key", 401), ("other_source", 401),
    ("expired", 401), ("wrong_origin", 401), ("extra_field", 401), ("nan", 422)])
def test_inbound_requests_require_a_configured_peer_signature(network, attack, expected):
    _, _, _, publication, _ = network
    payload = signed_request(publicationId=publication["id"])
    signer = receipt_signer
    if attack == "unconfigured": payload["requesterNode"]["nodeId"] = "urn:unknown"
    if attack == "forged_key": signer = ReceiptSigner(node_id=receipt_signer.node_id, private_key_b64=None, app_env="test")
    if attack == "other_source": payload["sourceNodeId"] = "urn:another"
    if attack == "expired": payload.update(issuedAt=int(time.time()) - 400, expiresAt=int(time.time()) - 100)
    if attack == "wrong_origin": payload["requesterNode"]["origin"] = "https://attacker.example.test"
    if attack == "extra_field": payload["evidence"] = "smuggled"
    statement = signer.sign_statement(payload)
    body = canonical_json(statement)
    if attack == "nan":
        body = body.replace(b'"context":{}', b'"context":{"x":NaN}')
    response = client.post("/v1/federation/inbound/permission-requests", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == expected, response.text


def test_withdrawn_entries_refuse_new_requests_and_the_requester_records_why(network):
    headers, _, side, publication, request = network
    root = f"/v1/organizations/{side['orgId']}/catalog/publications"
    assert client.post(f"{root}/{publication['id']}/withdraw", headers=headers, json={"expected_revision": 1}).status_code == 200
    response = client.post("/v1/federation/permission-requests", headers=headers, json=request)
    assert response.status_code == 409 and "not currently published" in response.json()["detail"]
    listed = client.get(f"/v1/organizations/{request['requester_org_id']}/federation/permission-requests", headers=headers).json()
    assert listed["requests"][0]["status"] == "not_accepted"


def test_status_queries_name_an_existing_request_from_the_asking_peer(network):
    now = int(time.time())
    query = {"schemaVersion": federation.STATUS_QUERY_SCHEMA, "requestId": uuid.uuid4().hex,
             "requesterNode": {"nodeId": receipt_signer.node_id, "origin": ORIGIN}, "sourceNodeId": receipt_signer.node_id,
             "nonce": "n" * 32, "issuedAt": now, "expiresAt": now + 300}
    assert client.post("/v1/federation/inbound/permission-requests/status", json=receipt_signer.sign_statement(query)).status_code == 404


def test_requester_rejects_receipts_signed_by_another_key(network):
    headers, _, _, _, request = network
    sent = send(headers, request)
    client.post(f"/v1/permission-requests/{sent['remotePermissionId']}/decide", headers=headers, json=approval())
    status = client.post(f"/v1/federation/permission-requests/{sent['id']}/refresh", headers=headers).json()["statusStatement"]
    payload = copy.deepcopy(status["payload"])
    other = ReceiptSigner(node_id=receipt_signer.node_id, private_key_b64=None, app_env="test")
    payload["receipts"] = [other.sign_receipt(payload=payload["receipts"][0]["payload"], transparency_sequence=1, previous_entry_hash=None)]
    with pytest.raises(ValueError, match="configured peer"):
        federation.verify_status(receipt_signer.sign_statement(payload), SOURCE, request_id=sent["id"],
                                 requester_node_id=receipt_signer.node_id, nonce=payload["nonce"])


def test_local_results_use_the_same_request_endpoint(network):
    headers, _, _, _, request = network
    response = client.post("/v1/federation/permission-requests", headers=headers, json={**request, "source_id": "local"})
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "local" and response.json()["status"] == "pending"


def test_an_unreachable_source_leaves_an_unconfirmed_request_that_refresh_can_deliver(network, monkeypatch):
    headers, _, _, _, request = network
    def offline(*args, **kwargs):
        raise TimeoutError("offline")
    monkeypatch.setattr(federated_requests, "peer_post", offline)
    assert client.post("/v1/federation/permission-requests", headers=headers, json=request).status_code == 502
    listed = client.get(f"/v1/organizations/{request['requester_org_id']}/federation/permission-requests", headers=headers).json()
    row = listed["requests"][0]
    assert row["status"] == "unconfirmed" and row["remotePermissionId"] is None
    monkeypatch.setattr(federated_requests, "peer_post", transport)
    delivered = client.post(f"/v1/federation/permission-requests/{row['id']}/refresh", headers=headers)
    assert delivered.status_code == 200 and delivered.json()["status"] == "pending"


def test_public_terms_and_node_descriptor_are_signed_and_readable_without_an_account(network):
    headers, _, side, publication, _ = network
    response = client.get(f"/v1/public/catalog/publications/{publication['id']}")
    assert response.status_code == 200 and 'rel="describedby"' in response.headers["link"]
    terms = response.json()
    federation.verify_peer_signature(terms, SOURCE)
    assert terms["payload"]["schemaVersion"] == federation.TERMS_SCHEMA
    assert terms["payload"]["entry"]["publicationId"] == publication["id"]
    assert "evidence" not in canonical_json(terms).decode()
    descriptor = client.get("/.well-known/clef-node").json()
    federation.verify_peer_signature(descriptor, SOURCE)
    assert descriptor["payload"]["keys"][0]["publicKey"] == receipt_signer.public_key_b64
    assert descriptor["payload"]["endpoints"]["publicTerms"].startswith("/v1/public/catalog/publications/")
    root = f"/v1/organizations/{side['orgId']}/catalog/publications"
    client.post(f"{root}/{publication['id']}/withdraw", headers=headers, json={"expected_revision": 1})
    assert client.get(f"/v1/public/catalog/publications/{publication['id']}").status_code == 404


def test_a_pinned_next_key_lets_a_peer_rotate_without_reconfiguration():
    current = ReceiptSigner(node_id="urn:rotating", private_key_b64=None, app_env="test")
    upcoming = ReceiptSigner(node_id="urn:rotating", private_key_b64=None, app_env="test")
    peer = Peer("rotating", "https://rotating.example.test", "urn:rotating", current.public_key_b64, upcoming.public_key_b64)
    federation.verify_peer_signature(current.sign_statement({"schemaVersion": "x"}), peer)
    federation.verify_peer_signature(upcoming.sign_statement({"schemaVersion": "x"}), peer)
    stranger = ReceiptSigner(node_id="urn:rotating", private_key_b64=None, app_env="test")
    with pytest.raises(ValueError):
        federation.verify_peer_signature(stranger.sign_statement({"schemaVersion": "x"}), peer)


def test_receipt_verification_requires_a_signer_this_node_recognizes(network):
    headers, _, side, _, _ = network
    approved = client.post(f"/v1/permission-requests/{side['permissionId']}/decide", headers=headers, json=approval())
    receipt = approved.json()["receipt"]
    own = client.post("/v1/receipts/verify", json={"receipt": receipt}).json()
    assert own["valid"] is True and own["signer"] == "this_node"
    stranger = ReceiptSigner(node_id=receipt_signer.node_id, private_key_b64=None, app_env="test")
    foreign = stranger.sign_receipt(payload=receipt["payload"], transparency_sequence=1, previous_entry_hash=None)
    result = client.post("/v1/receipts/verify", json={"receipt": foreign}).json()
    assert result["signatureValid"] is True and result["valid"] is False and result["signer"] is None
    assert "does not recognize" in result["error"]


def test_node_descriptor_is_served_outside_demo_mode(network, monkeypatch):
    from test_api import settings
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    assert client.get("/.well-known/clef-node").status_code == 200
    assert client.get("/.well-known/other").status_code == 410


def test_peer_enrollment_requires_the_key_id_verified_out_of_band(network):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from federation_peer import peer_entry
    descriptor = client.get("/.well-known/clef-node").json()
    entry = peer_entry(descriptor, origin=ORIGIN, peer_id="label", expected_key_id=receipt_signer.key_id)
    assert entry == {"id": "label", "origin": ORIGIN, "nodeId": receipt_signer.node_id, "publicKey": receipt_signer.public_key_b64}
    with pytest.raises(ValueError, match="differs"):
        peer_entry(descriptor, origin=ORIGIN, peer_id="label", expected_key_id="ed25519:" + "0" * 24)
    with pytest.raises(ValueError, match="origin"):
        peer_entry(descriptor, origin="https://elsewhere.example.test", peer_id="label", expected_key_id=receipt_signer.key_id)


# --- Findings from the 2026-11-01 adversarial review ---

def _patch_closure(path, names, value):
    """Swap a dependency captured at registration, following nested closures by name; returns a restore callback."""
    function = next(r for r in app.routes if getattr(r, "path", "") == path).endpoint
    for name in names[:-1]:
        function = function.__closure__[function.__code__.co_freevars.index(name)].cell_contents
    cell = function.__closure__[function.__code__.co_freevars.index(names[-1])]
    old, cell.cell_contents = cell.cell_contents, value
    return lambda: setattr(cell, "cell_contents", old)


def test_peer_slugs_are_reserved_and_a_lookalike_org_is_never_reused(network):
    headers, tour, _, publication, request = network
    taken = client.post("/v1/organizations", headers=headers, json={"slug": "peer-squatter", "name": "Squatter",
        "organization_type": "requester", "default_territory": "US", "controlled_right_types": []})
    assert taken.status_code == 422 and "reserved" in taken.json()["detail"]
    import hashlib
    slug = "peer-" + hashlib.sha256(f"{receipt_signer.node_id}\0{tour['requester']['id']}".encode()).hexdigest()[:24]
    with SessionLocal() as db:
        user_id = db.query(OrganizationRecord).filter_by(id=tour["requester"]["id"]).one().created_by_user_id
        db.add(OrganizationRecord(slug=slug, name="Pre-existing lookalike", profile={}, created_by_user_id=user_id))
        db.commit()
    response = client.post("/v1/federation/permission-requests", headers=headers, json=request)
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.query(PermissionRequestRecord).join(OrganizationRecord, PermissionRequestRecord.requester_org_id == OrganizationRecord.id) \
            .filter(OrganizationRecord.slug == slug).count() == 0


def test_a_transient_source_failure_stays_retryable(network, monkeypatch):
    headers, _, _, _, request = network
    def busy(peer, path, body, **kwargs):
        raise PeerRejected(429, "Rate limit exceeded")
    monkeypatch.setattr(federated_requests, "peer_post", busy)
    assert client.post("/v1/federation/permission-requests", headers=headers, json=request).status_code == 502
    row = client.get(f"/v1/organizations/{request['requester_org_id']}/federation/permission-requests", headers=headers).json()["requests"][0]
    assert row["status"] == "unconfirmed"
    monkeypatch.setattr(federated_requests, "peer_post", transport)
    assert client.post(f"/v1/federation/permission-requests/{row['id']}/refresh", headers=headers).json()["status"] == "pending"


def test_retired_keys_keep_old_receipts_verifiable_after_rotation(network, monkeypatch):
    from test_api import settings
    headers, _, _, _, request = network
    sent = send(headers, request)
    client.post(f"/v1/permission-requests/{sent['remotePermissionId']}/decide", headers=headers, json=approval())
    receipt = client.post(f"/v1/federation/permission-requests/{sent['id']}/refresh", headers=headers).json()["receipts"][0]
    successor = ReceiptSigner(node_id=receipt_signer.node_id, private_key_b64=None, app_env="test")
    rotated = Peer("label", ORIGIN, receipt_signer.node_id, successor.public_key_b64, retired_keys=(receipt_signer.public_key_b64,))
    status = receipt_signer.sign_statement({**client.post(f"/v1/federation/permission-requests/{sent['id']}/refresh",
        headers=headers).json()["statusStatement"]["payload"]})
    # The status statement itself must come from a current key; carried receipts may use a retired one.
    with pytest.raises(ValueError):
        federation.verify_status(status, rotated, request_id=sent["id"], requester_node_id=receipt_signer.node_id,
                                 nonce=status["payload"]["nonce"])
    fresh = successor.sign_statement(status["payload"])
    assert federation.verify_status(fresh, rotated, request_id=sent["id"], requester_node_id=receipt_signer.node_id,
                                    nonce=status["payload"]["nonce"])["status"] == "approved"
    monkeypatch.setattr(settings, "NODE_RETIRED_SIGNING_PUBLIC_KEYS_B64", receipt_signer.public_key_b64)
    import main
    monkeypatch.setattr(main, "receipt_signer", successor)
    assert client.post("/v1/receipts/verify", json={"receipt": receipt}).json()["signer"] == "this_node_retired_key"


def test_peer_enrollment_computes_the_key_id_instead_of_trusting_the_descriptor(network):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from federation_peer import peer_entry
    descriptor = client.get("/.well-known/clef-node").json()
    impostor = ReceiptSigner(node_id=receipt_signer.node_id, private_key_b64=None, app_env="test")
    payload = copy.deepcopy(descriptor["payload"])
    payload["keys"] = [{"keyId": receipt_signer.key_id, "publicKey": impostor.public_key_b64, "status": "current"}]
    with pytest.raises(ValueError, match="differs"):
        peer_entry(impostor.sign_statement(payload), origin=ORIGIN, peer_id="label", expected_key_id=receipt_signer.key_id)


def test_a_withdrawal_that_lands_before_the_locks_refuses_the_request(network):
    _, _, _, publication, _ = network
    import main
    real = main.catalog_publications.current_payload
    calls = []
    def racing(db, row):
        result = real(db, row)
        if not calls:
            # Simulates PostgreSQL interleaving: the withdrawal commits right after the first check.
            with SessionLocal() as other:
                pub = other.get(CatalogPublicationRecord, row.id)
                pub.withdrawn_at = datetime.datetime.utcnow(); pub.public_payload = {}; pub.search_text = ""
                other.commit()
        calls.append(result)
        return result
    restore = _patch_closure("/v1/federation/inbound/permission-requests", ["locked_current", "current_publication"], racing)
    try:
        payload = signed_request(publicationId=publication["id"])
        response = client.post("/v1/federation/inbound/permission-requests", json=receipt_signer.sign_statement(payload))
    finally:
        restore()
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.query(FederatedInboundRequestRecord).filter_by(request_id=payload["requestId"]).count() == 0


def test_status_survives_long_notes_and_keeps_the_newest_receipts(network):
    headers, _, _, _, request = network
    sent = send(headers, request)
    note = "Fictional decline. " * 300
    assert client.post(f"/v1/permission-requests/{sent['remotePermissionId']}/decide", headers=headers,
        json={"decision": "rejected", "note": note}).status_code == 200
    refreshed = client.post(f"/v1/federation/permission-requests/{sent['id']}/refresh", headers=headers)
    assert refreshed.status_code == 200 and refreshed.json()["decisionNote"] == note.strip()


def test_refresh_releases_its_database_connection_before_calling_the_peer(network, monkeypatch):
    headers, _, _, _, request = network
    import main
    seen = []
    def watching(peer, path, body, **kwargs):
        seen.append(main.engine.pool.checkedout())
        return transport(peer, path, body, **kwargs)
    monkeypatch.setattr(federated_requests, "peer_post", watching)
    sent = send(headers, request)
    client.post(f"/v1/federation/permission-requests/{sent['id']}/refresh", headers=headers)
    assert seen == [0, 0]
