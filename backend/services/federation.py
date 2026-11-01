"""Pinned, bounded exchange between explicitly configured rights nodes.

Discovery statements have their own schema and expiry. They never enter the
permission ledger. No requester credentials are forwarded to another node.
Permission requests travel as statements signed by the requesting node; the
source node answers with signed status statements that carry its receipts.
Every statement names its schemaVersion, and every verifier accepts exactly
one schema, so a signature over one statement type never verifies as another.
"""
from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import unicodedata
from typing import Any, Literal
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, field_validator
from services.receipts import CANONICALIZATION, ReceiptSigner, canonical_json, sha256_hex

SCHEMA = "clef.catalog-discovery.v1"
REQUEST_SCHEMA = "clef.permission-request.v1"
STATUS_QUERY_SCHEMA = "clef.permission-status-query.v1"
STATUS_SCHEMA = "clef.permission-status.v1"
TERMS_SCHEMA = "clef.catalog-terms.v1"
DESCRIPTOR_SCHEMA = "clef.node-descriptor.v1"
STATEMENT_TTL = 60
REQUEST_TTL = 300
REQUEST_TIMEOUT = 10.0
MAX_REQUEST_BYTES = 65536
MAX_BYTES = 262144
PEER_TIMEOUT = 3.0
MAX_PEERS = 8
# A stalled peer can hold at most its own slots; other peers keep their capacity.
PER_PEER_CAPACITY = 4
_EXECUTOR = ThreadPoolExecutor(max_workers=32, thread_name_prefix="clef-discovery")
_CAPACITY = threading.BoundedSemaphore(32)
_PEER_CAPACITY: dict[str, threading.BoundedSemaphore] = {}
_PEER_CAPACITY_LOCK = threading.Lock()
# Invisible, bidirectional-override, private-use and unassigned characters can disguise a query.
_UNPRINTABLE = {"Cc", "Cf", "Cs", "Co", "Cn"}


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchInput(ClosedModel):
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value):
        if len(value.strip()) < 2 or any(unicodedata.category(c) in _UNPRINTABLE for c in value):
            raise ValueError("Enter at least two printable characters")
        return value.strip()


class PeerSearchInput(SearchInput):
    nonce: str = Field(pattern=r"^[a-zA-Z0-9_-]{32,80}$")


class PublicOrganization(ClosedModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)


class CatalogReferences(ClosedModel):
    isrc: str | None = Field(default=None, pattern=r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")
    iswc: str | None = Field(default=None, pattern=r"^T[0-9]{10}$")


class PublicEntry(ClosedModel):
    publicationId: str = Field(min_length=1, max_length=100)
    organization: PublicOrganization
    authorityClaimId: str = Field(min_length=1, max_length=100)
    workKey: str = Field(min_length=1, max_length=500)
    workTitle: str = Field(min_length=1, max_length=500)
    artistName: str = Field(min_length=1, max_length=500)
    rightType: Literal["master", "composition", "lyrics", "performance", "voice", "likeness"]
    territory: str = Field(min_length=1, max_length=500)
    policyVersion: int = Field(ge=1)
    publicationRevision: int = Field(ge=1)
    synthetic: bool
    catalogReferences: CatalogReferences
    # Each section is checked against this implementation's fixed vocabulary.
    policy: dict[str, dict[str, Any]]


class DiscoveryPayload(ClosedModel):
    schemaVersion: Literal["clef.catalog-discovery.v1"]
    nodeId: str = Field(min_length=1, max_length=200)
    origin: str = Field(min_length=1, max_length=500)
    query: str = Field(min_length=2, max_length=200)
    nonce: str = Field(pattern=r"^[a-zA-Z0-9_-]{32,80}$")
    issuedAt: int
    expiresAt: int
    truncated: bool
    entries: list[PublicEntry] = Field(max_length=50)


def sign_discovery(signer, payload: DiscoveryPayload) -> dict:
    """Keep the complete UTF-8 envelope inside the same budget peers enforce."""
    body = payload.model_dump()
    while True:
        statement = signer.sign_statement(body)
        if len(canonical_json(statement)) <= MAX_BYTES:
            return statement
        if not body["entries"]:
            raise ValueError("Discovery envelope exceeds its transport budget")
        body["entries"].pop()
        body["truncated"] = True


class NodeReference(ClosedModel):
    nodeId: str = Field(min_length=1, max_length=200)
    origin: str = Field(min_length=1, max_length=500)


class PermissionRequestPayload(ClosedModel):
    schemaVersion: Literal["clef.permission-request.v1"]
    requestId: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,100}$")
    requesterNode: NodeReference
    sourceNodeId: str = Field(min_length=1, max_length=200)
    requester: PublicOrganization
    publicationId: str = Field(min_length=1, max_length=100)
    intendedUsage: str = Field(min_length=1, max_length=100)
    territory: str = Field(min_length=1, max_length=500)
    termStart: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    termEnd: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    context: dict[str, Any]
    issuedAt: int
    expiresAt: int


