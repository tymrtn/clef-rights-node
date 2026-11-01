#!/usr/bin/env python3
"""Exercise prebuilt local images through nginx with fictional, disposable data.

Requires a local Docker daemon and existing images. Creates an internal network,
binds one loopback web port, disables providers, and removes owned containers.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

from run_local_preview import preview_environment


def local_daemon():
    # DOCKER_CONTEXT takes precedence over DOCKER_HOST. Resolve that choice once
    # and pin every read, mutation and cleanup to the validated Unix endpoint.
    context = os.environ.get("DOCKER_CONTEXT")
    endpoint = os.environ.get("DOCKER_HOST") if not context else None
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}}
    if not endpoint:
        command = ["docker", "context", "inspect"] + ([context] if context else [])
        result = subprocess.run(command, env=environment, capture_output=True, text=True, check=True, timeout=15)
        endpoint = json.loads(result.stdout)[0]["Endpoints"]["docker"]["Host"]
    if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
        raise RuntimeError("This proof requires a local Unix-socket Docker daemon")

    def execute(*args):
        result = subprocess.run(["docker", "--host", endpoint, *args], env=environment,
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError(f"Local Docker operation failed: {args[0]}")
        return result.stdout.strip()
    return execute


def require(condition, message="Container verification failed"):
    if not condition:
        raise RuntimeError(message)


def cleanup(docker, containers, networks):
    failures = []
    for name in reversed(containers):
        try: docker("rm", "-f", name)
        except (RuntimeError, subprocess.SubprocessError, OSError): failures.append({"kind": "container", "name": name})
    for name in reversed(networks):
        try: docker("network", "rm", name)
        except (RuntimeError, subprocess.SubprocessError, OSError): failures.append({"kind": "network", "name": name})
    return failures


def check_installed_packages(lock, installed):
    """Reject unreviewed base-image tools and versions outside the hashed lock."""
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    expected = {}
    for line in lock.splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;\\]+)", line)
        if match:
            expected.setdefault(normalize(match[1]), set()).add(match[2])
    require(bool(expected) and isinstance(installed, dict) and bool(installed), "Missing Python dependency inventory")
    for name, version in installed.items():
        require(isinstance(name, str) and isinstance(version, str), "Invalid Python dependency inventory")
        require(version in expected.get(normalize(name), set()), f"Installed package differs from the reviewed lock: {name}")
    require("pip" not in {normalize(name) for name in installed},
            "Runtime image still includes the build-time package installer")


def request(port, method, path, body=None, session=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    headers = {"Content-Type": "application/json"}
    if session: headers["X-Session-Id"] = session
    try:
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        value = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw.decode()
        return response.status, value, dict(response.getheaders())
    finally:
        connection.close()


def verify(api_image, web_image):
    docker = local_daemon()
    images = {}
    for role, name in [("api", api_image), ("web", web_image)]:
        detail = json.loads(docker("image", "inspect", name))[0]
        images[role] = {"id": detail["Id"], "architecture": detail["Architecture"], "os": detail["Os"]}
    prefix = "clef-proof-" + uuid.uuid4().hex[:12]
    network, api, web = prefix, prefix + "-api", prefix + "-web"
    front_network = prefix + "-front"
    steps = []; containers = []; networks = []; outcome = None; failure = None
    try:
        networks.append(network)
        docker("network", "create", "--internal", network)
        networks.append(front_network)
        docker("network", "create", front_network)
        with tempfile.TemporaryDirectory(prefix="clef-container-fixture-") as temporary:
            state = Path(temporary)
            env = preview_environment(state, 80, 9247)
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT", "PYTHONPATH"):
                env.pop(key, None)
            env = {key: value for key, value in env.items() if not key.startswith("VITE_")}
            env.update(DATABASE_URL="sqlite:////tmp/rights.db", CLEF_ENV_FILE="/tmp/empty.env", PORT="9247")
            env_file = state / "container.env"
            env_file.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
            env_file.chmod(0o600)
            containers.append(api)
            docker("run", "-d", "--pull=never", "--name", api, "--network", network,
                   "--env-file", str(env_file), images["api"]["id"])
            containers.append(web)
            docker("run", "-d", "--pull=never", "--name", web, "--network", front_network,
                   "-p", "127.0.0.1::80", "-e", f"API_UPSTREAM=http://{api}:9247", images["web"]["id"])
            docker("network", "connect", network, web)
            port = int(docker("port", web, "80/tcp").rsplit(":", 1)[1])
            deadline = time.monotonic() + 60
            while True:
                try:
                    status, info, _ = request(port, "GET", "/api/v1/node/info")
                    if status == 200: break
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                if time.monotonic() >= deadline: raise RuntimeError("Container API readiness timed out")
                time.sleep(0.5)
            require(info["deploymentMode"] == "public_sandbox" and info["sandboxGuestAccess"] is True)
            status, page, headers = request(port, "GET", "/")
            headers = {key.lower(): value for key, value in headers.items()}
            require(status == 200 and 'id="root"' in page)
            require(headers["x-frame-options"] == "DENY" and headers["cache-control"] == "no-store")
            require("frame-ancestors 'none'" in headers["content-security-policy"])
            steps.append("web-security-headers-and-api-proxy")
            status, guest, _ = request(port, "POST", "/api/v1/sandbox/session")
            require(status == 200)
            session = guest["session"]["id"]
            status, tour, _ = request(port, "POST", "/api/v1/sandbox/tour", session=session)
            require(status == 200 and tour["synthetic"] is True)
            require([side["rightType"] for side in tour["sides"]] == ["master", "composition"])
            require(all(side["permission"]["status"] == "pending" for side in tour["sides"]))
            steps.append("fresh-guest-prepared-label-and-publisher-catalog")
            for probe in ("training", "territory", "duration", "political", "voice"):
                body = copy.deepcopy(tour["sides"][0]["request"])
                if probe == "training": body["intended_usage"] = "ai_model_training"
                if probe == "territory": body["territory"] = "worldwide"
                if probe == "duration": body["context"]["aiUse"]["sourceDurationSeconds"] = 31
                if probe == "political": body["context"]["restrictionCategories"] = ["political"]
                if probe == "voice": body["context"]["aiUse"]["inputAssets"] = ["isolated_vocals"]
                require(request(port, "POST", "/api/v1/permission-requests", body, session)[0] == 409)
            steps.append("five-live-policy-and-authority-rejections")
            approval = {"decision": "approved", "note": "Fictional container proof",
                "obligations": {"attribution": {"required": True, "credit_text": "Paper Skies — Mara Vale (fictional)",
                    "placements": ["description", "metadata"]}, "publication_reporting_required": True,
                    "publication_evidence_due_days": 30, "usage_reporting_frequency": "once"}}
            for side in tour["sides"]:
                status, decided, _ = request(port, "POST", f"/api/v1/permission-requests/{side['permissionId']}/decide", approval, session)
                require(status == 200)
                receipt = decided["receipt"]
                require(request(port, "POST", "/api/v1/receipts/verify", {"receipt": receipt})[1]["valid"] is True)
                receipt_path = f"/api/v1/receipts/{receipt['payload']['receiptId']}"
                require(request(port, "GET", receipt_path)[0] == 401)
                require(request(port, "GET", receipt_path, session=session)[1] == receipt)
                altered = copy.deepcopy(receipt)
                altered["payload"]["permission"]["territory"] = "worldwide"
                require(request(port, "POST", "/api/v1/receipts/verify", {"receipt": altered})[1]["valid"] is False)
            steps.append("separate-approvals-private-receipts-and-tamper-rejection")
            resumed = request(port, "POST", "/api/v1/sandbox/tour", session=session)[1]
            require(all(side["permission"]["status"] == "approved" for side in resumed["sides"]))
            require([s["permissionId"] for s in resumed["sides"]] == [s["permissionId"] for s in tour["sides"]])
            steps.append("resume-preserves-approved-example")
            installed = json.loads(docker("exec", api, "python", "-c",
                "import importlib.metadata,json; print(json.dumps({d.metadata['Name']:d.version for d in importlib.metadata.distributions()}))"))
            lock_path = Path(__file__).resolve().parents[1] / "backend/requirements.lock"
            lock = lock_path.read_bytes()
            check_installed_packages(lock.decode(), installed)
            steps.append("build-time-package-installer-removed")
            steps.append("installed-python-packages-match-reviewed-lock")
        outcome = {"ok": True, "schemaVersion": "clef.container-proof.v1", "mode": "local-synthetic",
                "images": images, "network": "internal-api-and-loopback-web", "steps": steps,
                "pythonLockSha256": hashlib.sha256(lock).hexdigest(), "pythonPackages": installed}
    except (RuntimeError, ValueError, KeyError, OSError, http.client.HTTPException, subprocess.SubprocessError) as error:
        failure = f"{type(error).__name__}: {error}"
    finally:
        cleanup_failures = cleanup(docker, containers, networks)
    if failure or cleanup_failures:
        return {"ok": False, "schemaVersion": "clef.container-proof.v1", "mode": "local-synthetic",
                "images": images, "completedSteps": steps, "error": failure,
                "cleanupFailures": cleanup_failures}
    outcome["cleanup"] = "complete"
    return outcome


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    args = parser.parse_args()
    result = verify(args.api_image, args.web_image)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
