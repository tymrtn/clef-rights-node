"""Consent, provenance, withdrawal and transport boundaries of connected catalogs."""
import asyncio
import copy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
from types import SimpleNamespace
import uuid

import pytest
from cryptography.exceptions import InvalidSignature
from models import AuthorityClaimRecord, CatalogPublicationRecord, OrganizationMembershipRecord, OrganizationRecord, RightsContractRecord
from services import federation
from services.federation import FederationConfig, Peer, PeerSearchInput, validate_origin, verify_statement
from services.receipts import ReceiptSigner
from services.receipts import canonical_json
from test_api import (app, client, SessionLocal, _session_headers, _create_api_credential, receipt_signer,
    USAGE_KEYS, RESTRICTION_KEYS, AI_INPUT_KEYS, AI_MODEL_SCOPE_KEYS, AI_LIMIT_KEYS, AI_SAFEGUARD_KEYS)
from test_sandbox_tour import guest, prepared

VOCABULARY = {"usage": USAGE_KEYS, "restrictions": RESTRICTION_KEYS, "inputs": AI_INPUT_KEYS,
              "modelScopes": AI_MODEL_SCOPE_KEYS, "limits": AI_LIMIT_KEYS, "safeguards": AI_SAFEGUARD_KEYS}


@pytest.fixture
def connected(guest, monkeypatch):
    monkeypatch.setattr(app.state, "federation_config", FederationConfig(True, "https://node.example.test"))
    tour = prepared(guest)
    side = tour["sides"][0]
    # Every guest's tour uses the same fictional title; a unique label keeps searches hermetic.
    side["label"] = f"Fictional Label {uuid.uuid4().hex[:12]}"
    with SessionLocal() as db:
        db.get(OrganizationRecord, side["orgId"]).name = side["label"]
        db.commit()
    root = f"/v1/organizations/{side['orgId']}/catalog/publications"
    return guest, tour, side, root


def preview_and_publish(connected):
    headers, _, side, root = connected
    response = client.post(f"{root}/preview", headers=headers, json={"authority_claim_id": side["authority"]["id"]})
    assert response.status_code == 200, response.text
    preview = response.json()
    request = {"authority_claim_id": side["authority"]["id"], "preview_digest": preview["previewDigest"], "confirm_publication": True}
    response = client.post(root, headers=headers, json=request)
    assert response.status_code == 200, response.text
    return response.json(), request, preview


def public_search(query="Paper Skies"):
    request = PeerSearchInput(query=query, nonce=uuid.uuid4().hex)
    response = client.post("/v1/federation/catalog/search", json=request.model_dump())
    assert response.status_code == 200, response.text
    return request, response.json()


def test_disabled_federation_exposes_no_catalog():
    assert client.post("/v1/federation/catalog/search", json={"query": "Paper", "nonce": "a" * 32}).status_code == 404
    assert client.post("/v1/federation/search", json={"query": "Paper"}).status_code == 404


