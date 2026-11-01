import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import verify_container_preview as proof


def test_remote_context_overrides_local_host_and_is_rejected_before_mutation(monkeypatch):
    monkeypatch.setenv("DOCKER_CONTEXT", "remote-fixture")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert "DOCKER_CONTEXT" not in kwargs["env"]
        return subprocess.CompletedProcess(command, 0, json.dumps([{"Endpoints": {"docker": {"Host": "ssh://example.test"}}}]))
    monkeypatch.setattr(proof.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="local Unix-socket"):
        proof.local_daemon()
    assert calls == [["docker", "context", "inspect", "remote-fixture"]]


def test_all_docker_calls_pin_the_validated_host_after_environment_changes(monkeypatch):
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/fixture-docker.sock")
    execute = proof.local_daemon()
    monkeypatch.setenv("DOCKER_CONTEXT", "remote-fixture")
    monkeypatch.setenv("DOCKER_HOST", "ssh://example.test")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert "DOCKER_CONTEXT" not in kwargs["env"] and "DOCKER_HOST" not in kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "fixture")
    monkeypatch.setattr(proof.subprocess, "run", run)
    execute("image", "inspect", "fixture")
    execute("network", "rm", "fixture")
    assert all(command[:3] == ["docker", "--host", "unix:///tmp/fixture-docker.sock"] for command in calls)


def test_cleanup_attempts_every_resource_after_errors_and_timeouts():
    calls = []
    def fail(*args):
        calls.append(args)
        if args[-1] == "api": raise subprocess.TimeoutExpired("docker", 90)
        raise RuntimeError("Synthetic teardown failure")
    failures = proof.cleanup(fail, ["api", "web"], ["inside", "front"])
    assert len(calls) == 4
    assert {item["name"] for item in failures} == {"api", "web", "inside", "front"}


def test_python_optimization_keeps_failing_probe_and_side_effect():
    script = f"""
import sys
sys.path.insert(0, {str(SCRIPTS)!r})
from verify_container_preview import require
def probe():
    print('probe-executed')
    return False
require(probe(), 'synthetic-invalid-receipt')
"""
    result = subprocess.run([sys.executable, "-O", "-c", script], capture_output=True, text=True)
    assert result.returncode != 0
    assert "probe-executed" in result.stdout
    assert "synthetic-invalid-receipt" in result.stderr


def test_installed_package_inventory_rejects_base_image_drift():
    lock = "example-package==1.2.3 \\\n    --hash=sha256:fixture\npip==26.2.1 \\\n    --hash=sha256:fixture\n"
    proof.check_installed_packages(lock, {"Example_Package": "1.2.3"})
    with pytest.raises(RuntimeError, match="build-time package installer"):
        proof.check_installed_packages(lock, {"Example_Package": "1.2.3", "pip": "26.2.1"})
    for installed in ({"pip": "24.0"}, {"unreviewed-base-tool": "1.0"}, {}, {"pip": 26}):
        with pytest.raises(RuntimeError):
            proof.check_installed_packages(lock, installed)
