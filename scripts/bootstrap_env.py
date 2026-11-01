#!/usr/bin/env python3
"""Generate an operator-owned staging environment file without external calls."""

from __future__ import annotations

import argparse
import base64
import ipaddress
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
from urllib.parse import urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from source_binding import source_url_names_revision, valid_immutable_revision


ROOT = Path(__file__).resolve().parents[1]


def https_origin(value: str, label: str, *, allow_path: bool = False) -> str:
    try:
        parsed = urlparse(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or "%" in parsed.hostname
                or any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError(f"{label} must be an HTTPS URL without credentials, query, or fragment")
    if allow_path:
        return value.rstrip("/")
    if parsed.path not in {"", "/"} or parsed.params:
        raise argparse.ArgumentTypeError(f"{label} must be a domain-level HTTPS origin, such as https://rights.example.com, with no path")
    try:
        address = ipaddress.ip_address(parsed.hostname)
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    except ValueError:
        host = parsed.hostname
        labels = host.rstrip(".").split(".")
        if (not host.isascii() or len(host) > 253
                or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in labels)
                or re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", labels[-1])):
            raise argparse.ArgumentTypeError(f"{label} requires a valid ASCII domain (punycode for international names) or a full IP address") from None
    return f"https://{host}" + (f":{parsed.port}" if parsed.port not in {None, 443} else "")


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


def write_private_atomic(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        dir=output.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            file_descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Git-ignored operator-owned environment file")
    parser.add_argument("--node-slug", required=True, help="Stable lowercase node identifier")
    parser.add_argument("--console-url", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--operator-emails", required=True)
    parser.add_argument(
        "--notification-provider",
        choices=("smtp", "mailgun", "disabled"),
        default="smtp",
    )
    parser.add_argument("--notification-from-email", default="Clef Rights <rights@example.com>")
    parser.add_argument("--mailgun-domain")
    parser.add_argument("--smtp-host")
    parser.add_argument("--smtp-port", type=int, default=587)
    parser.add_argument("--smtp-security", choices=("starttls", "implicit"), default="starttls")
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
        source_url = https_origin(args.source_url, "source URL", allow_path=True)
        operators = email_list(args.operator_emails)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    if args.sandbox_guest_access and args.deployment_mode != "public_sandbox":
        parser.error("--sandbox-guest-access requires --deployment-mode public_sandbox")
    if args.deployment_mode == "public_sandbox" and args.notification_provider != "disabled":
        parser.error("public_sandbox requires --notification-provider disabled")
    if args.deployment_mode != "public_sandbox" and args.notification_provider == "disabled":
        parser.error("adopter staging and production require smtp or mailgun notifications")
    if args.notification_provider == "mailgun" and not (
        args.mailgun_domain
        and re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", args.mailgun_domain)
    ):
        parser.error("--notification-provider mailgun requires a valid --mailgun-domain")
    if args.notification_provider == "smtp" and not args.smtp_host:
        parser.error("--notification-provider smtp requires --smtp-host")
    if args.smtp_host and (
        not re.fullmatch(r"[a-zA-Z0-9.-]+", args.smtp_host)
        or not 1 <= args.smtp_port <= 65535
    ):
        parser.error("SMTP host or port is invalid")
    if not re.fullmatch(r"[^\r\n]+<[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+>|[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", args.notification_from_email):
        parser.error("--notification-from-email must be a single mailbox or display-name mailbox")
    if not valid_immutable_revision(args.revision):
        parser.error("--revision must be a full Git commit hash")
    if not source_url_names_revision(source_url, args.revision):
        parser.error("--source-url must name --revision as an exact HTTPS path component")

    output = args.output.expanduser().resolve()
    if output.exists() and not args.force:
        parser.error(f"{output} already exists; use --force only when rotating every generated secret")
    values = {
        "APP_ENV": "production" if args.deployment_mode == "adopter_production" else "staging",
        "DEMO_MODE": "false",
        "MOCK_INTEGRATIONS": "false",
        "ALLOW_DEV_IDENTITY_HEADERS": "false",
        "ALLOW_DEV_MAGIC_LINKS": "false",
        "RIGHTS_MAGIC_LINK_SECRET": secrets.token_urlsafe(48),
        "NODE_OPERATOR_EMAILS": operators,
        "AUTH_SIGNUP_MODE": "operator_only",
        "NOTIFICATION_PROVIDER": args.notification_provider,
        "NOTIFICATION_FROM_EMAIL": args.notification_from_email,
        "MAILGUN_DOMAIN": (args.mailgun_domain or "mg.example.com").lower(),
        "SMTP_HOST": args.smtp_host or "",
        "SMTP_PORT": str(args.smtp_port),
        "SMTP_SECURITY": args.smtp_security,
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
    write_private_atomic(output, render(values))
    if args.notification_provider == "smtp":
        remaining = "database credentials plus SMTP username and password"
    elif args.notification_provider == "mailgun":
        remaining = "database credentials plus the Mailgun API key"
    else:
        remaining = "database credentials"
    print(f"wrote {output} with mode 0600; supply {remaining} in the deployment secret manager")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
