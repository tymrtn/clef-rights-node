#!/usr/bin/env python3
"""Run two independent local nodes with consented fictional catalog entries.

Default execution preserves existing fixture edits and publication choices.
--verify requires fresh state, exercises cross-node requests, public terms,
withdrawal/policy changes/peer failure, and stops all servers. All data and sign-in links remain in private local state.
Failures stop for inspection; add the failing case to tests before changing this
deterministic workflow. No external catalogs, email or model calls are involved.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

from run_local_preview import ROOT, free_port, port, preview_environment, private_file, state_lock, stop, wait_ready

sys.path.insert(0, str(ROOT / "backend"))
import httpx
from services.federation import Peer, verify_peer_signature
from services.policy_vocabulary import AI_SAFEGUARD_KEYS
from reference_catalog import ARTIST, ISRC, TITLE, ApiClient, consent, seed
from services.receipts import ReceiptSigner

class Node(ApiClient):
    def __init__(self, origin, email):
        http = httpx.Client(base_url=origin, timeout=10, trust_env=False, follow_redirects=False)
        super().__init__(http, "")
        self.headers = {}
        invited = self.call("POST", "/auth/invite", {"email": email})
        token = parse_qs(urlsplit(invited["devLink"]).query)["token"][0]
        self.session = self.call("GET", "/auth/validate", params={"token": token})["session"]
        self.headers = {"X-Session-Id": self.session["id"]}


APPROVAL = {"decision": "approved", "note": "Fictional approval for the declared instrumental study",
    "obligations": {"attribution": {"required": True, "credit_text": f"{TITLE} — {ARTIST}", "placements": ["description", "metadata"]},
        "publication_reporting_required": True, "publication_evidence_due_days": 30, "usage_reporting_frequency": "once"}}


def request_body(composition, requester):
    today = dt.date.today()
    return {"source_id": composition["source"]["id"], "publication_id": composition["entry"]["publicationId"],
        "requester_org_id": requester["id"], "intended_usage": "ai_grounded_generation", "territory": "US",
        "term_start": today.isoformat(), "term_end": (today + dt.timedelta(days=90)).isoformat(),
        "context": {"restrictionCategories": [], "releaseTitle": f"{TITLE} · 60-second study (fictional)",
            "aiUse": {"inputAssets": ["composition_data"], "modelScope": "private_single_tenant",
                "sourceDurationSeconds": 30, "outputDurationSeconds": 60, "lyricCharacters": 0,
                "sourceRetentionDays": 7, "embeddingRetentionDays": 7, "acceptedSafeguards": list(AI_SAFEGUARD_KEYS)}}}


def verify_requests(nodes, fixtures, origins, signers, composition, requester_slug="connected-example-requester"):
    """A requester on the label node asks the publisher node; only signed answers count."""
    steps = []
    label, publisher = nodes
    requester = next((row for row in label.call("GET", "/v1/session")["organizations"]
                      if row["slug"] == requester_slug), None)
    if not requester:
        requester = label.call("POST", "/v1/organizations", {"slug": requester_slug,
            "name": "Example AI Studio · fictional", "organization_type": "requester", "default_territory": "US",
            "controlled_right_types": []})
    sent = label.call("POST", "/v1/federation/permission-requests", request_body(composition, requester))
    assert sent["status"] == "pending" and sent["remotePermissionId"] and sent["receipts"] == []
    ledger = publisher.call("GET", f"{fixtures[1]['root']}/permission-requests")["permissionRequests"]
    assert any(row["id"] == sent["remotePermissionId"] for row in ledger)
    steps.append("A requester on the label node sends a signed request; the publisher node records it pending under its own policy")
    publisher.call("POST", f"/v1/permission-requests/{sent['remotePermissionId']}/decide", APPROVAL)
    approved = label.call("POST", f"/v1/federation/permission-requests/{sent['id']}/refresh")
    assert approved["status"] == "approved" and len(approved["receipts"]) == 1
    checked = label.call("POST", "/v1/receipts/verify", {"receipt": approved["receipts"][0]})
    assert checked["valid"] is True and checked["signer"] == "peer:example-publisher"
    assert publisher.call("POST", "/v1/receipts/verify", {"receipt": approved["receipts"][0]})["signer"] == "this_node"
    steps.append("The publisher's human approval returns to the label node as a receipt that verifies against the pinned publisher key")
    with httpx.Client(base_url=origins[1], timeout=10, trust_env=False, follow_redirects=False) as anonymous:
        again = anonymous.post("/v1/federation/inbound/permission-requests", json=approved["requestStatement"])
        assert again.status_code == 200 and again.json()["payload"]["permissionRequestId"] == sent["remotePermissionId"]
        forged_payload = {**approved["requestStatement"]["payload"], "requestId": "forged-" + "x" * 24}
        impostor = ReceiptSigner(node_id=signers[0].node_id, private_key_b64=None, app_env="development")
        assert anonymous.post("/v1/federation/inbound/permission-requests", json=impostor.sign_statement(forged_payload)).status_code == 401
        steps.append("Replaying the signed request returns the same record; a request signed by an impostor key is refused")
        pin = Peer("publisher", origins[1], signers[1].node_id, signers[1].public_key_b64)
        terms = anonymous.get(f"/v1/public/catalog/publications/{composition['entry']['publicationId']}")
        assert terms.status_code == 200 and 'rel="describedby"' in terms.headers.get("link", "")
        verify_peer_signature(terms.json(), pin)
        assert terms.json()["payload"]["entry"]["rightType"] == "composition"
        descriptor = anonymous.get("/.well-known/clef-node")
        assert descriptor.status_code == 200
        verify_peer_signature(descriptor.json(), pin)
        steps.append("Without an account, anyone can read the publisher's signed public terms and node descriptor through its web origin")
    return steps, requester


def verify(nodes, fixtures, children, origins, signers):
    steps = []
    def search(): return nodes[0].call("POST", "/v1/federation/search", {"query": ISRC})
    result = search()
    assert result["partial"] is False
    assert {row["entry"]["rightType"] for row in result["results"]} == {"master", "composition"}
    assert len(result["results"]) == 2
    assert len({row["source"]["nodeId"] for row in result["results"]}) == 2
    assert all(row["entry"]["synthetic"] for row in result["results"])
    steps.append("Two separate databases and pinned signers return the recording and composition for one fictional ISRC")
    composition = next(row for row in result["results"] if row["entry"]["rightType"] == "composition")
    request_steps, requester = verify_requests(nodes, fixtures, origins, signers, composition)
    steps.extend(request_steps)
    remote = fixtures[1]; pub = remote["publication"]
    nodes[1].call("POST", f"{remote['root']}/catalog/publications/{pub['id']}/withdraw", {"expected_revision": pub["revision"]})
    assert len(search()["results"]) == 1
    steps.append("An authenticated publisher withdrawal disappears on the next cross-node query")
    refused = nodes[0].http.post("/v1/federation/permission-requests", headers=nodes[0].headers, json=request_body(composition, requester))
    assert refused.status_code == 409 and "not currently published" in refused.json()["detail"]
    steps.append("A request for the withdrawn entry is refused by the publisher node and recorded as not accepted")
    consent(nodes[1], remote["root"], remote["claim"]["id"])
    assert len(search()["results"]) == 2
    steps.append("A new explicit publication review restores the entry")
    current = nodes[1].call("GET", f"{remote['root']}/rights/{remote['workKey']}")
    original = copy.deepcopy(current["contract"])
    blocked = copy.deepcopy(original)
    blocked["matrix"]["usage"]["ai_grounded_generation"] = "blocked"
    updated = nodes[1].call("PUT", f"{remote['root']}/rights/{remote['workKey']}", {
        "artist_name": ARTIST, "expected_version": current["version"], "contract": blocked})
    assert len(search()["results"]) == 1
    steps.append("Blocking the source policy removes stale discovery availability")
    nodes[1].call("PUT", f"{remote['root']}/rights/{remote['workKey']}", {
        "artist_name": ARTIST, "expected_version": updated["version"], "contract": original})
    assert len(search()["results"]) == 1
    consent(nodes[1], remote["root"], remote["claim"]["id"])
    assert len(search()["results"]) == 2
    steps.append("Restoring a policy still requires renewed publication consent")
    stop(children["publisher-web"])
    result = search()
    assert result["partial"] is True and len(result["results"]) == 1
    assert result["sources"][1]["status"] in {"unavailable", "timeout"}
    steps.append("A failed peer preserves the local result and is reported as a partial search")
    return {"schemaVersion": "clef.local-federation-proof.v1", "synthetic": True, "passed": steps,
            "nodeIds": [row["nodeId"] for row in result["sources"]]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".cache/clef/federation-preview")
    parser.add_argument("--label-web-port", type=port, default=16484)
    parser.add_argument("--publisher-web-port", type=port, default=16485)
    parser.add_argument("--label-api-port", type=port, default=9251)
    parser.add_argument("--publisher-api-port", type=port, default=9252)
    parser.add_argument("--verify", action="store_true", help="Use fresh state, exercise live edge cases, and stop")
    args = parser.parse_args(argv)
    ports = [args.label_web_port, args.publisher_web_port, args.label_api_port, args.publisher_api_port]
    if len(set(ports)) != 4: parser.error("All four ports must be distinct")
    state = args.state_dir.expanduser().absolute()
    if "?" in str(state) or "#" in str(state): parser.error("Use a state path without ? or #")
    python = ROOT / ".venv/bin/python"; npm = shutil.which("npm")
    if not python.is_file() or not npm or not (ROOT / "frontend/node_modules/vite").is_dir():
        parser.error("Install the repository's Python and frontend dependencies first")
    children, locks, logs, nodes = {}, [], [], []
    try:
        locks.append(state_lock(state))
        for value in ports: free_port(value)
        envs, origins, signers = [], [], []
        for role, web_port, api_port in (("label", args.label_web_port, args.label_api_port), ("publisher", args.publisher_web_port, args.publisher_api_port)):
            folder = state / role
            if args.verify and (folder / "rights.db").exists():
                raise RuntimeError("--verify requires fresh state so it cannot alter a saved demonstration")
            locks.append(state_lock(folder))
            env = preview_environment(folder, web_port, api_port)
            origin = f"http://127.0.0.1:{web_port}"
            env.update({"FEDERATION_ENABLED": "true", "FEDERATION_ALLOW_LOOPBACK": "true", "FEDERATION_PUBLIC_ORIGIN": origin,
                "NODE_ID": f"urn:clef:local-federation:{role}", "NODE_OPERATOR_EMAILS": f"federation-{role}@sandbox.invalid",
                "ALLOW_DEV_MAGIC_LINKS": "true", "RIGHTS_SESSION_TTL_MINUTES": "1440"})
            signers.append(ReceiptSigner(node_id=env["NODE_ID"], private_key_b64=env["NODE_SIGNING_PRIVATE_KEY_B64"], app_env="development"))
            envs.append(env); origins.append(origin)
        for i, (role, web_port, api_port) in enumerate((("label", args.label_web_port, args.label_api_port), ("publisher", args.publisher_web_port, args.publisher_api_port))):
            env = envs[i]; other = 1-i; folder = state / role
            env["FEDERATION_PEERS_JSON"] = json.dumps([{"id": "example-publisher" if i == 0 else "example-label",
                "origin": origins[other], "nodeId": signers[other].node_id, "publicKey": signers[other].public_key_b64}])
            log = private_file(folder / "migration.log"); logs.append(log); log.seek(0, os.SEEK_END)
            for command in ([str(python), "-m", "alembic", "upgrade", "head"], [str(python), "-m", "alembic", "check"]):
                if subprocess.run(command, cwd=ROOT / "backend", env=env, stdout=log, stderr=subprocess.STDOUT).returncode:
                    raise RuntimeError(f"{role} migration failed; inspect its private migration.log")
            for name, command, cwd, url in (
                ("api", [str(python), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(api_port)], ROOT / "backend", f"http://127.0.0.1:{api_port}/health"),
                ("web", [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"], ROOT / "frontend", origins[i]),
            ):
                log = private_file(folder / f"{name}.log"); logs.append(log); log.seek(0, os.SEEK_END)
                process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                children[f"{role}-{name}"] = process; wait_ready(url, process)
        fixtures = []
        for i, role in enumerate(("label", "publisher")):
            node = Node(origins[i], envs[i]["NODE_OPERATOR_EMAILS"]); nodes.append(node)
            fixtures.append(seed(node, role))
        if args.verify:
            proof = verify(nodes, fixtures, children, origins, signers)
            with private_file(state / "proof.json") as handle:
                handle.seek(0); json.dump(proof, handle, indent=2); handle.truncate()
            print(json.dumps(proof, indent=2))
            return 0
        print(f"Connected catalog demo: {origins[0]}\nPublisher node: {origins[1]}\nChoose Explore the example catalog, then Search connected catalogs.\nPrivate state: {state}\nCtrl-C stops both nodes; rerun to resume.", flush=True)
        while all(child.poll() is None for child in children.values()): time.sleep(.25)
        raise RuntimeError("A demo server stopped; inspect its private log")
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError, ValueError, AssertionError) as error:
        print(str(error) or "Federation proof failed; inspect the local fixture", file=sys.stderr)
        return 1
    finally:
        for node in nodes: node.http.close()
        for child in reversed(list(children.values())): stop(child)
        for log in logs: log.close()
        for lock in locks: lock.close()


if __name__ == "__main__":
    def interrupted(*_): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    raise SystemExit(main())
