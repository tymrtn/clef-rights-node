#!/usr/bin/env python3
"""Verify a running Rights Node and, when local, its Compose services."""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.error
import urllib.request


def fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{url}: {error}") from error


def fetch(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            response.read(1)
            return response.status
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"{url}: {error}") from error


def compose_states() -> dict[str, str]:
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        parsed = json.loads(result.stdout or "[]")
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return {row.get("Service", "unknown"): row.get("Health") or row.get("State", "unknown") for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:9247")
    parser.add_argument("--web-url", default="http://127.0.0.1:6482")
    parser.add_argument("--expected-revision")
    parser.add_argument("--expected-mode")
    parser.add_argument("--skip-compose", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []

    try:
        health = fetch_json(f"{args.api_url.rstrip('/')}/health")
        if health.get("status") != "ok":
            errors.append("API health did not report ok")
        info = fetch_json(f"{args.api_url.rstrip('/')}/v1/node/info")
        if not info.get("nodeId") or not info.get("publicKey") or not info.get("keyId"):
            errors.append("node identity or signing identity is incomplete")
        if args.expected_revision and info.get("sourceCodeRevision") != args.expected_revision:
            errors.append("deployed source revision does not match --expected-revision")
        if args.expected_mode and info.get("deploymentMode") != args.expected_mode:
            errors.append("deployed mode does not match --expected-mode")
        if args.expected_mode == "public_sandbox" and info.get("webhookDeliveryEnabled") is not False:
            errors.append("public sandbox exposes webhook partner delivery")
        if info.get("sourceCodeRevision") != "development" and not info.get("sourceCodeUrl"):
            errors.append("non-development deployment has no corresponding-source URL")
        if fetch(args.web_url.rstrip("/")) != 200:
            errors.append("web root did not return HTTP 200")
        if fetch_json(f"{args.web_url.rstrip('/')}/api/health").get("status") != "ok":
            errors.append("same-origin web API proxy did not report ok")
    except RuntimeError as error:
        errors.append(str(error))

    states: dict[str, str] = {}
    if not args.skip_compose:
        try:
            states = compose_states()
            expected = {"db", "api", "web", "webhook-worker", "expiry-worker"}
            missing = expected - states.keys()
            if missing:
                errors.append(f"Compose services missing: {', '.join(sorted(missing))}")
            for service in expected & states.keys():
                if states[service].lower() not in {"healthy", "running"}:
                    errors.append(f"{service} is {states[service]}")
            migration = subprocess.run(
                ["docker", "compose", "exec", "-T", "api", "alembic", "current"],
                capture_output=True,
                text=True,
            )
            if migration.returncode or "(head)" not in migration.stdout:
                errors.append("database is not at the Alembic head revision")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            errors.append(f"Compose inspection failed: {error}")

    report = {"ok": not errors, "api": args.api_url, "web": args.web_url, "services": states, "errors": errors}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
