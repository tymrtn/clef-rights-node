#!/usr/bin/env python3
"""Generate an operator-owned staging environment file without external calls."""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def https_origin(value: str, label: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise argparse.ArgumentTypeError(f"{label} must be an HTTPS URL without credentials, query, or fragment")
    return value.rstrip("/")


def email_list(value: str) -> str:
    emails = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not emails or any(not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", item) for item in emails):
        raise argparse.ArgumentTypeError("operator emails must be a comma-separated email list")
    return ",".join(emails)


def b64_secret(length: int = 32) -> str:
    return base64.urlsafe_b64encode(os.urandom(length)).decode("ascii").rstrip("=")


def render(values: dict[str, str]) -> str:
    lines: list[str] = []
    for line in (ROOT / "env.sample").read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0] if "=" in line and not line.startswith("#") else None
        lines.append(f"{key}={values[key]}" if key in values else line)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Git-ignored operator-owned environment file")
    parser.add_argument("--node-slug", required=True, help="Stable lowercase node identifier")
    parser.add_argument("--console-url", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--operator-emails", required=True)
    parser.add_argument("--mailgun-domain", required=True)
    parser.add_argument(
        "--deployment-mode",
        choices=("public_sandbox", "adopter_staging", "adopter_production"),
        default="adopter_staging",
    )
    parser.add_argument("--sandbox-guest-access", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", args.node_slug):
        parser.error("--node-slug must contain 3-63 lowercase letters, digits, or hyphens")
    try:
        console_url = https_origin(args.console_url, "console URL")
        source_url = https_origin(args.source_url, "source URL")
        operators = email_list(args.operator_emails)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    if not re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", args.mailgun_domain):
        parser.error("--mailgun-domain must be a domain name")
    if args.sandbox_guest_access and args.deployment_mode != "public_sandbox":
        parser.error("--sandbox-guest-access requires --deployment-mode public_sandbox")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{7,200}", args.revision):
        parser.error("--revision must be an immutable commit or release identifier")

    output = args.output.expanduser().resolve()
    if output.exists() and not args.force:
        parser.error(f"{output} already exists; use --force only when rotating every generated secret")
    values = {
        "APP_ENV": "staging",
        "DEMO_MODE": "false",
        "MOCK_INTEGRATIONS": "false",
        "ALLOW_DEV_IDENTITY_HEADERS": "false",
        "ALLOW_DEV_MAGIC_LINKS": "false",
        "RIGHTS_MAGIC_LINK_SECRET": secrets.token_urlsafe(48),
        "NODE_OPERATOR_EMAILS": operators,
        "AUTH_SIGNUP_MODE": "operator_only",
        "MAILGUN_DOMAIN": args.mailgun_domain.lower(),
        "CONSOLE_BASE_URL": console_url,
        "CORS_ALLOW_ORIGINS": console_url,
        "NODE_ID": f"urn:clef:rights-node:{args.node_slug}",
        "NODE_DEPLOYMENT_MODE": args.deployment_mode,
        "SANDBOX_GUEST_ACCESS": "true" if args.sandbox_guest_access else "false",
        "NODE_SIGNING_PRIVATE_KEY_B64": b64_secret(),
        "SOURCE_CODE_URL": source_url,
        "SOURCE_CODE_REVISION": args.revision,
        "WEBHOOK_ENCRYPTION_KEY_B64": b64_secret(),
        "WEBHOOK_DELIVERY_ENABLED": "false" if args.deployment_mode == "public_sandbox" else "true",
        "VITE_API_BASE": "/api",
        "VITE_DEMO_MODE": "false",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(values), encoding="utf-8")
    output.chmod(0o600)
    remaining = "database credentials" if args.sandbox_guest_access else "database and Mailgun credentials"
    print(f"wrote {output} with mode 0600; supply {remaining} in the deployment secret manager")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
