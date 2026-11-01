from __future__ import annotations

import importlib.util
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "verify_public_repository.py"
SPEC = importlib.util.spec_from_file_location("verify_public_repository", MODULE_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_private_artifact_paths_are_detected_without_disclosing_the_path() -> None:
    path = "Research/" + "BMI" + "/meeting-notes.pdf"
    assert verifier.is_private_artifact_path(path)
    errors: list[dict[str, object]] = []
    verifier._append_issues(errors, path=path, source="working-tree", content=b"notes", max_blob_bytes=1024)
    assert errors[0]["rule"] == "private-artifact:path"
    assert errors[0]["path"].startswith("<redacted-private-path:")
    assert "BMI" not in str(errors)


def test_known_secret_is_detected_without_echoing_its_value() -> None:
    token = "gh" + "p_" + ("a" * 36)
    issues = verifier.find_content_issues("config.py", f'API_TOKEN = "{token}"')
    assert any(issue["rule"] == "secret:github-token" for issue in issues)
    assert token not in str(issues)


def test_placeholders_and_public_standards_context_are_allowed() -> None:
    text = "\n".join(
        (
            "MLC and DDEX integrations require adopter authority.",
            "RIGHTS_MAGIC_LINK_SECRET=${RIGHTS_MAGIC_LINK_SECRET}",
            "POSTGRES_PASSWORD=rights",
            'API_TOKEN = "test-secret-change-me"',
            '"NODE_SIGNING_PRIVATE_KEY_B64": b64_secret(),',
            '"WEBHOOK_ENCRYPTION_KEY_B64": signing_key,',
            'API_TOKEN_PREFIX = "clef_rn_"',
        )
    )
    assert verifier.find_content_issues("env.sample", text) == []


def test_concrete_credential_assignments_are_rejected_case_insensitively() -> None:
    lines = (
        "PARTNER_API_TOKEN=correct-horse-battery-staple",
        ('config.py', 'api_token = "correct-horse-battery-staple"'),
        '"database_password": "correct-horse-battery-staple",',
        "Private_Key: correct-horse-battery-staple",
        "partnerAccess_Key=correct-horse-battery-staple",
    )
    for item in lines:
        path, line = item if isinstance(item, tuple) else ("deployment.env", item)
        issues = verifier.find_content_issues(path, line)
        assert issues == [{"rule": "credential:concrete-assignment", "line": 1}]


@pytest.mark.parametrize("path", ["backend/tests/leaked.env", "fixtures/leaked.env", "backend/tests/config.py", "fixtures/config.json"])
def test_test_and_fixture_paths_receive_concrete_credential_checks(path):
    assert verifier.find_content_issues(path, 'API_TOKEN = "correct-horse-battery-staple"') == [
        {"rule": "credential:concrete-assignment", "line": 1}]
    assert verifier.find_content_issues(path, 'API_TOKEN = "fixture-placeholder"') == []


@pytest.mark.parametrize("path,comment", [
    ("config.py", " # production"), ("backend/tests/config.py", " # example"),
    ("config.ts", "; // fixture"), ("config.js", "; /* example */"),
    ("fixtures/config.env", " # example"),
])
def test_comments_cannot_change_literal_credential_classification(path, comment):
    assert verifier.find_content_issues(path, 'API_TOKEN = "correct-horse-battery-staple"' + comment) == [
        {"rule": "credential:concrete-assignment", "line": 1}]


def test_comment_markers_inside_quotes_and_real_lookups_are_preserved():
    literal = '"correct#horse//battery"'
    assert verifier.assignment_value("config.ts", literal + " // fixture") == literal
    assert verifier.assignment_value("config.py", r'"correct\"#horse" # fixture') == r'"correct\"#horse"'
    assert verifier.find_content_issues("config.py", 'API_TOKEN = os.getenv("API_TOKEN") # production') == []


def test_reviewed_history_exception_requires_exact_content_path_rule_and_history(monkeypatch):
    path = "backend/tests/config.env"
    content = b"API_TOKEN=correct-horse-battery-staple\n"
    monkeypatch.setattr(verifier, "HISTORICAL_DUMMY_FIXTURES", {(path, hashlib.sha256(content).hexdigest()): {1}})
    def scan(target, body, source):
        issues = []
        verifier._append_issues(issues, path=target, source=source, content=body, max_blob_bytes=1024)
        return issues
    assert scan(path, content, "git:fixture") == []
    assert scan(path, content, "working-tree")
    assert scan("fixtures/config.env", content, "git:fixture")
    assert scan(path, content + b"# changed\n", "git:fixture")
    # Generic dummy exceptions never suppress provider-specific secret detection.
    provider = ("API_TOKEN=gh" + "p_" + "a" * 36 + "\n").encode()
    monkeypatch.setattr(verifier, "HISTORICAL_DUMMY_FIXTURES", {(path, hashlib.sha256(provider).hexdigest()): {1}})
    assert any(issue["rule"] == "secret:github-token" for issue in scan(path, provider, "git:fixture"))


def test_private_correspondence_markers_are_detected() -> None:
    domain = "b" + "mi.com"
    text = f"From: person@{domain}\nTo: user@example.com\nDate: Fri, 14 Aug 2026 09:00:00 -0700\nSubject: notes"
    rules = {issue["rule"] for issue in verifier.find_content_issues("notes.txt", text)}
    assert "personal-data:bmi-email" in rules
    assert "personal-data:rfc822-message" in rules


def test_large_file_is_rejected_without_reading_it_as_text() -> None:
    errors: list[dict[str, object]] = []
    verifier._append_issues(errors, path="asset.bin", source="working-tree", content=b"x" * 5, max_blob_bytes=4)
    assert errors == [{"rule": "large-file", "path": "asset.bin", "source": "working-tree", "bytes": 5}]


@pytest.mark.parametrize("generic_fixture", [False, True])
def test_deleted_secret_remains_detectable_in_public_history(tmp_path: Path, generic_fixture: bool) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Clef Tests"], cwd=tmp_path, check=True)
    token = "sk_" + "live_" + ("a" * 24)
    relative_path = "temporary-config.txt"
    expected_rule = "secret:stripe-live-key"
    if generic_fixture:
        token = "-".join(("correct", "horse", "battery", "staple"))
        relative_path = "fixtures/temporary-config.env"
        expected_rule = "credential:concrete-assignment"
    secret_path = tmp_path / relative_path
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(f"PAYMENT_API_KEY={token} # example\n", encoding="utf-8")
    subprocess.run(["git", "add", relative_path], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture with secret"], cwd=tmp_path, check=True)
    secret_path.write_text("PAYMENT_API_KEY=<configure-in-secret-manager>\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-q", "-am", "remove secret"], cwd=tmp_path, check=True)

    report = verifier.scan_repository(tmp_path)

    assert report["ok"] is False
    assert any(error["rule"] == expected_rule and str(error["source"]).startswith("git:") for error in report["errors"])
    assert token not in str(report)
