#!/usr/bin/env python3
"""Run the fictional walkthrough on loopback with an isolated, resumable database.

Requires the repository's .venv and frontend/node_modules. Ctrl-C stops both
servers; the state directory retains the database and signing keys for restart.
"""
from __future__ import annotations

import argparse
import fcntl
import http.client
import json
import os
from pathlib import Path
import secrets
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
KEY_NAMES = ("RIGHTS_MAGIC_LINK_SECRET", "NODE_SIGNING_PRIVATE_KEY_B64", "WEBHOOK_ENCRYPTION_KEY_B64")


def private_file(path: Path):
    """Reject symlink substitutions and retain private, user-owned local state."""
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    if os.fstat(descriptor).st_uid != os.getuid():
        os.close(descriptor)
        raise RuntimeError("Preview state must belong to the current user")
    os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "r+")


def state_lock(state: Path):
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    if state.is_symlink() or state.stat().st_uid != os.getuid():
        raise RuntimeError("Use a private state directory owned by the current user")
    state.chmod(0o700)
    handle = private_file(state / "preview.lock")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("This preview state directory is already in use") from None
    return handle


def preview_environment(state: Path, web_port: int, api_port: int) -> dict[str, str]:
    keys_path = state / "local-keys.json"
    if (state / "rights.db").is_symlink():
        raise RuntimeError("Preview database must be a file within the state directory")
    # Refuse a database without its original signer instead of silently changing it.
    if (state / "rights.db").exists() and not keys_path.exists():
        raise RuntimeError("The saved database is missing its signing keys; restore the matching keys or choose a fresh state directory")
    with private_file(keys_path) as handle:
        raw = handle.read()
        if not raw and (state / "rights.db").exists():
            raise RuntimeError("The saved database is missing its signing keys; restore the matching keys")
        keys = json.loads(raw) if raw else {name: secrets.token_urlsafe(32) for name in KEY_NAMES}
        if not isinstance(keys, dict) or set(keys) != set(KEY_NAMES) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", v) for v in keys.values()):
            raise RuntimeError("Preview key file is invalid; restore the matching keys")
        if not raw:
            json.dump(keys, handle)
            handle.flush()
            os.fsync(handle.fileno())
    with private_file(state / "empty.env") as handle:
        handle.truncate(0)
    # Allow only OS runtime variables from the caller, never its provider secrets.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT") if key in os.environ}
    # Explicit defaults also override frontend .env files loaded by Vite.
    env.update(keys)
    env.update({
        "CLEF_ENV_FILE": str(state / "empty.env"),
        "APP_ENV": "development", "DATABASE_URL": f"sqlite:///{state / 'rights.db'}",
        "NODE_DEPLOYMENT_MODE": "public_sandbox", "SANDBOX_GUEST_ACCESS": "true",
        "AUTH_SIGNUP_MODE": "operator_only", "NODE_OPERATOR_EMAILS": "sandbox-operator@sandbox.invalid",
        "DEMO_MODE": "false", "MOCK_INTEGRATIONS": "false", "ALLOW_DEV_IDENTITY_HEADERS": "false",
        "ALLOW_DEV_MAGIC_LINKS": "false", "NOTIFICATION_PROVIDER": "disabled",
        "MLC_ENABLED": "false", "DDEX_ENABLED": "false", "DDEX_LIVE_MESSAGES": "false",
        "MUSICBRAINZ_ENABLED": "false", "WEBHOOK_DELIVERY_ENABLED": "false",
        "NODE_ID": "urn:clef:local-synthetic-review", "SOURCE_CODE_REVISION": "local-working-tree",
        "SOURCE_CODE_URL": "", "CORS_ALLOW_ORIGINS": f"http://127.0.0.1:{web_port}",
        "CONSOLE_BASE_URL": f"http://127.0.0.1:{web_port}", "RATE_LIMIT": "100/minute",
        "VITE_DEMO_MODE": "false", "VITE_API_BASE": "", "VITE_API_PROXY_TARGET": f"http://127.0.0.1:{api_port}",
        "PYTHONPATH": str(ROOT / "backend"), "PYTHONUNBUFFERED": "1",
    })
    return env


def free_port(port: int) -> None:
    with socket.socket() as probe:
        # A stopped server may leave TIME_WAIT connections; match server bind
        # behavior while still refusing an active listener.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(f"Port {port} is already in use; stop its server or choose another port") from None