class StatusQueryPayload(ClosedModel):
    schemaVersion: Literal["clef.permission-status-query.v1"]
    requestId: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,100}$")
    requesterNode: NodeReference
    sourceNodeId: str = Field(min_length=1, max_length=200)
    nonce: str = Field(pattern=r"^[a-zA-Z0-9_-]{32,80}$")
    issuedAt: int
    expiresAt: int


class PermissionStatusPayload(ClosedModel):
    schemaVersion: Literal["clef.permission-status.v1"]
    nodeId: str = Field(min_length=1, max_length=200)
    origin: str = Field(min_length=1, max_length=500)
    requestId: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,100}$")
    requesterNodeId: str = Field(min_length=1, max_length=200)
    nonce: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{32,80}$")
    permissionRequestId: str = Field(min_length=1, max_length=100)
    status: Literal["pending", "approved", "rejected", "revoked", "expired", "disputed", "corrected"]
    policyState: str | None = Field(default=None, max_length=100)
    decidedAt: str | None = Field(default=None, max_length=40)
    decisionNote: str | None = None
    # Envelopes as GET /v1/receipts/{id} returns them to a requesting party, newest last.
    receipts: list[dict[str, Any]] = Field(max_length=20)
    receiptsOmitted: int = Field(default=0, ge=0)
    issuedAt: int
    expiresAt: int


