#!/usr/bin/env python3
"""Verify a running Rights Node and, when local, its Compose services."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def validated_origin(url: str) -> tuple[str, str, int]:
    """Allow local HTTP evaluation and require HTTPS for all remote checks."""
    try:
        if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url) or "\\" in url:
            raise ValueError()
        parsed = urlsplit(url)
        host = parsed.hostname
        if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or "%" in host):
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535 or parsed.port == 0:
            raise ValueError()
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if parsed.scheme == "http" and not loopback:
            raise ValueError()
        return parsed.scheme, host, port
    except (ValueError, TypeError):
        raise RuntimeError("Use an HTTPS deployment URL, or HTTP on localhost or a literal loopback address; omit credentials, query and fragment") from None


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if validated_origin(new_url) != validated_origin(request.full_url):
            raise RuntimeError("Deployment check refused a redirect to a different origin")
        return super().redirect_request(request, response, code, message, headers, new_url)


def safe_open(request, *, timeout: int):
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    origin = validated_origin(url)
    handlers = [SameOriginRedirect()]
    if origin[0] == "http":
        # Local HTTP credentials must stay local even when HTTP_PROXY is configured.
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


def fetch_json(url: str, *, headers: dict[str, str] | None = None) -> dict:
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with safe_open(request, timeout=10) as response:
            result = json.load(response)
            if not isinstance(result, dict):
                raise RuntimeError("Deployment endpoint must return a JSON object")
            return result
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Deployment JSON request failed ({type(error).__name__})") from None


def fetch_web(url: str) -> tuple[int, dict[str, str]]:
    try:
        with safe_open(url, timeout=10) as response:
            response.read(1)
            return response.status, {key.lower(): value for key, value in response.headers.items()}
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"Deployment web request failed ({type(error).__name__})") from None


def web_header_errors(headers: dict[str, str]) -> list[str]:
    errors = []
    for name, expected in {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "cache-control": "no-store",
    }.items():
        if headers.get(name) != expected:
            errors.append(f"web response is missing required {name}: {expected}")
    directives = {part.strip() for part in headers.get("content-security-policy", "").split(";")}
    for directive in ("default-src 'self'", "script-src 'self'", "frame-ancestors 'none'", "object-src 'none'"):
        if directive not in directives:
            errors.append(f"web response CSP is missing {directive}")
    return errors


def probe_catalog_upload(web_url: str) -> None:
    """Confirm a synthetic 10 MiB file reaches the API authentication boundary."""
    boundary = "clef-container-upload-probe"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
        + b"x" * (10 * 1024 * 1024)
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        f"{web_url.rstrip('/')}/api/v1/organizations/synthetic-probe/catalog/imports/csv",
        data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST",
    )
    try:
        with safe_open(request, timeout=30):
            raise RuntimeError("Unauthenticated catalog upload was unexpectedly accepted")
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get("detail")
        except (ValueError, AttributeError):
            detail = None
        if error.code != 401 or detail != "A session or bearer API credential is required":
            raise RuntimeError(f"Catalog upload did not reach the API authentication boundary (HTTP {error.code})") from error
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError("Catalog upload probe could not reach the web proxy") from error


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
    parser.add_argument("--probe-upload-limit", action="store_true", help="Send an unauthenticated synthetic 10 MiB upload to verify the test deployment's proxy limit")
    parser.add_argument(
        "--require-readiness",
        action="store_true",
        help="Require the operator-only readiness endpoint using CLEF_OPERATOR_SESSION_ID",
    )
    args = parser.parse_args()
    errors: list[str] = []

    # Validate both targets before reading operator credentials or contacting either server.
    try:
        validated_origin(args.api_url)
        validated_origin(args.web_url)
    except RuntimeError as error:
        print(json.dumps({"ok": False, "services": {}, "errors": [str(error)]}))
        return 1

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
        web_status, web_headers = fetch_web(args.web_url.rstrip("/"))
        if web_status != 200:
            errors.append("web root did not return HTTP 200")
        errors.extend(web_header_errors(web_headers))
        if fetch_json(f"{args.web_url.rstrip('/')}/api/health").get("status") != "ok":
            errors.append("same-origin web API proxy did not report ok")
        if args.probe_upload_limit:
            probe_catalog_upload(args.web_url)
        if args.require_readiness:
            session_id = os.environ.get("CLEF_OPERATOR_SESSION_ID", "").strip()
            if not session_id:
                errors.append("CLEF_OPERATOR_SESSION_ID is required with --require-readiness")
            else:
                readiness = fetch_json(
                    f"{args.api_url.rstrip('/')}/v1/node/readiness",
                    headers={"X-Session-Id": session_id},
                )
                if readiness.get("ready") is not True:
                    failed = [
                        row.get("key")
                        for row in readiness.get("checks", [])
                        if row.get("required") and row.get("status") != "ready"
                    ]
                    errors.append(f"operator readiness failed: {', '.join(str(key) for key in failed)}")
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