def stop(process: subprocess.Popen, timeout: float = 8) -> None:
    # npm can exit before its Vite child: terminate the entire owned process group.
    def group_alive():
        process.poll()  # Reap our leader before probing for surviving descendants.
        try:
            os.killpg(process.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # macOS can return EPERM for a group during orphan/zombie teardown.
            # Inspect process state rather than treating an inaccessible group
            # as either a live owned server or an unconditional cleanup failure.
            result = subprocess.run(["ps", "-axo", "pgid=,uid=,stat="],
                                    capture_output=True, text=True, check=True, timeout=2)
            live = [fields for line in result.stdout.splitlines()
                    if len(fields := line.split()) == 3 and fields[0] == str(process.pid)
                    and not fields[2].startswith("Z")]
            if any(fields[1] != str(os.getuid()) for fields in live):
                raise RuntimeError("Preview process group has changed ownership; inspect it before restarting")
            return bool(live)

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    except PermissionError:
        if not group_alive():
            process.wait()
            return
        raise RuntimeError("Preview process group could not be stopped") from None
    until = time.monotonic() + timeout
    while group_alive() and time.monotonic() < until:
        time.sleep(0.05)
    if group_alive():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()
    # Let the OS reap killed descendants before releasing the preview state lock.
    until = time.monotonic() + 2
    while group_alive() and time.monotonic() < until:
        time.sleep(0.05)


def wait_ready(url: str, process: subprocess.Popen, timeout: float = 30) -> None:
    address = urlsplit(url)
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if process.poll() is not None:
            raise RuntimeError("Preview server stopped during startup; inspect the log in the state directory")
        connection = http.client.HTTPConnection("127.0.0.1", address.port, timeout=1)
        try:
            connection.request("GET", address.path or "/")
            if connection.getresponse().status == 200:
                return
        except OSError:
            pass
        finally:
            connection.close()
        time.sleep(0.1)
    raise RuntimeError("Preview startup timed out; inspect the log in the state directory")


def port(value: str) -> int:
    result = int(value)
    if not 1024 <= result <= 65535:
        raise argparse.ArgumentTypeError("Use a port between 1024 and 65535")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".cache/clef/local-preview")
    parser.add_argument("--web-port", type=port, default=16482)
    parser.add_argument("--api-port", type=port, default=9247)
    parser.add_argument("--check", action="store_true", help="Migrate and check the isolated database, then exit")
    args = parser.parse_args(argv)
    if args.web_port == args.api_port:
        parser.error("API and web ports must differ")
    python = ROOT / ".venv/bin/python"
    npm = shutil.which("npm")
    if not python.is_file() or not npm or not (ROOT / "frontend/node_modules/vite").is_dir():
        parser.error("Install dependencies first: python3 -m venv .venv; .venv/bin/python -m pip install --require-hashes -r backend/requirements.lock; npm --prefix frontend ci")
    state = args.state_dir.expanduser().absolute()
    if "?" in str(state) or "#" in str(state):
        parser.error("State directory cannot contain ? or #")
    children, logs = [], []
    lock = None
    try:
        lock = state_lock(state)
        if not args.check:
            free_port(args.api_port)
            free_port(args.web_port)
        env = preview_environment(state, args.web_port, args.api_port)
        with private_file(state / "migration.log") as migration_log:
            migration_log.seek(0, os.SEEK_END)
            for command in ([str(python), "-m", "alembic", "upgrade", "head"], [str(python), "-m", "alembic", "check"]):
                result = subprocess.run(command, cwd=ROOT / "backend", env=env, stdout=migration_log, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise RuntimeError("Preview database check failed; inspect migration.log in the state directory")
        if args.check:
            print(f"Isolated preview database is ready. State: {state}")
            return 0
        for name, command, cwd, url in (
            ("api", [str(python), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(args.api_port)], ROOT / "backend", f"http://127.0.0.1:{args.api_port}/health"),
            ("web", [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(args.web_port), "--strictPort"], ROOT / "frontend", f"http://127.0.0.1:{args.web_port}/"),
        ):
            log = private_file(state / f"{name}.log")
            log.seek(0, os.SEEK_END)
            logs.append(log)
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            children.append(child)
            wait_ready(url, child)
        print(f"Fictional walkthrough: http://127.0.0.1:{args.web_port}/\nState and logs: {state}\nCtrl-C stops both servers. Rerun the command to resume.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        raise RuntimeError("A preview server stopped; inspect its log before restarting")
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        for child in reversed(children):
            stop(child)
        for log in logs:
            log.close()
        if lock:
            lock.close()


if __name__ == "__main__":
    # SIGTERM follows the same cleanup path as Ctrl-C.
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    raise SystemExit(main())