def test_publication_requires_exact_consent_and_excludes_private_canaries(connected):
    headers, _, side, root = connected
    # Existing internal directory visibility confers no external publication consent.
    assert all(e["authorityClaimId"] != side["authority"]["id"] for e in public_search(side["label"])[1]["payload"]["entries"])
    with SessionLocal() as db:
        claim = db.get(AuthorityClaimRecord, side["authority"]["id"])
        claim.evidence = {**claim.evidence, "agreement": "PRIVATE-AGREEMENT-827", "email": "private@example.test", "price": 123456}
        contract = db.get(RightsContractRecord, claim.rights_contract_id)
        contract.contract_json = {**contract.contract_json, "commercialTerms": {"secret": "PRIVATE-PRICE-837"}}
        db.commit()
    publication, request, preview = preview_and_publish(connected)
    assert preview["publicFields"] == publication["publicFields"]
    assert client.post(root, headers=headers, json=request).json()["revision"] == 1  # exact retry
    response = client.post(root, headers=headers, json={**request, "confirm_publication": False})
    assert response.status_code == 422
    search_request, statement = public_search(side["label"])
    peer = Peer("own", "https://node.example.test", receipt_signer.node_id, receipt_signer.public_key_b64)
    result = verify_statement(statement, peer, search_request, VOCABULARY)
    item = next(e for e in result["entries"] if e["publicationId"] == publication["id"])
    assert item["rightType"] == "master" and item["territory"] == "US"
    assert item["policy"]["inputs"]["stems"] == "requires_approval"
    encoded = json.dumps(statement)
    assert all(secret not in encoded for secret in ["PRIVATE-", "private@example.test", "123456", "commercialTerms", "evidence"])
    response = client.post("/v1/federation/search", headers=headers, json={"query": "Paper Skies"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["partial"] is False
    assert client.post("/v1/federation/search", json={"query": "Paper Skies"}).status_code == 401


def test_other_tenant_and_non_administrator_cannot_publish_or_withdraw(connected):
    headers, _, side, root = connected
    publication, request, _ = preview_and_publish(connected)
    stranger = _session_headers(f"stranger-{uuid.uuid4().hex}@example.test")
    for token in ({}, stranger):
        expected = 401 if not token else 403
        assert client.post(f"{root}/preview", headers=token, json={"authority_claim_id": side["authority"]["id"]}).status_code == expected
        assert client.post(root, headers=token, json=request).status_code == expected
        assert client.post(f"{root}/{publication['id']}/withdraw", headers=token, json={"expected_revision": 1}).status_code == expected
    user_id = client.get("/v1/session", headers=headers).json()["user"]["id"]
    with SessionLocal() as db:
        db.query(OrganizationMembershipRecord).filter_by(org_id=side["orgId"], user_id=user_id).update({"role": "rights_manager"})
        db.commit()
    assert client.post(root, headers=headers, json=request).status_code == 403


def test_machine_search_requires_directory_scope_and_cannot_publish(connected):
    headers, _, side, root = connected
    _, request, _ = preview_and_publish(connected)
    for scopes, expected in [(["catalog:read"], 403), (["directory:read"], 200)]:
        credential = _create_api_credential(side["orgId"], headers, scopes=scopes)
        machine = {"Authorization": f"Bearer {credential['token']}"}
        assert client.post("/v1/federation/search", headers=machine, json={"query": "Paper Skies"}).status_code == expected
        assert client.post(root, headers=machine, json=request).status_code == 401


def test_publication_pages_cover_the_whole_organization_and_scope_the_cursor(connected):
    headers, _, side, root = connected
    original, _, _ = preview_and_publish(connected)
    with SessionLocal() as db:
        source = db.get(AuthorityClaimRecord, side["authority"]["id"])
        # Synthetic stored rows exercise pagination beyond the former 200-row cutoff.
        for index in range(204):
            claim = AuthorityClaimRecord(id=str(uuid.uuid4()), org_id=source.org_id, rights_contract_id=source.rights_contract_id,
                work_key=f"fictional:{index}", right_type="master", territory="US", status="verified",
                evidence=source.evidence, asserted_by_user_id=source.asserted_by_user_id)
            db.add(claim); db.flush()
            db.add(CatalogPublicationRecord(id=str(uuid.uuid4()), org_id=source.org_id, authority_claim_id=claim.id,
                public_payload={}, search_text="", basis_hash="fixture", revision=1,
                approved_by_user_id=source.asserted_by_user_id))
        db.commit()
    found, cursor = [], None
    for _ in range(3):
        response = client.get(root, headers=headers, params={"limit": 100, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        page = response.json()
        found.extend(row["id"] for row in page["publications"])
        cursor = page["nextCursor"]
    assert cursor is None and len(found) == len(set(found)) == 205 and original["id"] in found
    other_root = f"/v1/organizations/{connected[1]['sides'][1]['orgId']}/catalog/publications"
    assert client.get(other_root, headers=headers, params={"cursor": original["id"]}).status_code == 404


@pytest.mark.parametrize("change", ["policy", "private_evidence", "revocation", "territory"])
def test_stale_or_revoked_publications_vanish_and_old_consent_cannot_republish(connected, change):
    headers, _, side, root = connected
    publication, request, _ = preview_and_publish(connected)
    assert any(e["publicationId"] == publication["id"] for e in public_search(side["label"])[1]["payload"]["entries"])
    with SessionLocal() as db:
        claim = db.get(AuthorityClaimRecord, side["authority"]["id"])
        if change == "policy":
            contract = db.get(RightsContractRecord, claim.rights_contract_id)
            contract.version += 1
            contract.effective_matrix = {**contract.effective_matrix, "usage": {k: "blocked" for k in USAGE_KEYS}}
        if change == "private_evidence": claim.evidence = {**claim.evidence, "reference": "changed-mandate"}
        if change == "revocation": claim.status = "revoked"
        if change == "territory": claim.territory = "CA"
        db.commit()
    assert not any(e["publicationId"] == publication["id"] for e in public_search(side["label"])[1]["payload"]["entries"])
    assert client.post(root, headers=headers, json=request).status_code == 409
    assert client.get(root, headers=headers).json()["publications"][0]["status"] == "needs_review"


def test_withdrawal_clears_public_fields_and_requires_new_consent_to_republish(connected):
    headers, _, side, root = connected
    publication, request, _ = preview_and_publish(connected)
    assert any(e["publicationId"] == publication["id"] for e in public_search(side["label"])[1]["payload"]["entries"])
    url = f"{root}/{publication['id']}/withdraw"
    assert client.post(url, headers=headers, json={"expected_revision": 2}).status_code == 409
    withdrawn = client.post(url, headers=headers, json={"expected_revision": 1})
    assert withdrawn.status_code == 200 and withdrawn.json()["publicFields"] == {}
    assert client.post(url, headers=headers, json={"expected_revision": 1}).status_code == 200
    assert not any(e["publicationId"] == publication["id"] for e in public_search(side["label"])[1]["payload"]["entries"])
    assert client.post(root, headers=headers, json=request).status_code == 409
    republished, _, _ = preview_and_publish(connected)
    assert republished["revision"] == 2 and republished["status"] == "published"
    # A stale withdrawal cannot remove the newly consented revision.
    assert client.post(url, headers=headers, json={"expected_revision": 1}).status_code == 409


@pytest.mark.parametrize("mutation", ["tamper", "new_key", "query", "nonce", "expired", "origin", "private_field"])
def test_peer_proof_binds_source_search_expiry_and_minimal_schema(connected, mutation):
    preview_and_publish(connected)
    request, statement = public_search()
    peer = Peer("own", "https://node.example.test", receipt_signer.node_id, receipt_signer.public_key_b64)
    changed = copy.deepcopy(statement["payload"])
    if mutation == "tamper":
        statement["payload"]["origin"] = "https://attacker.example.test"
    elif mutation == "new_key":
        statement = ReceiptSigner(node_id=receipt_signer.node_id, private_key_b64=None, app_env="test").sign_statement(changed)
    else:
        if mutation == "query": changed["query"] = "Another search"
        if mutation == "nonce": changed["nonce"] = "b" * 32
        if mutation == "expired": changed["expiresAt"] = int(time.time()) - 1
        if mutation == "origin": changed["origin"] = "https://another.example.test"
        if mutation == "private_field": changed["entries"][0]["evidence"] = "private"
        statement = receipt_signer.sign_statement(changed)
    with pytest.raises((ValueError, InvalidSignature)):
        verify_statement(statement, peer, request, VOCABULARY)


@pytest.mark.parametrize("origin", ["http://example.com", "https://user:pass@example.com", "https://example.com/path",
    "https://example.com?query=yes", "https://example.com#fragment", "https://example.com\\@127.0.0.1",
    "https://127.0.0.1", "https://10.0.0.1", "https://169.254.169.254", "https://[::1]", "https://example.com:99999"])
def test_unsafe_origins_rejected(origin):
    with pytest.raises(ValueError): validate_origin(origin)


def test_loopback_requires_explicit_development_setting():
    assert validate_origin("http://127.0.0.1:9251", allow_loopback=True) == "http://127.0.0.1:9251"
    args = dict(FEDERATION_ENABLED=True, FEDERATION_ALLOW_LOOPBACK=True, APP_ENV="production",
        FEDERATION_PUBLIC_ORIGIN="http://127.0.0.1:9251", FEDERATION_PEERS_JSON="[]")
    with pytest.raises(ValueError, match="development/test"):
        FederationConfig.from_settings(SimpleNamespace(**args), receipt_signer)


def test_peer_cannot_impersonate_the_reserved_local_source_id():
    settings = SimpleNamespace(FEDERATION_ENABLED=True, FEDERATION_ALLOW_LOOPBACK=False, APP_ENV="test",
        FEDERATION_PUBLIC_ORIGIN="https://this.example.test", FEDERATION_PEERS_JSON=json.dumps([
            {"id": "local", "origin": "https://peer.example.test", "nodeId": "urn:peer", "publicKey": receipt_signer.public_key_b64}]))
    with pytest.raises(ValueError, match="distinct"):
        FederationConfig.from_settings(settings, receipt_signer)


def test_private_dns_answer_is_rejected_before_socket_connection(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("No socket should open for a mixed public/private DNS answer"))
    peer = Peer("test", "https://example.com", "urn:test", receipt_signer.public_key_b64)
    with pytest.raises(ValueError, match="private"):
        federation.fetch_statement(peer, PeerSearchInput(query="Paper", nonce="a" * 32), allow_loopback=False)


@pytest.fixture
def http_peer():
    state = {"status": 200, "body": b'{"payload":{}}', "content_type": "application/json", "requests": []}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["requests"].append({"path": self.path, "headers": dict(self.headers),
                "body": self.rfile.read(int(self.headers["Content-Length"]))})
            self.send_response(state["status"])
            self.send_header("Content-Type", state["content_type"])
            self.send_header("Location", "http://169.254.169.254/latest/meta-data")
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers(); self.wfile.write(state["body"])
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield Peer("fixture", f"http://127.0.0.1:{server.server_port}", "urn:fixture", receipt_signer.public_key_b64), state
    server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_real_transport_sends_only_search_and_never_follows_redirects(http_peer):
    peer, state = http_peer
    request = PeerSearchInput(query="Paper", nonce="a" * 32)
    assert federation.fetch_statement(peer, request, allow_loopback=True) == {"payload": {}}
    sent = state["requests"][0]
    assert sent["path"] == "/v1/federation/catalog/search" and json.loads(sent["body"]) == request.model_dump()
    assert not any(name.lower() in {"authorization", "x-session-id", "cookie"} for name in sent["headers"])
    state["status"] = 302
    with pytest.raises(ValueError, match="unsuccessful"):
        federation.fetch_statement(peer, request, allow_loopback=True)
    assert len(state["requests"]) == 2


@pytest.mark.parametrize("body", [b"x" * (federation.MAX_BYTES + 1), b'{"same":1,"same":2}', b'{"number":NaN}'])
def test_oversized_or_ambiguous_json_fails_closed(http_peer, body):
    peer, state = http_peer; state["body"] = body
    with pytest.raises(ValueError):
        federation.fetch_statement(peer, PeerSearchInput(query="Paper", nonce="a" * 32), allow_loopback=True)


def test_peer_failure_keeps_local_results_and_reports_partial(connected, monkeypatch):
    import federation_routes
    headers, _, side, _ = connected
    label = side["label"]
    publication, _, _ = preview_and_publish(connected)
    peer = Peer("unavailable", "https://offline.example.test", "urn:offline", receipt_signer.public_key_b64)
    monkeypatch.setattr(app.state, "federation_config", FederationConfig(True, "https://node.example.test", (peer,)))
    async def unavailable(peer, *args, **kwargs):
        return {"id": peer.id, "nodeId": peer.node_id, "origin": peer.origin, "status": "timeout", "entries": []}
    monkeypatch.setattr(federation_routes, "query_peer", unavailable)
    result = client.post("/v1/federation/search", headers=headers, json={"query": label}).json()
    assert result["partial"] is True
    assert any(r["entry"]["publicationId"] == publication["id"] for r in result["results"])
    assert result["sources"][-1]["status"] == "timeout"


def test_timed_out_workers_keep_their_capacity_until_they_exit(monkeypatch):
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(federation, "_CAPACITY", capacity)
    monkeypatch.setattr(federation, "PEER_TIMEOUT", 0.01)
    done = threading.Event()
    def wait(*a, **k):
        done.wait(3)
        return {}
    monkeypatch.setattr(federation, "fetch_statement", wait)
    peer = Peer("slow", "https://slow.example.test", "urn:slow", receipt_signer.public_key_b64)
    request = PeerSearchInput(query="Paper", nonce="a" * 32)
    try:
        assert asyncio.run(federation.query_peer(peer, request, VOCABULARY, allow_loopback=False))["status"] == "timeout"
        assert asyncio.run(federation.query_peer(peer, request, VOCABULARY, allow_loopback=False))["status"] == "busy"
    finally:
        done.set()


def test_long_multibyte_source_entries_fit_the_real_peer_transport(connected, http_peer):
    _, _, preview = preview_and_publish(connected)
    peer, state = http_peer
    entries = []
    for index in range(50):
        item = copy.deepcopy(preview["publicFields"])
        item.update(publicationId=f"publication-{index}", authorityClaimId=f"claim-{index}",
            workTitle="音" * 500, artistName="音" * 500)
        item["organization"]["name"] = "音" * 200
        entries.append(item)
    request = PeerSearchInput(query="音音", nonce="a" * 32, limit=50)
    now = int(time.time())
    payload = federation.DiscoveryPayload(schemaVersion=federation.SCHEMA, nodeId=peer.node_id,
        origin=peer.origin, **request.model_dump(exclude={"limit"}), issuedAt=now, expiresAt=now + 60,
        entries=entries, truncated=False)
    assert len(canonical_json(receipt_signer.sign_statement(payload.model_dump()))) > federation.MAX_BYTES
    statement = federation.sign_discovery(receipt_signer, payload)
    state["body"] = canonical_json(statement)
    assert len(state["body"]) <= federation.MAX_BYTES
    transported = federation.fetch_statement(peer, request, allow_loopback=True)
    verified = verify_statement(transported, peer, request, VOCABULARY)
    assert verified["truncated"] is True and 0 < len(verified["entries"]) < 50
