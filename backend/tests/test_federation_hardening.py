"""Transport deadlines, capacity fairness and protocol boundaries found in the 2026-11-01 audit."""
import asyncio
import datetime
import ipaddress
import json
import socket
import ssl
import threading
import time
from types import SimpleNamespace
import uuid

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from models import AuthorityClaimRecord, CatalogPublicationRecord
from services import federation
from services.federation import FederationConfig, Peer, PeerSearchInput, SearchInput, validate_origin, validate_policy, verify_statement
from services.receipts import ReceiptSigner
from test_api import SessionLocal, receipt_signer
from test_federation import VOCABULARY, connected, preview_and_publish, public_search  # noqa: F401
from test_sandbox_tour import guest  # noqa: F401

PEER = Peer("own", "https://node.example.test", receipt_signer.node_id, receipt_signer.public_key_b64)


def _drip_server(delay):
    """Accept one connection and send a valid status line one byte at a time."""
    server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(1)
    stop = threading.Event()
    def serve():
        connection, _ = server.accept()
        connection.recv(65536)
        for byte in b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" * 50:
            if stop.is_set():
                break
            try:
                connection.send(bytes([byte]))
            except OSError:
                break
            time.sleep(delay)
        connection.close()
    thread = threading.Thread(target=serve, daemon=True); thread.start()
    return server, stop, thread


def test_slow_drip_peer_is_cut_off_at_the_total_deadline():
    server, stop, thread = _drip_server(0.05)
    peer = Peer("drip", f"http://127.0.0.1:{server.getsockname()[1]}", "urn:drip", receipt_signer.public_key_b64)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            federation.fetch_statement(peer, PeerSearchInput(query="Paper", nonce="a" * 32), allow_loopback=True, timeout=0.5)
        assert time.monotonic() - started < 1.5
    finally:
        stop.set(); server.close(); thread.join(timeout=2)


def test_one_stalled_peer_cannot_take_capacity_from_other_peers(monkeypatch):
    release = threading.Event()
    def fetch(peer, *args, **kwargs):
        if peer.id == "stalled":
            release.wait(5)
        return {"stalled": peer.id == "stalled"}
    monkeypatch.setattr(federation, "fetch_statement", fetch)
    monkeypatch.setattr(federation, "PEER_TIMEOUT", 0.05)
    monkeypatch.setattr(federation, "verify_statement", lambda statement, *a, **k: {"entries": [], "expiresAt": 0, "truncated": False})
    stalled = Peer("stalled", "https://stalled.example.test", "urn:stalled", receipt_signer.public_key_b64)
    healthy = Peer("healthy", "https://healthy.example.test", "urn:healthy", receipt_signer.public_key_b64)
    request = PeerSearchInput(query="Paper", nonce="a" * 32)
    try:
        statuses = [asyncio.run(federation.query_peer(stalled, request, VOCABULARY, allow_loopback=False))["status"]
                    for _ in range(federation.PER_PEER_CAPACITY + 1)]
        assert statuses[:-1] == ["timeout"] * federation.PER_PEER_CAPACITY and statuses[-1] == "busy"
        assert asyncio.run(federation.query_peer(healthy, request, VOCABULARY, allow_loopback=False))["status"] == "ok"
    finally:
        release.set()


@pytest.mark.parametrize("address", ["224.0.0.1", "239.255.255.250", "ff02::1", "255.255.255.255"])
def test_multicast_and_broadcast_destinations_are_not_public(address):
    assert federation.public_address(ipaddress.ip_address(address)) is False
    host = f"[{address}]" if ":" in address else address
    with pytest.raises(ValueError):
        validate_origin(f"https://{host}")


@pytest.mark.parametrize("query", ["Paper‮Skies", "Paper​Skies", "Paper\x7fSkies", "Paper\x85Skies", "Paper"])
def test_queries_reject_invisible_bidi_and_control_characters(query):
    with pytest.raises(ValueError):
        SearchInput(query=query)


@pytest.mark.parametrize("query", ["Beyoncé", "音楽", "Sigur Rós", "AC/DC"])
def test_queries_accept_ordinary_international_text(query):
    assert SearchInput(query=query).query == query


@pytest.mark.parametrize("query,limit", [("P", 20), ("x" * 201, 20), ("Paper", 0), ("Paper", 51)])
def test_search_input_bounds(query, limit):
    with pytest.raises(ValueError):
        SearchInput(query=query, limit=limit)


def _limits_policy(value):
    policy = {section: {key: None if section == "limits" else True if section == "safeguards"
                        else "denied" if section == "restrictions" else "blocked" for key in keys}
              for section, keys in VOCABULARY.items()}
    policy["limits"]["maxSourceDurationSeconds"] = value
    return policy


