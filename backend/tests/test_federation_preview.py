"""Actual two-node launcher: independent state, boundary proof and durable restart."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / ".venv/bin/python").is_file() or not (ROOT / "frontend/node_modules/vite").is_dir(),
    reason="Requires installed local preview dependencies; exercised in the local-preview CI job")


def command(state):
    sockets = [socket.socket() for _ in range(4)]
    try:
        for sock in sockets: sock.bind(("127.0.0.1", 0))
        ports = [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets: sock.close()
    flags = ("--label-web-port", "--publisher-web-port", "--label-api-port", "--publisher-api-port")
    cmd = [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/run_federation_preview.py"), "--state-dir", str(state)]
    for flag, port in zip(flags, ports): cmd.extend([flag, str(port)])
    return cmd, ports


def assert_stopped(ports):
    for port in ports:
        with socket.socket() as sock:
            assert sock.connect_ex(("127.0.0.1", port)) != 0, f"Preview left port {port} listening"


def test_real_two_node_failure_proof_and_existing_state_guard(tmp_path):
    cmd, ports = command(tmp_path)
    proof = subprocess.run([*cmd, "--verify"], cwd=ROOT, capture_output=True, text=True, timeout=45)
    assert proof.returncode == 0, proof.stderr
    data = json.loads(proof.stdout)
    assert data["synthetic"] is True and len(data["passed"]) == 11
    assert any("verifies against the pinned publisher key" in step for step in data["passed"])
    assert len(set(data["nodeIds"])) == 2
    assert json.loads((tmp_path / "proof.json").read_text()) == data
    assert_stopped(ports)
    databases = [tmp_path / role / "rights.db" for role in ("label", "publisher")]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in databases]
    rejected = subprocess.run([*cmd, "--verify"], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert rejected.returncode == 1 and "requires fresh state" in rejected.stderr
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in databases] == before
    assert_stopped(ports)


def test_actual_restart_preserves_published_catalog_ids_and_keys(tmp_path):
    cmd, ports = command(tmp_path)
    first = None
    with httpx.Client(trust_env=False, timeout=3) as client:
        for _ in range(2):
            process = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                end = time.monotonic() + 30
                current = []
                while time.monotonic() < end:
                    assert process.poll() is None, process.stderr.read().decode()
                    try:
                        current = []
                        for port in ports[:2]:
                            response = client.post(f"http://127.0.0.1:{port}/v1/federation/catalog/search",
                                json={"query": "ZZDEM2600001", "nonce": "a" * 32})
                            if response.status_code != 200 or len(response.json()["payload"]["entries"]) != 1: break
                            value = response.json()
                            current.append((value["proof"]["publicKey"], value["payload"]["nodeId"], value["payload"]["entries"]))
                        if len(current) == 2: break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                assert len(current) == 2, "Both independent catalogs must be prepared"
                assert current[0][0] != current[1][0]
                if first is None: first = current
                else: assert current == first
            finally:
                process.terminate()
                try:
                    _, error = process.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
                    pytest.fail("Federation launcher did not stop its children")
                assert process.returncode == 0, error.decode()
            assert_stopped(ports)
