#!/usr/bin/env python3
"""Fail closed on private artifacts, credentials, or oversized public Git blobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_BLOB_BYTES = 5 * 1024 * 1024
PRIVATE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".eml",
    ".mbox",
    ".mov",
    ".mp4",
    ".msg",
    ".ost",
    ".pdf",
    ".pst",
    ".xls",
    ".xlsx",
}
PRIVATE_PATH_COMPONENTS = {"legal", "mailbox", "mailboxes", "slack-export", "teams-export"}
PRIVATE_FILENAME_MARKERS = (
    "screen recording",
    "slack export",
    "teams export",
    "direct messages",
    "confidential information",
)
SECRET_PATTERNS = (
    ("private-key", re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("stripe-live-key", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
)
CREDENTIAL_KEY = re.compile(
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|ACCESS_KEY)",
    re.IGNORECASE,
)
CREDENTIAL_ASSIGNMENT = re.compile(
    r"^\s*[\"']?([A-Z][A-Z0-9_]*)[\"']?\s*[:=]\s*(.+?)\s*,?\s*$",
    re.IGNORECASE,
)
DATABASE_CREDENTIAL = re.compile(r"\b(?:postgres(?:ql)?|mysql|mariadb)://[^\s:@]+:([^\s@]+)@", re.IGNORECASE)

# Reviewed synthetic webhook, sandbox-auth and mocked MLC values in released tests.
# Each exception binds the complete historical file, path, line and generic rule.
# Working files and every modified version receive the normal credential checks.
HISTORICAL_DUMMY_FIXTURES = {
    ("backend/tests/test_api.py", "1aa5d6aade79bcce6a1a7b47636901325e260acd0c2667f980d2bad5c6cf97f2"): {880, 887, 894, 1292},
    ("backend/tests/test_api.py", "2f55891a883e3192f395cfd2bc1edb7bd7b978db59f8e7d89a4999a2f949affe"): {880, 887, 894},
    ("backend/tests/test_api.py", "71e8c72dbbaefc0af54ddcc0acae126ccb5190e9e5dc501a49b72bb9fe7cd297"): {880, 887, 894},
    ("backend/tests/test_mlc_client.py", "243efb0c0594d235f85ff735dfc3d2b4c25a4c4aa3f2830f0021f42658ffb984"): {114},
}


def run_git(root: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=text,
    )


def is_private_artifact_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    parsed = PurePosixPath(normalized)
    components = set(parsed.parts)
    if parsed.suffix in PRIVATE_EXTENSIONS:
        return True
    if components & PRIVATE_PATH_COMPONENTS:
        return True
    if "research" in components and "bmi" in components:
        return True
    filename = parsed.name.replace("_", " ").replace("-", " ")
    return any(marker in filename for marker in PRIVATE_FILENAME_MARKERS)


def credential_value_is_placeholder(value: str) -> bool:
    candidate = value.strip().rstrip(",").strip().strip("\"'").strip()
    lowered = candidate.lower()
    if not candidate or lowered in {"...", "***", "none", "null", "false", "true", "rights"}:
        return True
    if any(marker in candidate for marker in ("${", "{{", "<", ">")):
        return True
    if lowered.startswith(("os.getenv", "getattr(", "settings.", "secrets.")):
        return True
    markers = (
        "change-me",
        "change-before",
        "demo-only",
        "dev-secret",
        "example",
        "fixture",
        "placeholder",
        "sample",
        "test-secret",
        "testing",
        "workflow-verification",
        "your-",
        "your_",
    )
    return any(marker in lowered for marker in markers)


def credential_assignment_is_expression(path: str, line: str, key: str, value: str) -> bool:
    key = key.upper()
    if key.endswith(("_FIELDS", "_KEYS", "_NAMES", "_PATTERNS", "_PREFIX", "_SCOPES", "_SECRETS")):
        return True
    candidate = value.strip().rstrip(",;").strip()
    if candidate.startswith(("[", "{", "(")):
        return True
    suffix = PurePosixPath(path.lower()).suffix
    if suffix in {".py", ".js", ".jsx", ".ts", ".tsx"}:
        if re.fullmatch(r"(?:[rubfRUBF]{0,2})?[\"'].*[\"']", candidate):
            return candidate.lower().startswith(("f\"", "f'", "rf\"", "rf'", "fr\"", "fr'"))
        return True
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*\(.*\)", candidate))


def assignment_value(path: str, value: str) -> str:
    """Separate trailing comments without treating comment markers in strings as comments."""
    slash_comments = PurePosixPath(path.lower()).suffix in {".js", ".jsx", ".ts", ".tsx"}
    quote = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "#" or (slash_comments and value[index:index + 2] in {"//", "/*"}):
            return value[:index].strip().rstrip(",;").strip()
    return value.strip().rstrip(",;").strip()


def _issue(rule: str, line: int | None = None) -> dict[str, object]:
    issue: dict[str, object] = {"rule": rule}
    if line is not None:
        issue["line"] = line
    return issue


def find_content_issues(path: str, text: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for rule, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            issues.append(_issue(f"secret:{rule}", text.count("\n", 0, match.start()) + 1))

    private_names = ("Add" + "ison", "Out" + "landers", "Xo" + "der")
    personal_patterns = (
        ("bmi-email", re.compile(r"\b[A-Z0-9._%+-]+@bmi\.com\b", re.IGNORECASE)),
        ("bmi-research", re.compile(r"\bBMI\s+(?:MRMT|All\s+Hands)\b", re.IGNORECASE)),
        ("private-party", re.compile(r"\b(?:" + "|".join(private_names) + r")\b", re.IGNORECASE)),
    )
    for rule, pattern in personal_patterns:
        match = pattern.search(text)
        if match:
            issues.append(_issue(f"personal-data:{rule}", text.count("\n", 0, match.start()) + 1))

    mail_headers = sum(
        bool(re.search(rf"(?im)^{header}:\s*\S+", text))
        for header in ("From", "To", "Date", "Message-ID", "Subject")
    )
    if mail_headers >= 3:
        issues.append(_issue("personal-data:rfc822-message"))

    slack_marker = "client_" + "msg_id"
    if slack_marker in text and re.search(r'"(?:user|team|channel|ts)"\s*:', text):
        issues.append(_issue("personal-data:slack-export"))

    for line_number, line in enumerate(text.splitlines(), start=1):
        assignment = CREDENTIAL_ASSIGNMENT.match(line)
        if assignment and CREDENTIAL_KEY.search(assignment.group(1)):
            key = assignment.group(1)
            value = assignment_value(path, assignment.group(2))
            if (
                not credential_assignment_is_expression(path, line, key, value)
                and not credential_value_is_placeholder(value)
            ):
                issues.append(_issue("credential:concrete-assignment", line_number))
        for database_match in DATABASE_CREDENTIAL.finditer(line):
            if not credential_value_is_placeholder(database_match.group(1)):
                issues.append(_issue("credential:database-url", line_number))
    return issues


def _redacted_path(path: str, *, private: bool) -> str:
    if not private:
        return path
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
    return f"<redacted-private-path:{digest}>"


def _append_issues(
    errors: list[dict[str, object]],
    *,
    path: str,
    source: str,
    content: bytes,
    max_blob_bytes: int,
) -> None:
    private_path = is_private_artifact_path(path)
    display_path = _redacted_path(path, private=private_path)
    if private_path:
        errors.append({"rule": "private-artifact:path", "path": display_path, "source": source})
    if len(content) > max_blob_bytes:
        errors.append(
            {
                "rule": "large-file",
                "path": display_path,
                "source": source,
                "bytes": len(content),
            }
        )
        return
    if b"\x00" in content:
        return
    text = content.decode("utf-8", errors="replace")
    historical_dummy_lines = HISTORICAL_DUMMY_FIXTURES.get((path, hashlib.sha256(content).hexdigest()), set()) if source.startswith("git:") else set()
    for issue in find_content_issues(path, text):
        if issue["rule"] == "credential:concrete-assignment" and issue.get("line") in historical_dummy_lines:
            continue
        errors.append({**issue, "path": display_path, "source": source})


def scan_repository(root: Path = ROOT, *, max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES) -> dict[str, object]:
    root = root.resolve()
    errors: list[dict[str, object]] = []
    object_paths: dict[str, set[str]] = {}
    rev_list = run_git(root, "rev-list", "--objects", "--all").stdout
    for line in rev_list.splitlines():
        object_id, separator, path = line.partition(" ")
        if not separator or not path:
            continue
        object_paths.setdefault(object_id, set()).add(path)

    history_blob_count = 0
    for object_id, paths in sorted(object_paths.items()):
        if run_git(root, "cat-file", "-t", object_id).stdout.strip() != "blob":
            continue
        history_blob_count += 1
        content = run_git(root, "cat-file", "blob", object_id, text=False).stdout
        for path in sorted(paths):
            _append_issues(
                errors,
                path=path,
                source=f"git:{object_id[:12]}",
                content=content,
                max_blob_bytes=max_blob_bytes,
            )

    working_output = run_git(root, "ls-files", "-co", "--exclude-standard", "-z", text=False).stdout
    working_paths = [item.decode("utf-8", errors="surrogateescape") for item in working_output.split(b"\x00") if item]
    working_file_count = 0
    for path in sorted(set(working_paths)):
        candidate = root / path
        if not candidate.is_file():
            continue
        working_file_count += 1
        _append_issues(
            errors,
            path=path,
            source="working-tree",
            content=candidate.read_bytes(),
            max_blob_bytes=max_blob_bytes,
        )

    unique_errors = list({json.dumps(error, sort_keys=True): error for error in errors}.values())
    unique_errors.sort(key=lambda error: (str(error["rule"]), str(error["path"]), str(error["source"])))
    return {
        "schemaVersion": "clef.public-repository-verification.v1",
        "ok": not unique_errors,
        "historyBlobCount": history_blob_count,
        "workingFileCount": working_file_count,
        "maxBlobBytes": max_blob_bytes,
        "errors": unique_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--max-blob-bytes", type=int, default=DEFAULT_MAX_BLOB_BYTES)
    args = parser.parse_args()
    report = scan_repository(args.root, max_blob_bytes=args.max_blob_bytes)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