def test_published_limits_are_whole_numbers_for_cross_language_signatures():
    assert validate_policy(_limits_policy(30), VOCABULARY)
    for value in (30.5, 30.0, True):
        with pytest.raises(ValueError):
            validate_policy(_limits_policy(value), VOCABULARY)


def test_receipts_and_discovery_statements_are_not_interchangeable(connected):
    preview_and_publish(connected)
    request, statement = public_search()
    assert ReceiptSigner.verify_receipt(statement).valid is False
    receipt = receipt_signer.sign_receipt(payload={"schemaVersion": "clef.permission-receipt.v1", "query": request.query,
        "nonce": request.nonce}, transparency_sequence=1, previous_entry_hash=None)
    with pytest.raises(ValueError):
        verify_statement(receipt, PEER, request, VOCABULARY)
    with pytest.raises(ValueError):
        verify_statement({"payload": receipt["payload"], "proof": receipt["proof"]}, PEER, request, VOCABULARY)


@pytest.mark.parametrize("mutation", ["future", "over_limit", "duplicate"])
def test_statement_time_count_and_identity_boundaries(connected, mutation):
    publication, _, _ = preview_and_publish(connected)
    request, statement = public_search()
    payload = statement["payload"]
    entry = publication["publicFields"]
    narrow = request
    if mutation == "future":
        payload["issuedAt"] = int(time.time()) + 30; payload["expiresAt"] = payload["issuedAt"] + 30
    if mutation == "over_limit":
        payload["entries"] = [entry, {**entry, "publicationId": "another"}]
        narrow = PeerSearchInput(query=request.query, nonce=request.nonce, limit=1)
    if mutation == "duplicate":
        payload["entries"] = [entry, entry]
    with pytest.raises(ValueError):
        verify_statement(receipt_signer.sign_statement(payload), PEER, narrow, VOCABULARY)


def _peer_settings(peers, app_env="test", loopback=False):
    return SimpleNamespace(FEDERATION_ENABLED=True, FEDERATION_ALLOW_LOOPBACK=loopback, APP_ENV=app_env,
        FEDERATION_PUBLIC_ORIGIN="http://127.0.0.1:9251" if loopback else "https://this.example.test",
        FEDERATION_PEERS_JSON=json.dumps(peers))


def test_configuration_allows_at_most_eight_peers():
    peers = [{"id": f"p{i}", "origin": f"https://p{i}.example.test", "nodeId": f"urn:p{i}",
              "publicKey": ReceiptSigner(node_id=f"urn:p{i}", private_key_b64=None, app_env="test").public_key_b64} for i in range(9)]
    assert len(FederationConfig.from_settings(_peer_settings(peers[:8]), receipt_signer).peers) == 8
    with pytest.raises(ValueError, match="eight"):
        FederationConfig.from_settings(_peer_settings(peers), receipt_signer)


def test_staging_rejects_the_loopback_switch():
    with pytest.raises(ValueError, match="development/test"):
        FederationConfig.from_settings(_peer_settings([], app_env="staging", loopback=True), receipt_signer)


def test_candidate_window_reports_truncation(connected):
    preview_and_publish(connected)
    with SessionLocal() as db:
        source = db.query(AuthorityClaimRecord).first()
        for index in range(201):
            claim = AuthorityClaimRecord(id=str(uuid.uuid4()), org_id=source.org_id, rights_contract_id=source.rights_contract_id,
                work_key=f"fictional:window:{index}", right_type="master", territory="US", status="verified",
                evidence=source.evidence, asserted_by_user_id=source.asserted_by_user_id)
            db.add(claim); db.flush()
            db.add(CatalogPublicationRecord(id=f"0000-window-{index:03d}", org_id=source.org_id, authority_claim_id=claim.id,
                public_payload={}, search_text="windowprobe", basis_hash="fixture", revision=1,
                approved_by_user_id=source.asserted_by_user_id))
        db.commit()
    _, statement = public_search("windowprobe")
    assert statement["payload"]["truncated"] is True and statement["payload"]["entries"] == []


@pytest.fixture
def untrusted_tls_peer(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256()))
    (tmp_path / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "cert.pem", tmp_path / "key.pem")
    server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(1)
    def serve():
        try:
            connection, _ = server.accept()
            with context.wrap_socket(connection, server_side=True) as tls:
                tls.recv(65536)
        except (OSError, ssl.SSLError):
            pass
    thread = threading.Thread(target=serve, daemon=True); thread.start()
    yield Peer("tls", f"https://127.0.0.1:{server.getsockname()[1]}", "urn:tls", receipt_signer.public_key_b64)
    server.close(); thread.join(timeout=2)


def test_tls_peers_must_present_a_trusted_certificate(untrusted_tls_peer):
    with pytest.raises(ssl.SSLCertVerificationError):
        federation.fetch_statement(untrusted_tls_peer, PeerSearchInput(query="Paper", nonce="a" * 32), allow_loopback=True)
