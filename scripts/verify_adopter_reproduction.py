#!/usr/bin/env python3
"""Validate the evidence record from a clean adopter-owned Railway reproduction."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import re
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from source_binding import source_url_names_revision


SCHEMA_VERSION = "clef.adopter-reproduction.v1"
SERVICE_NAMES = {"Postgres", "api", "webhook-worker", "expiry-worker", "web"}
GENERATED_SECRETS = {"RIGHTS_MAGIC_LINK_SECRET", "NODE_SIGNING_PRIVATE_KEY_B64", "WEBHOOK_ENCRYPTION_KEY_B64"}
ADOPTER_SECRETS = {"SMTP_USERNAME", "SMTP_PASSWORD"}
READINESS_CHECKS = {"database", "migrations", "signing_identity", "corresponding_source", "email_delivery", "webhook_worker", "expiry_worker"}


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def structure_errors(report: object) -> list[str]:
    if not isinstance(report, dict):
        return ["report must be a JSON object"]
    errors = []
    for name in ("operator", "project", "source", "custody", "verification"):
        if not isinstance(report.get(name, {}), dict):
            errors.append(f"{name} must be a JSON object")
    for name in ("services", "failures"):
        rows = report.get(name, [])
        if not isinstance(rows, list):
            errors.append(f"{name} must be a list")
        else:
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    errors.append(f"{name}[{index}] must be a JSON object")
                elif name == "services" and not isinstance(row.get("name"), str):
                    errors.append(f"services[{index}].name must be a string")
    custody = report.get("custody", {})
    if isinstance(custody, dict):
        for name in ("generatedInAdopterProject", "enteredAndSealedByAdopter"):
            values = custody.get(name, [])
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                errors.append(f"custody.{name} must be a list of strings")
    verification = report.get("verification", {})
    if isinstance(verification, dict):
        for name in ("requiredReadinessStates", "magicLinkDelivery", "browserAcceptance", "backupRestore"):
            if not isinstance(verification.get(name, {}), dict):
                errors.append(f"verification.{name} must be a JSON object")
    return errors


def validate(report: object) -> list[str]:
    malformed = structure_errors(report)
    if malformed:
        return malformed
    errors: list[str] = []
    if report.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("unsupported report schema")

    operator = report.get("operator", {})
    if not nonempty(operator.get("identifier")) or operator.get("role") not in ("adopter", "independent_verifier"):
        errors.append("a named or stable private adopter/independent operator is required")
    if operator.get("isClefFounder") is not False:
        errors.append("the reproduction must be performed by a second operator")

    project = report.get("project", {})
    if project.get("provider") != "railway" or not nonempty(project.get("accountOwner")) or not nonempty(project.get("projectId")):
        errors.append("an adopter-owned Railway project must be identified")
    if not timestamp(project.get("createdAt")):
        errors.append("project creation needs a timezone-aware timestamp")

    source = report.get("source", {})
    source_url = source.get("url", "")
    if not source_url_names_revision(source_url, source.get("revision")):
        errors.append("corresponding-source URL must name the exact immutable revision")
    if source.get("exactRevisionVerified") is not True or source.get("publicReachabilityStatus") != 200:
        errors.append("public corresponding source must be independently verified")
    if (source.get("archiveContentVerified") is not True
            or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("archiveSha256") or ""))):
        errors.append("include the successful release verifier's public archive comparison and SHA-256 digest")

    custody = report.get("custody", {})
    if custody.get("clefHeldSecrets") is not False or custody.get("secretValuesRecorded") is not False:
        errors.append("Clef may not hold or record adopter secret values")
    if set(custody.get("generatedInAdopterProject", [])) != GENERATED_SECRETS:
        errors.append("all three core secrets must be generated in the adopter project")
    if not ADOPTER_SECRETS <= set(custody.get("enteredAndSealedByAdopter", [])):
        errors.append("SMTP credentials must be entered and sealed by the adopter")

    services = report.get("services", [])
    by_name = {row.get("name"): row for row in services if isinstance(row, dict)}
    if set(by_name) != SERVICE_NAMES or len(services) != len(SERVICE_NAMES):
        errors.append("the report must contain exactly the five required services")
    for name, row in by_name.items():
        if row.get("status") != "SUCCESS" or type(row.get("replicas")) is not int or row.get("replicas") != 1:
            errors.append(f"{name} must have one successful deployment")
        if row.get("public") is not (name == "web"):
            errors.append(f"{name} has an invalid public-network setting")

    verification = report.get("verification", {})
    started = timestamp(verification.get("startedAt"))
    finished = timestamp(verification.get("finishedAt"))
    elapsed = verification.get("elapsedMinutes")
    valid_elapsed = type(elapsed) in (int, float) and elapsed > 0 and (not isinstance(elapsed, float) or math.isfinite(elapsed))
    if not started or not finished or finished <= started or not valid_elapsed:
        errors.append("reproduction timing must be complete and positive")
    if verification.get("deploymentVerifierPassed") is not True or verification.get("releaseVerifierPassed") is not True:
        errors.append("deployment and release verifiers must both pass")
    readiness = verification.get("requiredReadinessStates", {})
    if set(readiness) != READINESS_CHECKS or any(state != "ready" for state in readiness.values()):
        errors.append("every required readiness check must be present and ready")
    for key in ("magicLinkDelivery", "browserAcceptance"):
        result = verification.get(key, {})
        passed = result.get("accepted") if key == "magicLinkDelivery" else result.get("passed")
        if passed is not True or not nonempty(result.get("evidenceReference")):
            errors.append(f"{key} requires a passing evidence reference")
    restore = verification.get("backupRestore", {})
    if restore.get("performed") is not True or restore.get("verifierPassed") is not True or not nonempty(restore.get("isolatedProjectId")) or not nonempty(restore.get("evidenceReference")):
        errors.append("an evidenced isolated backup/restore exercise is required")

    failures = report.get("failures", [])
    if not isinstance(failures, list):
        errors.append("failures must be a list")
    else:
        for index, failure in enumerate(failures):
            if not isinstance(failure, dict) or not nonempty(failure.get("summary")) or failure.get("status") not in ("resolved", "documented_nonblocking"):
                errors.append(f"failure {index + 1} is missing a resolved or documented disposition")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        print(json.dumps({"ok": False, "errors": ["report must be a readable UTF-8 JSON document"]}, indent=2))
        return 1
    errors = validate(report)
    print(json.dumps({"ok": not errors, "report": str(args.report), "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
