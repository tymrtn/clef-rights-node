#!/usr/bin/env python3
"""Run the cross-node proof against two deployed nodes over HTTPS.

Each node must have federation enabled and the other node configured as its
peer. The script uses the same clearly labelled fictional catalog as the local
proof, then exercises discovery, a signed cross-node request, the source's
human decision, receipt verification, replay and impostor refusal, public
terms, and withdrawal. It never stops a server.

Sign in to each node's console as its operator and supply the session IDs
through CLEF_LABEL_SESSION and CLEF_PUBLISHER_SESSION; they are never printed.
With --label-guest, the label node is a public sandbox: the run uses a fresh
anonymous guest there, which also shows that guests cannot publish, and the
label's reference catalog must already be seeded with seed_reference_catalog.py.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import httpx
from run_federation_preview import Node, request_body, verify_requests  # also puts backend/ on sys.path
from reference_catalog import ISRC, consent, seed
from services.federation import validate_origin


class HostedNode(Node):
    def __init__(self, origin, session_id):
        self.http = httpx.Client(base_url=f"{origin}/api", timeout=20, trust_env=False, follow_redirects=False)
        self.headers = {"X-Session-Id": session_id}
        self.call("GET", "/v1/session")


def pinned(origin, public_key):
    """The descriptor names the node; the key must be the one the operator pinned."""
    response = httpx.get(f"{origin}/.well-known/clef-node", timeout=10, follow_redirects=False, trust_env=False)
    if response.status_code != 200:
        raise RuntimeError(f"{origin} has no node descriptor ({response.status_code}); is federation enabled?")
    payload = response.json()["payload"]
    if not any(key["publicKey"] == public_key and key["status"] == "current" for key in payload["keys"]):
        raise RuntimeError(f"{origin} signs with a key other than the pinned one")
    return SimpleNamespace(node_id=payload["nodeId"], public_key_b64=public_key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label-origin", required=True)
    parser.add_argument("--publisher-origin", required=True)
    parser.add_argument("--label-key", required=True, help="The label node's pinned base64url public key")
    parser.add_argument("--publisher-key", required=True, help="The publisher node's pinned base64url public key")
    parser.add_argument("--output", type=Path, help="Write the proof JSON here as well as to stdout")
    parser.add_argument("--label-guest", action="store_true",
                        help="The label node is a public sandbox; use a fresh guest session there")
    parser.add_argument("--allow-loopback", action="store_true",
                        help="Rehearse against scripts/run_federation_preview.py on 127.0.0.1 before a hosted run")
    args = parser.parse_args(argv)
    sessions = [os.environ.get("CLEF_LABEL_SESSION"), os.environ.get("CLEF_PUBLISHER_SESSION")]
    if not sessions[1] or not (sessions[0] or args.label_guest):
        parser.error("Set CLEF_PUBLISHER_SESSION, and CLEF_LABEL_SESSION unless --label-guest, to operator session IDs")
    nodes = []
    try:
        origins = [validate_origin(args.label_origin, allow_loopback=args.allow_loopback),
                   validate_origin(args.publisher_origin, allow_loopback=args.allow_loopback)]
        signers = [pinned(origins[0], args.label_key), pinned(origins[1], args.publisher_key)]
        if args.label_guest:
            guest = httpx.post(f"{origins[0]}/api/v1/sandbox/session", timeout=20, trust_env=False, follow_redirects=False)
            if guest.status_code != 200:
                raise RuntimeError(f"The label sandbox did not start a guest session ({guest.status_code})")
            sessions[0] = guest.json()["session"]["id"]
        nodes = [HostedNode(origin, session) for origin, session in zip(origins, sessions)]
        fixtures = [None if args.label_guest else seed(nodes[0], "label"), seed(nodes[1], "publisher")]
        steps = []
        result = nodes[0].call("POST", "/v1/federation/search", {"query": ISRC})
        assert result["partial"] is False and {row["entry"]["rightType"] for row in result["results"]} == {"master", "composition"}
        steps.append("Two hosted nodes return the recording and composition for one fictional ISRC")
        composition = next(row for row in result["results"] if row["entry"]["rightType"] == "composition")
        slug = f"example-requester-{uuid.uuid4().hex[:12]}" if args.label_guest else "connected-example-requester"
        request_steps, requester = verify_requests(nodes, fixtures, origins, signers, composition, requester_slug=slug)
        steps.extend(request_steps)
        if args.label_guest:
            refused = nodes[0].http.get(f"/v1/organizations/{requester['id']}/catalog/publications", headers=nodes[0].headers)
            assert refused.status_code == 403
            steps.append("An anonymous sandbox guest can search and request terms but cannot publish to the network")
        remote = fixtures[1]
        publication = next(row for row in nodes[1].call("GET", f"{remote['root']}/catalog/publications")["publications"]
                           if row["authorityClaimId"] == remote["claim"]["id"])
        nodes[1].call("POST", f"{remote['root']}/catalog/publications/{publication['id']}/withdraw", {"expected_revision": publication["revision"]})
        refused = nodes[0].http.post("/v1/federation/permission-requests", headers=nodes[0].headers, json=request_body(composition, requester))
        assert refused.status_code == 409 and "not currently published" in refused.json()["detail"]
        consent(nodes[1], remote["root"], remote["claim"]["id"])
        steps.append("A withdrawn entry refuses new requests across the internet; renewed consent restores it")
        proof = {"schemaVersion": "clef.hosted-federation-proof.v1", "synthetic": True, "origins": origins,
                 "nodeIds": [signer.node_id for signer in signers], "passed": steps}
        text = json.dumps(proof, indent=2)
        if args.output:
            args.output.write_text(text + "\n")
        print(text)
        return 0
    except (RuntimeError, ValueError, AssertionError, httpx.HTTPError, KeyError) as error:
        print(str(error) or "Hosted federation proof failed; inspect both nodes' API logs", file=sys.stderr)
        return 1
    finally:
        for node in nodes:
            node.http.close()


if __name__ == "__main__":
    raise SystemExit(main())
