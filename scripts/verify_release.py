#!/usr/bin/env python3
"""Match a running node's declared revision to an immutable public source revision."""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []

    with urllib.request.urlopen(f"{args.api_url.rstrip('/')}/v1/node/info", timeout=10) as response:
        info = json.load(response)
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
    if not source_url.startswith("https://"):
        errors.append("node does not declare an HTTPS corresponding-source URL")
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
        "keyId": info.get("keyId"),
        "errors": errors,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
