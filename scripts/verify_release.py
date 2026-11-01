#!/usr/bin/env python3
"""Match a running node's declared revision to an immutable public source revision."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from source_binding import public_source_status, source_url_names_revision, valid_immutable_revision, verify_public_source, SourceVerificationError
from verify_deployment import fetch_json


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def source_url_contains_revision(source_url: str, revision: str) -> bool:
    return source_url_names_revision(source_url, revision)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--require-source-reachable", action="store_true", help="Compatibility flag; public source content verification is always required")
    args = parser.parse_args()
    errors: list[str] = []

    if not valid_immutable_revision(args.expected_revision):
        print(json.dumps({"ok": False, "errors": ["Expected revision must be a full Git commit hash"]}))
        return 1
    try:
        info = fetch_json(f"{args.api_url.rstrip('/')}/v1/node/info")
    except RuntimeError as error:
        print(json.dumps({"ok": False, "errors": [str(error)]}))
        return 1
    local_commit = git("rev-parse", "HEAD", cwd=args.source_dir)
    try:
        resolved = git("rev-parse", f"{args.expected_revision}^{{commit}}", cwd=args.source_dir)
    except subprocess.CalledProcessError:
        resolved = ""
        errors.append("expected revision is not present in the source checkout")
    if resolved and local_commit != resolved:
        errors.append("source checkout HEAD does not match expected revision")
    if info.get("sourceCodeRevision") != args.expected_revision:
        errors.append("node declaration does not match expected revision")
    source_url = info.get("sourceCodeUrl") or ""
    if not source_url_contains_revision(source_url, args.expected_revision):
        errors.append("corresponding-source URL does not identify the expected immutable revision")
    source_status = None
    source_verification = None
    if source_url_contains_revision(source_url, args.expected_revision):
        try:
            source_status = public_source_status(source_url)
            if source_status != 200:
                errors.append(f"corresponding-source URL returned HTTP {source_status}")
            else:
                source_verification = verify_public_source(source_url, args.expected_revision, args.source_dir)
        except SourceVerificationError as error:
            errors.append(str(error))
        except Exception as error:
            errors.append(f"corresponding-source verification failed: {type(error).__name__}")
    if info.get("ephemeralSigningKey"):
        errors.append("release node uses an ephemeral signing key")
    if args.require_clean and git("status", "--porcelain", cwd=args.source_dir):
        errors.append("source checkout contains uncommitted changes")

    report = {
        "ok": not errors,
        "expectedRevision": args.expected_revision,
        "localCommit": local_commit,
        "nodeRevision": info.get("sourceCodeRevision"),
        "sourceCodeUrl": source_url,
        "sourceHttpStatus": source_status,
        "sourceVerification": source_verification,
        "keyId": info.get("keyId"),
        "errors": errors,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
