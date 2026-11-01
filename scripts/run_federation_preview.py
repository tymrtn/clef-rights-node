#!/usr/bin/env python3
"""Run two independent local nodes with consented fictional catalog entries.

Default execution preserves existing fixture edits and publication choices.
--verify requires fresh state, exercises withdrawal/policy changes/peer failure,
and stops all servers. All data and sign-in links remain in private local state.
Failures stop for inspection; add the failing case to tests before changing this
deterministic workflow. No external catalogs, email or model calls are involved.
"""
from __future__ import annotations
import argparse
import copy
import csv
import io
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
from services.policy_vocabulary import USAGE_KEYS, RESTRICTION_KEYS, AI_INPUT_KEYS, AI_MODEL_SCOPE_KEYS, default_ai_policy
from services.receipts import ReceiptSigner

ISRC, ISWC = "ZZDEM2600001", "T1234567894"
TITLE, ARTIST = "Paper Skies", "Mara Vale (fictional)"


class Node:
    def __init__(self, origin, email):
        self.http = httpx.Client(base_url=origin, timeout=10, trust_env=False, follow_redirects=False)
        self.headers = {}
        invited = self.call("POST", "/auth/invite", {"email": email})
        token = parse_qs(urlsplit(invited["devLink"]).query)["token"][0]
        self.session = self.call("GET", "/auth/validate", params={"token": token})["session"]
        self.headers = {"X-Session-Id": self.session["id"]}

    def call(self, method, path, body=None, **kwargs):
        response = self.http.request(method, path, headers=self.headers,
                                     **({"json": body} if body is not None else {}), **kwargs)
        if response.status_code not in {200, 201, 202}:
            # Never print a development login token, headers or private response.
            raise RuntimeError(f"Fixture operation {method} {path.split('?')[0]} failed ({response.status_code}); inspect private API logs")
        return response.json()


def seed(node, role):
    right = "master" if role == "label" else "composition"
    slug = f"connected-example-{role}"
    name = "Example Records · fictional" if role == "label" else "Example Publishing · fictional"
    context = node.call("GET", "/v1/session")
    org = next((row for row in context["organizations"] if row["slug"] == slug), None)
    if not org:
        org = node.call("POST", "/v1/organizations", {"slug": slug, "name": name,
            "organization_type": role, "default_territory": "US", "controlled_right_types": [right]})
    root = f"/v1/organizations/{org['id']}"
    work_key = f"isrc:{ISRC}" if role == "label" else f"iswc:{ISWC}"
    assets = node.call("GET", f"{root}/catalog/assets")["assets"]
    if not any(asset["workKey"] == work_key for asset in assets):
        clients = node.call("GET", f"{root}/catalog/clients")["clients"]
        if not any(row["externalReference"] == "mara-vale-fictional" for row in clients):
            node.call("POST", f"{root}/catalog/clients", {"name": ARTIST, "external_reference": "mara-vale-fictional"})
        data = io.StringIO(); writer = csv.writer(data)
        writer.writerow(["item_type", "title", "artist", "isrc", "iswc", "territory", "source_reference", "client_reference"])
        writer.writerow(["recording" if role == "label" else "work", TITLE, ARTIST,
            ISRC if role == "label" else "", ISWC, "US", "urn:clef:synthetic:connected-catalog-v1", "mara-vale-fictional"])
        batch = node.call("POST", f"{root}/catalog/imports/csv", files={"file": ("fictional.csv", data.getvalue().encode(), "text/csv")})
        if batch["status"] != "committed":
            node.call("POST", f"{root}/catalog/imports/{batch['id']}/commit", {"confirm_import": True, "expected_preview_digest": batch["previewDigest"]})
    policy = next((row for row in node.call("GET", f"{root}/rights")["policies"] if row["workKey"] == work_key), None)
    if not policy:
        component = "stems" if role == "label" else "composition_data"
        ai = default_ai_policy("blocked")
        ai["inputs"][component] = "requires_approval"
        ai["modelScopes"]["private_single_tenant"] = "requires_approval"
        ai["limits"] = {"maxSourceDurationSeconds": 30, "maxOutputDurationSeconds": 60,
            "maxLyricCharacters": 0, "sourceRetentionDays": 7, "embeddingRetentionDays": 7}
        policy = node.call("PUT", f"{root}/rights/{work_key}", {"artist_name": ARTIST, "expected_version": 0,
            "note": "Fictional connected-catalog example", "contract": {"policyVersion": "clef.rights-policy.v2",
                "matrix": {"usage": {key: "requires_approval" if key == "ai_grounded_generation" else "blocked" for key in USAGE_KEYS},
                    "restrictions": {key: "denied" if key in {"political", "likeness_voice_clone", "deceptive_endorsement"} else "allowed" for key in RESTRICTION_KEYS}},
                "aiPolicy": ai, "metadata": {"workTitle": TITLE, "synthetic": True,
                    "recordingIsrc": ISRC, "compositionIswc": ISWC, "pairingSource": "urn:clef:synthetic:connected-catalog-v1"}}})
    claims = node.call("GET", f"{root}/authority-claims")["claims"]
    claim = next((row for row in claims if row["rightsContractId"] == policy["id"]), None)
    if not claim:
        claim = node.call("POST", "/v1/authority-claims", {"org_id": org["id"], "rights_contract_id": policy["id"],
            "right_type": right, "territory": "US", "evidence": {"source": "fictional_local_fixture",
                "reference": "urn:clef:synthetic:connected-catalog-v1", "synthetic": True, "share": "100.0000"}})
    if claim["status"] == "self_asserted":
        node.call("POST", f"/v1/authority-claims/{claim['id']}/verify", {"evidence_note": "Synthetic mandate for this local demonstration"})
    publications = node.call("GET", f"{root}/catalog/publications")["publications"]
    publication = next((row for row in publications if row["authorityClaimId"] == claim["id"]), None)
    if not publication:
        publication = consent(node, root, claim["id"])
    return {"org": org, "root": root, "claim": claim, "policy": policy, "publication": publication, "workKey": work_key}


def consent(node, root, claim_id):
    preview = node.call("POST", f"{root}/catalog/publications/preview", {"authority_claim_id": claim_id})
    if preview["publicFields"]["synthetic"] is not True:
        raise RuntimeError("Only a clearly labelled synthetic publication may be seeded")
    return node.call("POST", f"{root}/catalog/publications", {"authority_claim_id": claim_id,
        "preview_digest": preview["previewDigest"], "confirm_publication": True})


def verify(nodes, fixtures, children):
    steps = []
    def search(): return nodes[0].call("POST", "/v1/federation/search", {"query": ISRC})
    result = search()
    assert result["partial"] is False
    assert {row["entry"]["rightType"] for row in result["results"]} == {"master", "composition"}
    assert len(result["results"]) == 2
    assert len({row["source"]["nodeId"] for row in result["results"]}) == 2
    assert all(row["entry"]["synthetic"] for row in result["results"])
    steps.append("Two separate databases and pinned signers return the recording and composition for one fictional ISRC")
    remote = fixtures[1]; pub = remote["publication"]
    nodes[1].call("POST", f"{remote['root']}/catalog/publications/{pub['id']}/withdraw", {"expected_revision": pub["revision"]})
    assert len(search()["results"]) == 1
    steps.append("An authenticated publisher withdrawal disappears on the next cross-node query")
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
            proof = verify(nodes, fixtures, children)
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
