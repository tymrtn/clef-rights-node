#!/usr/bin/env python3
"""Print a FEDERATION_PEERS_JSON entry for a node whose key you verified out of band.

The peer's operator gives you its key ID through a channel your organization
controls. This script fetches the peer's signed descriptor, refuses it unless the
signing key matches that key ID, and prints the configuration entry. It never
writes configuration; the operator reviews and applies the entry.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx
from services.federation import DESCRIPTOR_SCHEMA, Peer, check_window, decode_key, validate_origin, verify_peer_signature


def peer_entry(descriptor: dict, *, origin: str, peer_id: str, expected_key_id: str) -> dict:
    payload = descriptor.get("payload") if isinstance(descriptor, dict) else None
    if not isinstance(payload, dict) or payload.get("schemaVersion") != DESCRIPTOR_SCHEMA:
        raise ValueError("The origin did not return a Clef node descriptor")
    current = next((key for key in payload.get("keys", []) if key.get("status") == "current"), None)
    # Derive the key ID from the key itself; the descriptor's own keyId field is only a claim.
    computed = f"ed25519:{hashlib.sha256(decode_key(current['publicKey'])).hexdigest()[:24]}" if current else None
    if computed != expected_key_id or current.get("keyId") != computed:
        raise ValueError("The descriptor's current key differs from the key ID you verified; do not configure this peer")
    if payload.get("origin") != origin:
        raise ValueError("The descriptor names a different origin")
    upcoming = next((key["publicKey"] for key in payload.get("keys", []) if key.get("status") == "next"), None)
    verify_peer_signature(descriptor, Peer(peer_id, origin, payload["nodeId"], current["publicKey"]))
    check_window(payload["issuedAt"], payload["expiresAt"], 3600)
    entry = {"id": peer_id, "origin": origin, "nodeId": payload["nodeId"], "publicKey": current["publicKey"]}
    if upcoming:
        entry["nextPublicKey"] = upcoming
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("origin", help="The peer's HTTPS origin, e.g. https://rights.publisher.example")
    parser.add_argument("--id", required=True, help="A short local name for this peer")
    parser.add_argument("--expect-key-id", required=True, help="The ed25519:... key ID the peer's operator gave you")
    args = parser.parse_args(argv)
    try:
        origin = validate_origin(args.origin)
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.get(f"{origin}/.well-known/clef-node")
        if response.status_code != 200:
            raise ValueError(f"The origin answered {response.status_code}; is federation enabled there?")
        print(json.dumps(peer_entry(response.json(), origin=origin, peer_id=args.id, expected_key_id=args.expect_key_id), indent=2))
        return 0
    except (ValueError, httpx.HTTPError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