@dataclass(frozen=True)
class Peer:
    id: str
    origin: str
    node_id: str
    public_key: str
    # Pinned in advance so the peer can rotate its signing key without an outage.
    next_public_key: str | None = None
    # Keys the peer signed with before a rotation: accepted on carried receipts, never on new statements.
    retired_keys: tuple[str, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        return (self.public_key,) if not self.next_public_key else (self.public_key, self.next_public_key)


def decode_key(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ValueError("Peer public keys must be 32-byte base64url Ed25519 keys")
    result = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    if len(result) != 32:
        raise ValueError("Invalid Ed25519 key length")
    return result


def public_address(ip) -> bool:
    if not ip.is_global or ip.is_multicast:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # Exclude translation/tunnel forms whose eventual IPv4 destination can
        # differ from the apparently public IPv6 address we validated.
        return ip in ipaddress.ip_network("2000::/3") and not ip.sixtofour and not ip.teredo and not ip.ipv4_mapped
    return True


def validate_origin(value: str, *, allow_loopback: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 500 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise ValueError("Use a canonical HTTPS origin")
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("Peer addresses must be origins without credentials, paths or queries")
    host = parsed.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    local = bool(allow_loopback and host in {"127.0.0.1", "::1"})
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ValueError("Peers require HTTPS; literal loopback HTTP is a development-only exception")
    if literal and not public_address(literal) and not local:
        raise ValueError("Private and special-purpose peer addresses are unavailable")
    if not literal and (host.endswith(".") or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)):
        raise ValueError("Use an ASCII DNS hostname or IP address")
    port = parsed.port  # Raises on malformed/out-of-range ports.
    if port == 0:
        raise ValueError("Peer ports must be between 1 and 65535")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    return f"{parsed.scheme}://{authority}"


@dataclass(frozen=True)
class FederationConfig:
    enabled: bool
    origin: str = ""
    peers: tuple[Peer, ...] = ()
    allow_loopback: bool = False

    @classmethod
    def from_settings(cls, settings, signer):
        if not settings.FEDERATION_ENABLED:
            return cls(False)
        local = settings.FEDERATION_ALLOW_LOOPBACK
        if local and settings.APP_ENV.lower() not in {"development", "test"}:
            raise ValueError("Loopback federation is available only in development/test")
        if signer.ephemeral:
            raise ValueError("Federation requires a persistent node signing key")
        origin = validate_origin(settings.FEDERATION_PUBLIC_ORIGIN, allow_loopback=local)
        raw = json.loads(settings.FEDERATION_PEERS_JSON)
        if not isinstance(raw, list) or len(raw) > MAX_PEERS:
            raise ValueError("Configure at most eight federation peers")
        peers = []
        seen_ids, seen_nodes, seen_origins = {"local"}, {signer.node_id}, {origin}
        for row in raw:
            if not isinstance(row, dict) or not {"id", "origin", "nodeId", "publicKey"} <= set(row) <= {"id", "origin", "nodeId", "publicKey", "nextPublicKey", "retiredPublicKeys"}:
                raise ValueError("Each peer requires id, origin, nodeId and publicKey; nextPublicKey and retiredPublicKeys are optional")
            if not isinstance(row["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", row["id"]):
                raise ValueError("Peer IDs must be short identifiers")
            if not isinstance(row["nodeId"], str) or not 1 <= len(row["nodeId"]) <= 200:
                raise ValueError("Invalid peer nodeId")
            peer_origin = validate_origin(row["origin"], allow_loopback=local)
            decode_key(row["publicKey"])
            if "nextPublicKey" in row:
                decode_key(row["nextPublicKey"])
            retired = row.get("retiredPublicKeys", [])
            if not isinstance(retired, list) or len(retired) > 8:
                raise ValueError("retiredPublicKeys must be a list of at most eight keys")
            for key in retired:
                decode_key(key)
            if row["id"] in seen_ids or row["nodeId"] in seen_nodes or peer_origin in seen_origins:
                raise ValueError("Peer identities and origins must be distinct, including this node")
            seen_ids.add(row["id"]); seen_nodes.add(row["nodeId"]); seen_origins.add(peer_origin)
            peers.append(Peer(row["id"], peer_origin, row["nodeId"], row["publicKey"], row.get("nextPublicKey"), tuple(retired)))
        return cls(True, origin, tuple(peers), local)


def validate_policy(policy: dict, vocabulary: dict[str, list[str]]) -> dict:
    if set(policy) != set(vocabulary):
        raise ValueError("Unexpected public policy sections")
    for section, keys in vocabulary.items():
        values = policy[section]
        if set(values) != set(keys):
            raise ValueError("Unexpected public policy vocabulary")
        for value in values.values():
            if section == "limits":
                # Whole numbers serialize identically in every JSON canonicalization peers may implement.
                if value is not None and (type(value) is not int or not 0 <= value <= 10**12):
                    raise ValueError("Invalid public policy limit")
            elif section == "safeguards":
                if type(value) is not bool:
                    raise ValueError("Invalid public safeguard")
            else:
                choices = {"allowed", "conditional", "denied"} if section == "restrictions" else {"allowed", "requires_approval", "blocked"}
                if not isinstance(value, str) or value not in choices:
                    raise ValueError("Invalid public policy state")
    return policy


def verify_peer_signature(statement: dict, peer: Peer, *, allow_retired: bool = False) -> None:
    """Check the envelope shape, the pinned signer and the signature; not the payload's meaning."""
    if not isinstance(statement, dict) or set(statement) != {"payload", "proof"}:
        raise ValueError("Expected a signed statement")
    proof = statement["proof"]
    if not isinstance(proof, dict) or set(proof) != {"algorithm", "canonicalization", "payloadHash", "keyId", "publicKey", "signature"}:
        raise ValueError("Invalid statement proof")
    if proof["publicKey"] not in (*peer.keys, *(peer.retired_keys if allow_retired else ())):
        raise ValueError("Statement signer differs from the configured peer")
    public_raw = decode_key(proof["publicKey"])
    if (proof["algorithm"] != "Ed25519" or proof["canonicalization"] != CANONICALIZATION
            or proof["keyId"] != f"ed25519:{hashlib.sha256(public_raw).hexdigest()[:24]}"):
        raise ValueError("Statement signer differs from the configured peer")
    raw = canonical_json(statement["payload"])
    if sha256_hex(raw) != proof["payloadHash"]:
        raise ValueError("Statement payload changed")
    signature = proof["signature"]
    if not isinstance(signature, str) or not re.fullmatch(r"[A-Za-z0-9_-]{86}", signature):
        raise ValueError("Invalid statement signature")
    Ed25519PublicKey.from_public_bytes(public_raw).verify(base64.b64decode(signature + "==", altchars=b"-_", validate=True), raw)


def check_window(issued_at: int, expires_at: int, ttl: int, *, now: int | None = None) -> None:
    current = int(time.time()) if now is None else now
    if not (current - ttl <= issued_at <= current + 5 and current < expires_at <= issued_at + ttl and expires_at > issued_at):
        raise ValueError("Statement is outside its validity window")


def verify_statement(statement: dict, peer: Peer, request: PeerSearchInput, vocabulary: dict,
                     *, now: int | None = None) -> dict:
    verify_peer_signature(statement, peer)
    payload = DiscoveryPayload.model_validate(statement["payload"]).model_dump()
    current = int(time.time()) if now is None else now
    if (payload["nodeId"] != peer.node_id or payload["origin"] != peer.origin
            or payload["query"] != request.query or payload["nonce"] != request.nonce
            or not current - STATEMENT_TTL <= payload["issuedAt"] <= current + 5
            or not current < payload["expiresAt"] <= payload["issuedAt"] + STATEMENT_TTL
            or payload["expiresAt"] <= payload["issuedAt"]
            or len(payload["entries"]) > request.limit):
        raise ValueError("Discovery statement is stale or belongs to another search/source")
    identities = set()
    for entry in payload["entries"]:
        validate_policy(entry["policy"], vocabulary)
        if entry["publicationId"] in identities:
            raise ValueError("Repeated publication in discovery response")
        identities.add(entry["publicationId"])
    return payload


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def verify_status(statement: dict, peer: Peer, *, request_id: str, requester_node_id: str,
                  nonce: str | None = None) -> dict:
    """Verify a source node's answer, including every receipt it carries, against that peer's pins."""
    verify_peer_signature(statement, peer)
    payload = PermissionStatusPayload.model_validate(statement["payload"]).model_dump()
    check_window(payload["issuedAt"], payload["expiresAt"], REQUEST_TTL)
    if (payload["nodeId"] != peer.node_id or payload["origin"] != peer.origin
            or payload["requestId"] != request_id or payload["requesterNodeId"] != requester_node_id
            or payload["nonce"] != nonce):
        raise ValueError("Status statement belongs to another request or source")
    for receipt in payload["receipts"]:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("payload"), dict):
            raise ValueError("Invalid receipt in status statement")
        verify_peer_signature({"payload": receipt["payload"], "proof": receipt.get("proof")}, peer, allow_retired=True)
        if not ReceiptSigner.verify_receipt(receipt).valid or (receipt["payload"].get("node") or {}).get("id") != peer.node_id:
            raise ValueError("Receipt was not issued by the configured peer")
    return payload


class PeerRejected(ValueError):
    """The peer answered with a client error; its detail is safe to show the requester."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def fetch_statement(peer: Peer, request: PeerSearchInput, *, allow_loopback: bool,
                    timeout: float = PEER_TIMEOUT) -> dict:
    return peer_post(peer, "/v1/federation/catalog/search", canonical_json(request.model_dump()),
                     allow_loopback=allow_loopback, timeout=timeout)


def peer_post(peer: Peer, path: str, body: bytes, *, allow_loopback: bool, timeout: float = PEER_TIMEOUT,
              reject_detail: bool = False) -> dict:
    """Resolve once, validate every address, then connect to a vetted literal IP.

    TLS verifies the configured hostname. Redirects, proxies, cookies, caller
    credentials, compression and arbitrary paths are deliberately absent.
    With reject_detail, a 4xx JSON answer raises PeerRejected with its detail.
    """
    origin = validate_origin(peer.origin, allow_loopback=allow_loopback)
    parsed = urlsplit(origin)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    deadline = time.monotonic() + timeout
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("Peer DNS returned no addresses")
    for family, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if family not in {socket.AF_INET, socket.AF_INET6} or not (public_address(ip) or (allow_loopback and host in {"127.0.0.1", "::1"} and str(ip) == host)):
            raise ValueError("Peer DNS resolved to a private or special-purpose address")
    family, socktype, proto, _, address = addresses[0]
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Peer lookup timed out")
    sock = socket.socket(family, socktype, proto)
    connection = http.client.HTTPConnection(host, port, timeout=remaining)
    # Per-read timeouts restart on every byte, so a watchdog enforces the total deadline.
    live, expired = [sock], threading.Event()
    def abort():
        expired.set()
        try:
            socket.socket.shutdown(live[0], socket.SHUT_RDWR)
        except OSError:
            pass
    watchdog = threading.Timer(max(0.0, deadline - time.monotonic()), abort)
    watchdog.daemon = True
    watchdog.start()
    try:
        sock.settimeout(remaining)
        sock.connect(address)
        if parsed.scheme == "https":
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            live[0] = sock
        connection.sock = sock
        connection.request("POST", path, body=body,
            headers={"Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity", "Connection": "close"})
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        response = connection.getresponse()
        rejected = reject_detail and 400 <= response.status < 500
        if response.status != 200 and not rejected:
            raise ValueError("Peer returned an unsuccessful response")
        if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Peer did not return JSON")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("Compressed discovery responses are unsupported")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
            raise ValueError("Discovery response exceeds its size limit")
        chunks, size = [], 0
        while not response.isclosed():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Peer response timed out")
            sock.settimeout(remaining)
            chunk = response.read1(min(16384, MAX_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("Discovery response exceeds its size limit")
            chunks.append(chunk)
        parsed = json.loads(b"".join(chunks), object_pairs_hook=_unique_json,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON number")))
        if rejected:
            detail = parsed.get("detail") if isinstance(parsed, dict) else None
            raise PeerRejected(response.status, detail[:300] if isinstance(detail, str) else "The source node declined the request")
        return parsed
    except PeerRejected:
        raise
    except Exception as error:
        if expired.is_set():
            raise TimeoutError("Peer exceeded its total deadline") from error
        raise
    finally:
        watchdog.cancel()
        connection.close()
        sock.close()


class PeerBusy(RuntimeError):
    pass


@contextmanager
def reserved(peer: Peer):
    """Hold one of the peer's slots and one global slot for a synchronous exchange."""
    with _PEER_CAPACITY_LOCK:
        own = _PEER_CAPACITY.setdefault(peer.node_id, threading.BoundedSemaphore(PER_PEER_CAPACITY))
    if not own.acquire(blocking=False):
        raise PeerBusy(peer.id)
    if not _CAPACITY.acquire(blocking=False):
        own.release()
        raise PeerBusy(peer.id)
    try:
        yield
    finally:
        _CAPACITY.release()
        own.release()


async def query_peer(peer: Peer, request: PeerSearchInput, vocabulary: dict, *, allow_loopback: bool) -> dict:
    status = {"id": peer.id, "nodeId": peer.node_id, "origin": peer.origin}
    # Capacity remains held until an abandoned DNS/socket worker actually exits.
    # Timeouts therefore cannot create an unbounded queue of background work.
    with _PEER_CAPACITY_LOCK:
        own = _PEER_CAPACITY.setdefault(peer.node_id, threading.BoundedSemaphore(PER_PEER_CAPACITY))
    capacity = _CAPACITY
    if not own.acquire(blocking=False):
        return {**status, "status": "busy", "entries": []}
    if not capacity.acquire(blocking=False):
        own.release()
        return {**status, "status": "busy", "entries": []}
    def release(_=None):
        capacity.release()
        own.release()
    try:
        future = _EXECUTOR.submit(fetch_statement, peer, request, allow_loopback=allow_loopback)
    except Exception:
        release()
        raise
    future.add_done_callback(release)
    try:
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda result: result.exception() if not result.cancelled() else None)
        statement = await asyncio.wait_for(asyncio.shield(wrapped), PEER_TIMEOUT + 0.1)
        payload = verify_statement(statement, peer, request, vocabulary)
        return {**status, "status": "ok", "entries": payload["entries"], "statement": statement,
                "expiresAt": payload["expiresAt"], "truncated": payload["truncated"]}
    except (TimeoutError, asyncio.TimeoutError, socket.timeout):
        return {**status, "status": "timeout", "entries": []}
    except Exception:
        # Public errors identify the peer, never private network details or its response body.
        return {**status, "status": "unavailable", "entries": []}
