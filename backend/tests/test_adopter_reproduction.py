from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "verify_adopter_reproduction.py"
SPEC = importlib.util.spec_from_file_location("verify_adopter_reproduction", MODULE_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def valid_report() -> dict:
    report = json.loads((ROOT / "deploy/railway/adopter-reproduction.example.json").read_text(encoding="utf-8"))
    report["operator"] = {"identifier": "adopter-reviewer-1", "role": "adopter", "isClefFounder": False}
    report["project"].update({"accountOwner": "Example Label", "projectId": "project-1"})
    report["source"] = {
        "revision": "0123456789abcdef0123456789abcdef01234567",
        "url": "https://github.com/example/clef-rights-node/tree/0123456789abcdef0123456789abcdef01234567",
        "exactRevisionVerified": True,
        "publicReachabilityStatus": 200,
        "archiveContentVerified": True,
        "archiveSha256": "a" * 64,
    }
    for service in report["services"]:
        service["status"] = "SUCCESS"
    report["verification"].update(
        {
            "finishedAt": "2026-08-16T12:42:00Z",
            "elapsedMinutes": 42,
            "deploymentVerifierPassed": True,
            "releaseVerifierPassed": True,
            "requiredReadinessStates": {key: "ready" for key in verifier.READINESS_CHECKS},
            "magicLinkDelivery": {"provider": "smtp", "accepted": True, "evidenceReference": "private://magic-link"},
            "browserAcceptance": {"passed": True, "evidenceReference": "private://browser"},
            "backupRestore": {"performed": True, "isolatedProjectId": "restore-1", "verifierPassed": True, "evidenceReference": "private://restore"},
        }
    )
    return report


def test_complete_adopter_reproduction_passes() -> None:
    assert verifier.validate(valid_report()) == []


def test_clef_secret_custody_and_public_api_fail_closed() -> None:
    report = valid_report()
    report["custody"]["clefHeldSecrets"] = True
    report["services"][1]["public"] = True
    errors = verifier.validate(report)
    assert any("Clef may not hold" in error for error in errors)
    assert any("api has an invalid public-network setting" in error for error in errors)


@pytest.mark.parametrize("report", [None, [], "private-content", {"operator": "private-content"},
    {"services": None}, {"services": [{"name": []}]}, {"custody": {"generatedInAdopterProject": [{}]}},
    {"verification": {"requiredReadinessStates": []}}, {"verification": {"backupRestore": "private-content"}},
    {"failures": ["private-content"]}])
def test_malformed_structure_returns_field_errors(report):
    errors = verifier.validate(report)
    assert errors
    assert "private-content" not in json.dumps(errors)


@pytest.mark.parametrize("field,value", [("elapsedMinutes", True), ("elapsedMinutes", float("nan")), ("elapsedMinutes", float("inf")), ("replicas", True)])
def test_non_numeric_or_non_finite_deployment_evidence_fails(field, value):
    report = valid_report()
    target = report["services"][0] if field == "replicas" else report["verification"]
    target[field] = value
    assert verifier.validate(report)


@pytest.mark.parametrize("raw", [b"[]", b'{"operator":"private-content"}', b"{invalid", b"\xff\xfe"])
def test_cli_malformed_reports_fail_with_json_instead_of_a_traceback(tmp_path, raw):
    path = tmp_path / "report.json"
    path.write_bytes(raw)
    result = subprocess.run([sys.executable, str(MODULE_PATH), "--report", str(path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout)["ok"] is False
    assert "Traceback" not in result.stderr
    assert "private-content" not in result.stdout
