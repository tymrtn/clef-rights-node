"""Exercise restart safety and configuration isolation in the actual launcher."""
import importlib.util
import json
import os
from pathlib import Path
import socket

import pytest

spec = importlib.util.spec_from_file_location("local_preview", Path(__file__).resolve().parents[2] / "scripts/run_local_preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def test_preview_restarts_with_same_signer_and_ignores_real_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.invalid/database")
    monkeypatch.setenv("MLC_ENABLED", "true")
    monkeypatch.setenv("MLC_PASSWORD", "fixture-provider-value")
    monkeypatch.setenv("RESEND_API_KEY", "fixture-mail-value")
    monkeypatch.setenv("NODE_SIGNING_PRIVATE_KEY_B64", "fixture-real-signer")
    with preview.state_lock(tmp_path):
        first = preview.preview_environment(tmp_path, 16482, 9247)
        (tmp_path / "rights.db").touch()
        second = preview.preview_environment(tmp_path, 16482, 9247)
    assert first == second
    assert first["DATABASE_URL"] == f"sqlite:///{tmp_path}/rights.db"
    assert first["NODE_SIGNING_PRIVATE_KEY_B64"] != "fixture-real-signer"
    assert first["MLC_ENABLED"] == "false"
    assert "MLC_PASSWORD" not in first and "RESEND_API_KEY" not in first
    assert first["NOTIFICATION_PROVIDER"] == "disabled"
    assert first["WEBHOOK_DELIVERY_ENABLED"] == "false"
    assert Path(first["CLEF_ENV_FILE"]).read_text() == ""
    assert (tmp_path / "local-keys.json").stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700


def test_preview_prevents_two_processes_using_same_state(tmp_path):
    with preview.state_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already in use"):
            preview.state_lock(tmp_path)
    with preview.state_lock(tmp_path):
        pass


@pytest.mark.parametrize("key_contents", [None, "", "{}", "[]", "fixture-corrupt-json"])
def test_saved_database_never_gets_a_replacement_signer(tmp_path, key_contents):
    (tmp_path / "rights.db").write_bytes(b"fixture-database")
    if key_contents is not None:
        (tmp_path / "local-keys.json").write_text(key_contents)
    with pytest.raises((RuntimeError, json.JSONDecodeError)):
        preview.preview_environment(tmp_path, 16482, 9247)
    assert (tmp_path / "rights.db").read_bytes() == b"fixture-database"


def test_symlink_state_files_are_rejected_without_touching_target(tmp_path):
    target = tmp_path / "fixture-private-target"
    target.write_text("preserve this")
    (tmp_path / "local-keys.json").symlink_to(target)
    with pytest.raises(OSError):
        preview.preview_environment(tmp_path, 16482, 9247)
    assert target.read_text() == "preserve this"


def test_occupied_port_fails_instead_of_stopping_some_other_server():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with pytest.raises(RuntimeError, match="already in use"):
            preview.free_port(server.getsockname()[1])
        assert server.fileno() >= 0


@pytest.mark.skipif(
    not (preview.ROOT / ".venv/bin/python").is_file() or not (preview.ROOT / "frontend/node_modules/vite").is_dir(),
    reason="Requires installed local preview dependencies; exercised in the local-preview CI job",
)
def test_actual_launcher_restart_preserves_tour_and_stops_both_servers(tmp_path):
    import subprocess
    import time
    import httpx

    with socket.socket() as first, socket.socket() as second:
        first.bind(("127.0.0.1", 0))
        second.bind(("127.0.0.1", 0))
        api_port, web_port = first.getsockname()[1], second.getsockname()[1]
    root = Path(__file__).resolve().parents[2]
    command = [str(root / ".venv/bin/python"), str(root / "scripts/run_local_preview.py"),
               "--state-dir", str(tmp_path), "--api-port", str(api_port), "--web-port", str(web_port)]
    session = None
    with httpx.Client(base_url=f"http://127.0.0.1:{web_port}", trust_env=False, timeout=10) as browser_api:
        for run in range(2):
            process = subprocess.Popen(command, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    assert process.poll() is None, process.stderr.read().decode()
                    try:
                        if browser_api.get("/api/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("The preview never became ready")
                info = browser_api.get("/v1/node/info").json()
                assert info["deploymentMode"] == "public_sandbox"
                if run == 0:
                    result = browser_api.post("/v1/sandbox/session")
                    assert result.status_code == 200
                    session = {"X-Session-Id": result.json()["session"]["id"]}
                    tour = browser_api.post("/v1/sandbox/tour", headers=session).json()
                    assert len(tour["sides"]) == 2
                    keys = (tmp_path / "local-keys.json").read_text()
                else:
                    resumed = browser_api.get("/v1/sandbox/tour", headers=session)
                    assert resumed.status_code == 200
                    assert [s["permissionId"] for s in resumed.json()["sides"]] == [s["permissionId"] for s in tour["sides"]]
                    assert (tmp_path / "local-keys.json").read_text() == keys
            finally:
                process.terminate()
                process.wait(timeout=15)
                shutdown_error = process.stderr.read().decode()
                process.stderr.close()
            assert process.returncode == 0, shutdown_error
            for value in (api_port, web_port):
                with socket.socket() as check:
                    assert check.connect_ex(("127.0.0.1", value)) != 0


def test_shutdown_stops_descendants_even_after_leader_has_exited(tmp_path):
    import signal
    import subprocess
    import sys
    import time
    child_file = tmp_path / 'child-ready'
    child_code = "import os,signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path(%r).write_text(str(os.getpid())); time.sleep(60)" % str(child_file)
    leader_code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',%r])" % child_code
    leader = subprocess.Popen([sys.executable, '-c', leader_code], start_new_session=True)
    leader.wait(timeout=5)
    deadline = time.monotonic() + 5
    while not child_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_file.exists()
    child_pid = int(child_file.read_text())
    try:
        preview.stop(leader, timeout=0.1)
        # An orphan can briefly remain as a zombie on a container init. It can no
        # longer execute or own listening sockets; a running process is a failure.
        result = subprocess.run(['ps','-o','stat=','-p',str(child_pid)], capture_output=True, text=True)
        assert not result.stdout.strip() or result.stdout.strip().startswith('Z')
    finally:
        try:
            os.killpg(leader.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_shutdown_handles_inaccessible_zombie_group(tmp_path, monkeypatch):
    import signal
    import subprocess
    from types import SimpleNamespace
    leader = SimpleNamespace(pid=424242, poll=lambda: 0, wait=lambda: 0)
    signals = []
    def kill_group(pid, sig):
        signals.append(sig)
        if sig == 0:
            raise PermissionError('fixture group teardown')
    monkeypatch.setattr(preview.os, 'killpg', kill_group)
    monkeypatch.setattr(preview.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='424242 0 Z\n'))
    preview.stop(leader, timeout=0.01)
    assert signal.SIGTERM in signals
    assert signal.SIGKILL not in signals
