#!/usr/bin/env python3
"""Read-only acceptance verifier for one genuine Clef Rights Node pilot."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from source_binding import public_source_status, source_url_names_revision, verify_public_source, SourceVerificationError
from verify_deployment import safe_open, validated_origin


SCHEMA_VERSION = "clef.real-pilot-manifest.v1"
REPORT_SCHEMA_VERSION = "clef.real-pilot-acceptance.v1"
ATTESTATIONS = {
    "catalogIsGenuinelyAdministered",
    "authorityEvidenceIsAuthentic",
    "requestRepresentsGenuineIntendedUse",
    "publicationEvidenceIsAuthentic",
    "settlementEvidenceRepresentsExternalTransfers",
}
MANIFEST_FIELDS = {
    "schemaVersion",
    "pilotId",
    "authorityOrganizationId",
    "requesterOrganizationId",
    "permissionRequestId",
    "workKey",
    "catalogAssetId",
    "catalogClientReference",
    "rightType",
    "intendedUsage",
    "territory",
    "authorityEvidence",
    "publicationUrlSha256",
    "requiredCapabilities",
    "requireProductionSource",
    "attestations",
}
EVIDENCE_FIELDS = {"source", "reference", "documentSha256", "file"}
KNOWN_CAPABILITIES = {
    "catalog_lookup",
    "ownership_evidence_read",
    "work_registration_write",
    "claim_submission_write",
    "permission_request_exchange",
    "usage_reporting_write",
    "royalty_statement_read",
}
AI_USAGES = {
    "ai_training_recursive",
    "ai_model_training",
    "ai_model_fine_tuning",
    "ai_grounded_generation",
    "ai_embedding_creation",
    "ai_embedding_retrieval",
    "ai_source_separation",
    "ai_music_transformation",
    "ai_lyric_analysis",
    "ai_lyric_generation",
    "ai_synthetic_voice",
}


class PilotVerificationError(RuntimeError):
    """Raised for invalid inputs or an unavailable node response."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _nonblank(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PilotVerificationError(f"{field} must be a non-blank string")
    return value.strip()


def _sha256(value: Any, field: str) -> str:
    normalized = _nonblank(value, field).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized) or normalized == "0" * 64:
        raise PilotVerificationError(f"{field} must be a non-zero SHA-256 digest")
    return normalized


def validate_manifest(raw: Any, *, manifest_path: Path | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PilotVerificationError("Pilot manifest must be a JSON object")
    unknown = sorted(set(raw) - MANIFEST_FIELDS)
    if unknown:
        raise PilotVerificationError(
            f"Unknown pilot-manifest fields require human review: {', '.join(unknown)}"
        )
    if raw.get("schemaVersion") != SCHEMA_VERSION:
        raise PilotVerificationError(f"schemaVersion must be {SCHEMA_VERSION}")

    manifest = dict(raw)
    for field in (
        "pilotId",
        "authorityOrganizationId",
        "requesterOrganizationId",
        "permissionRequestId",
        "workKey",
        "catalogClientReference",
        "rightType",
        "intendedUsage",
        "territory",
    ):
        manifest[field] = _nonblank(raw.get(field), field)
    if manifest["authorityOrganizationId"] == manifest["requesterOrganizationId"]:
        raise PilotVerificationError("Authority and requester organizations must be distinct")
    if not re.fullmatch(r"(?:mlc|iswc|isrc):[^\s]+", manifest["workKey"], flags=re.IGNORECASE):
        raise PilotVerificationError("workKey must use a durable mlc:, iswc:, or isrc: namespace")
    if raw.get("catalogAssetId") is not None:
        manifest["catalogAssetId"] = _nonblank(raw["catalogAssetId"], "catalogAssetId")

    evidence = raw.get("authorityEvidence")
    if not isinstance(evidence, dict):
        raise PilotVerificationError("authorityEvidence must be an object")
    evidence_unknown = sorted(set(evidence) - EVIDENCE_FIELDS)
    if evidence_unknown:
        raise PilotVerificationError(
            f"Unknown authority-evidence fields require human review: {', '.join(evidence_unknown)}"
        )
    normalized_evidence = {
        "source": _nonblank(evidence.get("source"), "authorityEvidence.source"),
        "reference": _nonblank(evidence.get("reference"), "authorityEvidence.reference"),
        "documentSha256": _sha256(
            evidence.get("documentSha256"), "authorityEvidence.documentSha256"
        ),
    }
    evidence_file = evidence.get("file")
    if evidence_file is not None:
        evidence_path = Path(_nonblank(evidence_file, "authorityEvidence.file")).expanduser()
        if not evidence_path.is_absolute() and manifest_path:
            evidence_path = manifest_path.parent / evidence_path
        if not evidence_path.is_file():
            raise PilotVerificationError("authorityEvidence.file is unavailable")
        if sha256_file(evidence_path) != normalized_evidence["documentSha256"]:
            raise PilotVerificationError(
                "authorityEvidence.file does not match authorityEvidence.documentSha256"
            )
        normalized_evidence["file"] = str(evidence_path.resolve())
    manifest["authorityEvidence"] = normalized_evidence
    manifest["publicationUrlSha256"] = _sha256(
        raw.get("publicationUrlSha256"), "publicationUrlSha256"
    )

    capabilities = raw.get("requiredCapabilities", [])
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
        raise PilotVerificationError("requiredCapabilities must be a string array")
    normalized_capabilities = []
    for value in capabilities:
        provider, separator, capability = value.strip().partition(":")
        if separator != ":" or provider not in {"mlc", "ddex"} or capability not in KNOWN_CAPABILITIES:
            raise PilotVerificationError(f"Unsupported required capability: {value}")
        normalized_capabilities.append(f"{provider}:{capability}")
    manifest["requiredCapabilities"] = sorted(set(normalized_capabilities))
    require_production_source = raw.get("requireProductionSource", True)
    if not isinstance(require_production_source, bool):
        raise PilotVerificationError("requireProductionSource must be true or false")
    manifest["requireProductionSource"] = require_production_source

    attestations = raw.get("attestations")
    if not isinstance(attestations, dict) or set(attestations) != ATTESTATIONS:
        raise PilotVerificationError(
            "attestations must contain exactly the five documented real-pilot attestations"
        )
    if any(attestations[name] is not True for name in ATTESTATIONS):
        raise PilotVerificationError("Every real-pilot attestation must be explicitly true")
    manifest["attestations"] = dict(attestations)
    return manifest


def sanitized_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(manifest))
    result.get("authorityEvidence", {}).pop("file", None)
    return result


class NodeClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0) -> None:
        try:
            validated_origin(base_url)
        except RuntimeError as error:
            raise PilotVerificationError(str(error)) from None
        self.base_url = base_url.rstrip("/")
        self.token = _nonblank(token, "CLEF_PILOT_API_TOKEN")
        self.timeout = timeout

    def request(self, method: str, path: str, *, body: Any = None, authenticated: bool = False) -> Any:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = canonical_json(body).encode("utf-8")
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with safe_open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get("detail")
            except Exception:
                detail = None
            raise PilotVerificationError(
                f"{method} {path} returned HTTP {error.code}: {detail or 'request failed'}"
            ) from error
        except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as error:
            raise PilotVerificationError(f"{method} {path} failed: {error}") from error


def collect_bundle(client: NodeClient, manifest: dict[str, Any]) -> dict[str, Any]:
    authority_org = quote(manifest["authorityOrganizationId"], safe="")
    work_key = quote(manifest["workKey"], safe="")
    permission_id = quote(manifest["permissionRequestId"], safe="")
    node = client.request("GET", "/v1/node/info")
    node["sourceVerification"] = None
    try:
        node["sourceHttpStatus"] = public_source_status(
            str(node.get("sourceCodeUrl") or ""),
            timeout=client.timeout,
        )
        if manifest["requireProductionSource"] and node["sourceHttpStatus"] == 200:
            node["sourceVerification"] = verify_public_source(
                node["sourceCodeUrl"], node["sourceCodeRevision"], Path(__file__).resolve().parents[1])
    except (OSError, TimeoutError, ValueError, SourceVerificationError):
        node["sourceHttpStatus"] = None
    capabilities = client.request("GET", "/v1/integrations/capabilities")
    assets = client.request(
        "GET", f"/v1/organizations/{authority_org}/catalog/assets", authenticated=True
    )
    policy = client.request(
        "GET", f"/v1/organizations/{authority_org}/rights/{work_key}", authenticated=True
    )
    permission = client.request(
        "GET", f"/v1/permission-requests/{permission_id}", authenticated=True
    )
    receipt_id = _nonblank(permission.get("receiptId"), "permission.receiptId")
    receipt = client.request("GET", f"/v1/receipts/{quote(receipt_id, safe='')}", authenticated=True)
    receipt_verification = client.request("POST", "/v1/receipts/verify", body={"receipt": receipt})
    settlement = client.request(
        "GET", f"/v1/permission-requests/{permission_id}/settlement", authenticated=True
    )
    reconciliations = settlement.get("reconciliations") or []
    reconciliation_receipt = None
    reconciliation_verification = None
    if reconciliations and reconciliations[-1].get("receiptId"):
        reconciliation_receipt = client.request(
            "GET", f"/v1/receipts/{quote(reconciliations[-1]['receiptId'], safe='')}", authenticated=True
        )
        reconciliation_verification = client.request(
            "POST", "/v1/receipts/verify", body={"receipt": reconciliation_receipt}
        )
    return {
        "node": node,
        "capabilities": capabilities,
        "assets": assets,
        "policy": policy,
        "permission": permission,
        "receipt": receipt,
        "receiptVerification": receipt_verification,
        "settlement": settlement,
        "reconciliationReceipt": reconciliation_receipt,
        "reconciliationVerification": reconciliation_verification,
    }


def _actor_key(actor: Any) -> tuple[str | None, str | None]:
    if not isinstance(actor, dict):
        return (None, None)
    if actor.get("type") == "api_credential":
        return ("api_credential", actor.get("credentialId"))
    return ("organization_member", actor.get("userId"))


def _allocate_minor_units(total_minor: int, beneficiaries: list[dict[str, Any]]) -> dict[str, int]:
    allocations: dict[str, int] = {}
    remainders: list[tuple[int, str, str]] = []
    assigned = 0
    for beneficiary in beneficiaries:
        beneficiary_id = beneficiary["id"]
        numerator = total_minor * beneficiary["shareBps"]
        amount = numerator // 10000
        allocations[beneficiary_id] = amount
        assigned += amount
        remainders.append(
            (numerator % 10000, str(beneficiary.get("identifier") or ""), beneficiary_id)
        )
    for _, _, beneficiary_id in sorted(
        remainders,
        key=lambda row: (-row[0], row[1], row[2]),
    )[: total_minor - assigned]:
        allocations[beneficiary_id] += 1
    return allocations


def evaluate_pilot(
    manifest: dict[str, Any], bundle: dict[str, Any], *, synthetic_run: bool = False
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, failure: str, **evidence: Any) -> None:
        checks.append(
            {
                "name": name,
                "status": "passed" if condition else "failed",
                "failure": None if condition else failure,
                "evidence": evidence,
            }
        )

    node = bundle.get("node") or {}
    check(
        "node_identity",
        bool(node.get("nodeId") and node.get("keyId") and not node.get("ephemeralSigningKey")),
        "Node identity is missing or uses an ephemeral signing key",
        nodeId=node.get("nodeId"),
        keyId=node.get("keyId"),
        ephemeralSigningKey=node.get("ephemeralSigningKey"),
    )
    production_source_ok = (
        node.get("softwareLicense") == "AGPL-3.0-only"
        and source_url_names_revision(node.get("sourceCodeUrl"), node.get("sourceCodeRevision"))
        and node.get("sourceHttpStatus") == 200
        and (node.get("sourceVerification") or {}).get("verified") is True
        and (node.get("sourceVerification") or {}).get("revision") == node.get("sourceCodeRevision")
    )
    check(
        "corresponding_source",
        production_source_ok or not manifest["requireProductionSource"],
        "Production pilot requires its exact public corresponding source",
        softwareLicense=node.get("softwareLicense"),
        sourceCodeRevision=node.get("sourceCodeRevision"),
        sourceCodeUrlConfigured=bool(node.get("sourceCodeUrl")),
        sourceHttpStatus=node.get("sourceHttpStatus"),
        sourceVerification=node.get("sourceVerification"),
        required=manifest["requireProductionSource"],
    )

    capability_index = {
        f"{provider}:{row.get('name')}": row
        for provider, rows in (bundle.get("capabilities") or {}).items()
        for row in (rows or [])
    }
    missing_capabilities = []
    for required in manifest["requiredCapabilities"]:
        state = capability_index.get(required) or {}
        if not state.get("configured") or not state.get("authorized") or state.get("reachable") is False:
            missing_capabilities.append(required)
    check(
        "required_adapter_capabilities",
        not missing_capabilities,
        "A required adapter capability is unavailable or unauthorized",
        required=manifest["requiredCapabilities"],
        unavailable=missing_capabilities,
    )

    assets = (bundle.get("assets") or {}).get("assets") or []
    matching_assets = [row for row in assets if row.get("workKey") == manifest["workKey"]]
    asset = matching_assets[0] if len(matching_assets) == 1 else {}
    asset_client = asset.get("client") or {}
    asset_ok = (
        len(matching_assets) == 1
        and (not manifest.get("catalogAssetId") or asset.get("id") == manifest["catalogAssetId"])
        and asset_client.get("externalReference") == manifest["catalogClientReference"]
        and bool(asset.get("sourceReference"))
    )
    check(
        "managed_catalog_asset",
        asset_ok,
        "The durable work is not uniquely present and assigned to the expected managed client",
        workKey=manifest["workKey"],
        matches=len(matching_assets),
        assetId=asset.get("id"),
        version=asset.get("version"),
        managedClientMatched=asset_client.get("externalReference") == manifest["catalogClientReference"],
        sourceReferencePresent=bool(asset.get("sourceReference")),
    )

    policy = bundle.get("policy") or {}
    contract = policy.get("contract") or {}
    usage_state = ((policy.get("matrix") or {}).get("usage") or {}).get(manifest["intendedUsage"])
    is_ai = manifest["intendedUsage"] in AI_USAGES
    ai_policy = contract.get("aiPolicy") or {}
    policy_ok = (
        policy.get("orgId") == manifest["authorityOrganizationId"]
        and policy.get("workKey") == manifest["workKey"]
        and usage_state in {"allowed", "requires_approval"}
        and (contract.get("metadata") or {}).get("simulated") is False
        and (not is_ai or contract.get("policyVersion") == "clef.rights-policy.v2")
        and (not is_ai or ai_policy.get("schemaVersion") == "clef.ai-policy.v1")
    )
    check(
        "versioned_policy",
        policy_ok,
        "The live policy is missing, simulated, blocked, or lacks the required AI policy schema",
        policyId=policy.get("id"),
        version=policy.get("version"),
        policyVersion=contract.get("policyVersion"),
        usageState=usage_state,
        aiPolicySchema=ai_policy.get("schemaVersion"),
    )

    permission = bundle.get("permission") or {}
    assignment = permission.get("reviewAssignment") or {}
    reviewer = assignment.get("reviewer") or {}
    decision_actor = permission.get("decidedBy") or {}
    reviewer_key = ("organization_member", reviewer.get("userId"))
    current_date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    permission_ok = (
        permission.get("id") == manifest["permissionRequestId"]
        and permission.get("requester", {}).get("organizationId") == manifest["requesterOrganizationId"]
        and permission.get("authority", {}).get("organizationId") == manifest["authorityOrganizationId"]
        and permission.get("workKey") == manifest["workKey"]
        and permission.get("intendedUsage") == manifest["intendedUsage"]
        and permission.get("territory") == manifest["territory"]
        and permission.get("status") == "approved"
        and bool(permission.get("termStart") and permission.get("termEnd"))
        and permission.get("termStart", "9999") <= current_date <= permission.get("termEnd", "0000")
        and bool(reviewer.get("userId"))
        and _actor_key(decision_actor) == reviewer_key
        and bool(permission.get("provenance"))
    )
    check(
        "scoped_human_decision",
        permission_ok,
        "Permission is not a current, provenance-bearing approval by its assigned human reviewer",
        permissionId=permission.get("id"),
        status=permission.get("status"),
        termStart=permission.get("termStart"),
        termEnd=permission.get("termEnd"),
        assignedReviewerPresent=bool(reviewer.get("userId")),
        assignedReviewerDecided=_actor_key(decision_actor) == reviewer_key,
        provenancePresent=bool(permission.get("provenance")),
    )

    obligations = permission.get("licenseObligations") or {}
    attribution = obligations.get("attribution") or {}
    reporting = obligations.get("publicationReporting") or {}
    obligations_ok = (
        obligations.get("schemaVersion") == "clef.license-obligations.v1"
        and attribution.get("required") is True
        and bool((attribution.get("creditText") or "").strip())
        and bool(attribution.get("placements"))
        and reporting.get("required") is True
        and isinstance(reporting.get("evidenceDueDaysAfterPublication"), int)
    )
    check(
        "exact_license_obligations",
        obligations_ok,
        "Grant lacks exact attribution and publication-reporting obligations",
        exactCreditPresent=bool((attribution.get("creditText") or "").strip()),
        placements=len(attribution.get("placements") or []),
        reportingRequired=reporting.get("required"),
        evidenceDueDays=reporting.get("evidenceDueDaysAfterPublication"),
    )

    receipt = bundle.get("receipt") or {}
    receipt_payload = receipt.get("payload") or {}
    receipt_authority = receipt_payload.get("authority") or {}
    receipt_evidence = receipt_authority.get("evidence") or {}
    evidence_expected = manifest["authorityEvidence"]
    receipt_verification = bundle.get("receiptVerification") or {}
    signed_permission = receipt_payload.get("permission") or {}
    signed_decision = receipt_payload.get("decision") or {}
    signed_requester = signed_permission.get("requestedBy") or {}
    grant_matches_permission = (
        signed_permission.get("requestId") == permission.get("id")
        and all(
            key in signed_permission and signed_permission[key] == permission.get(key)
            for key in ("workKey", "intendedUsage", "territory", "termStart", "termEnd", "context")
        )
        and receipt_payload.get("provenance") == permission.get("provenance")
        and receipt_payload.get("status") == "permissioned"
        and signed_decision.get("result") == "approved"
        and _actor_key(signed_decision.get("actor")) == reviewer_key
        and (signed_decision.get("actor") or {}).get("organizationId") == manifest["authorityOrganizationId"]
        and (receipt_payload.get("requester") or {}).get("organizationId") == manifest["requesterOrganizationId"]
        and signed_requester.get("organizationId") == manifest["requesterOrganizationId"]
        and _actor_key(signed_requester) == _actor_key(permission.get("requestedBy"))
        and bool((permission.get("authority") or {}).get("claimId"))
        and receipt_authority.get("claimId") == permission["authority"]["claimId"]
    )
    receipt_ok = (
        receipt_verification.get("valid") is True
        and grant_matches_permission
        and receipt_payload.get("receiptId") == permission.get("receiptId")
        and (receipt_payload.get("node") or {}).get("id") == node.get("nodeId")
        and (receipt_payload.get("node") or {}).get("keyId") == node.get("keyId")
        and receipt_authority.get("organizationId") == manifest["authorityOrganizationId"]
        and receipt_authority.get("rightType") == manifest["rightType"]
        and receipt_authority.get("territory") == manifest["territory"]
        and receipt_authority.get("verificationStatus") == "verified"
        and receipt_evidence.get("source") == evidence_expected["source"]
        and receipt_evidence.get("reference") == evidence_expected["reference"]
        and receipt_evidence.get("documentSha256") == evidence_expected["documentSha256"]
        and (receipt_payload.get("permission") or {}).get("licenseObligations") == obligations
    )
    check(
        "signed_authority_receipt",
        receipt_ok,
        "Signed grant does not match the permission, assigned reviewer, requester, authority evidence, node identity, or signature checks",
        receiptId=permission.get("receiptId"),
        signatureValid=receipt_verification.get("signatureValid"),
        payloadHashValid=receipt_verification.get("payloadHashValid"),
        transparencyHashValid=receipt_verification.get("transparencyHashValid"),
        authorityStatus=receipt_authority.get("verificationStatus"),
        evidenceFingerprintMatched=receipt_evidence.get("documentSha256") == evidence_expected["documentSha256"],
        grantMatchesPermission=grant_matches_permission,
    )

    requested_actor = _actor_key((receipt_payload.get("permission") or {}).get("requestedBy"))
    receipt_decision_actor = _actor_key((receipt_payload.get("decision") or {}).get("actor"))
    check(
        "requester_authority_separation",
        requested_actor[1] is not None and receipt_decision_actor[1] is not None and requested_actor != receipt_decision_actor,
        "Requester and authority decision actors are missing or identical",
        requesterActorType=requested_actor[0],
        decisionActorType=receipt_decision_actor[0],
        actorsDistinct=requested_actor != receipt_decision_actor,
    )

    reports = permission.get("usageReports") or []
    report = reports[-1] if reports else {}
    checks_result = report.get("automatedChecks") or {}
    metadata_fields = attribution.get("metadataFields")
    required_metadata_keys = set(metadata_fields) if isinstance(metadata_fields, dict) else set()
    metadata_results = checks_result.get("metadataExactMatches")
    metadata_exact = (
        isinstance(metadata_results, dict)
        and set(metadata_results) == required_metadata_keys
        and all(metadata_results[key] is True for key in required_metadata_keys)
    )
    backlink_exact = (
        checks_result.get("backlinkExactMatch") is True
        if attribution.get("backlinkRequired") is True
        else checks_result.get("backlinkExactMatch") in {True, None}
    )
    reviews = report.get("reviews") or []
    review = reviews[-1] if reviews else {}
    report_url = report.get("publicationUrl") or ""
    report_ok = (
        len(reports) > 0
        and hashlib.sha256(report_url.encode("utf-8")).hexdigest() == manifest["publicationUrlSha256"]
        and checks_result.get("creditTextExactMatch") is True
        and backlink_exact
        and metadata_exact
        and checks_result.get("reportedWithinDeadline") is True
        and checks_result.get("effect") == "comparison_only"
        and report.get("currentReviewOutcome") == "compliant"
        and review.get("outcome") == "compliant"
        and review.get("effectOnPermission") == "none"
        and bool(report.get("evidence"))
        and bool(review.get("evidence"))
        and _actor_key(review.get("reviewedBy")) == reviewer_key
    )
    check(
        "publication_and_compliance_evidence",
        report_ok,
        "Publication evidence is absent, mismatched, late, or not reviewed compliant by the assigned reviewer",
        usageReportId=report.get("id"),
        publicationUrlHashMatched=hashlib.sha256(report_url.encode("utf-8")).hexdigest() == manifest["publicationUrlSha256"] if report_url else False,
        creditExact=checks_result.get("creditTextExactMatch"),
        backlinkRequired=attribution.get("backlinkRequired") is True,
        backlinkExact=backlink_exact,
        requiredMetadataFields=len(required_metadata_keys),
        metadataExact=metadata_exact,
        reportedWithinDeadline=checks_result.get("reportedWithinDeadline"),
        complianceOutcome=review.get("outcome"),
        assignedReviewerReviewed=_actor_key(review.get("reviewedBy")) == reviewer_key,
    )

    settlement = bundle.get("settlement") or {}
    totals = settlement.get("totals") or {}
    beneficiaries = settlement.get("beneficiaries") or []
    entries = settlement.get("entries") or []
    beneficiary_ids = [row.get("id") for row in beneficiaries]
    beneficiaries_valid = (
        bool(beneficiaries)
        and all(
            isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and bool(row["id"])
            and isinstance(row.get("shareBps"), int)
            and 0 < row["shareBps"] <= 10000
            for row in beneficiaries
        )
        and len(set(beneficiary_ids)) == len(beneficiary_ids)
        and sum(row.get("shareBps", 0) for row in beneficiaries) == 10000
    )
    obligation_minor = totals.get("obligationMinor")
    allocations = (
        _allocate_minor_units(obligation_minor, beneficiaries)
        if beneficiaries_valid and isinstance(obligation_minor, int) and obligation_minor > 0
        else {}
    )
    financial_kinds = {"payment_received", "payment_reversal", "payout", "payout_reversal"}
    financial_entries = [row for row in entries if row.get("kind") in financial_kinds]
    financial_entries_valid = bool(financial_entries) and all(
        isinstance(row.get("amountMinor"), int)
        and row.get("amountMinor", 0) > 0
        and bool(row.get("externalReference"))
        and bool(row.get("evidence"))
        and (
            row.get("beneficiaryId") in allocations
            if row.get("kind") in {"payout", "payout_reversal"}
            else row.get("beneficiaryId") in {None, ""}
        )
        for row in financial_entries
    )
    payment_entries = [row for row in financial_entries if row.get("kind") in {"payment_received", "payment_reversal"}]
    payout_entries = [row for row in financial_entries if row.get("kind") in {"payout", "payout_reversal"}]
    payment_minor = sum(
        (1 if row.get("kind") == "payment_received" else -1) * row.get("amountMinor", 0)
        for row in payment_entries
    )
    payout_by_beneficiary = {
        beneficiary_id: sum(
            (1 if row.get("kind") == "payout" else -1) * row.get("amountMinor", 0)
            for row in payout_entries
            if row.get("beneficiaryId") == beneficiary_id
        )
        for beneficiary_id in allocations
    }
    payments_and_payouts_complete = (
        any(row.get("kind") == "payment_received" for row in payment_entries)
        and all(any(row.get("kind") == "payout" and row.get("beneficiaryId") == beneficiary_id for row in payout_entries) for beneficiary_id in allocations)
        and payment_minor == obligation_minor
        and payout_by_beneficiary == allocations
    )
    reported_beneficiary_totals = {
        row.get("beneficiaryId"): row
        for row in (totals.get("beneficiaries") or [])
        if isinstance(row, dict)
    }
    reported_totals_match = (
        totals.get("paymentReceivedMinor") == payment_minor
        and totals.get("payoutMinor") == sum(payout_by_beneficiary.values())
        and set(reported_beneficiary_totals) == set(allocations)
        and all(
            reported_beneficiary_totals[beneficiary_id].get("obligationMinor") == amount
            and reported_beneficiary_totals[beneficiary_id].get("payoutMinor") == payout_by_beneficiary[beneficiary_id]
            and reported_beneficiary_totals[beneficiary_id].get("varianceMinor") == 0
            for beneficiary_id, amount in allocations.items()
        )
    )
    settlement_ok = (
        settlement.get("permissionRequestId") == manifest["permissionRequestId"]
        and settlement.get("requesterOrganizationId") == manifest["requesterOrganizationId"]
        and settlement.get("authorityOrganizationId") == manifest["authorityOrganizationId"]
        and settlement.get("assertionType") == "paid"
        and settlement.get("reconciliationCurrent") is True
        and totals.get("balanced") is True
        and isinstance(obligation_minor, int)
        and obligation_minor > 0
        and totals.get("paymentVarianceMinor") == 0
        and totals.get("payoutVarianceMinor") == 0
        and beneficiaries_valid
        and financial_entries_valid
        and payments_and_payouts_complete
        and reported_totals_match
    )
    check(
        "reconciled_external_payment",
        settlement_ok,
        "Settlement is not a current, evidence-backed, balanced paid reconciliation",
        settlementId=settlement.get("id"),
        assertionType=settlement.get("assertionType"),
        reconciliationCurrent=settlement.get("reconciliationCurrent"),
        obligationMinor=totals.get("obligationMinor"),
        paymentVarianceMinor=totals.get("paymentVarianceMinor"),
        payoutVarianceMinor=totals.get("payoutVarianceMinor"),
        beneficiaryShareBps=sum(row.get("shareBps", 0) for row in beneficiaries),
        externalEvidenceComplete=financial_entries_valid,
        paymentEntries=len(payment_entries),
        payoutEntries=len(payout_entries),
        beneficiaryPayoutsComplete=payments_and_payouts_complete,
        reportedTotalsMatched=reported_totals_match,
    )

    reconciliations = settlement.get("reconciliations") or []
    latest_reconciliation = reconciliations[-1] if reconciliations else {}
    reconciliation_receipt = bundle.get("reconciliationReceipt") or {}
    reconciliation_payload = reconciliation_receipt.get("payload") or {}
    reconciliation_settlement = reconciliation_payload.get("settlement") or {}
    reconciliation_verification = bundle.get("reconciliationVerification") or {}
    reconciliation_ok = (
        latest_reconciliation.get("assertionType") == "paid"
        and latest_reconciliation.get("ledgerDigest") == settlement.get("ledgerDigest")
        and latest_reconciliation.get("receiptId") == reconciliation_payload.get("receiptId")
        and latest_reconciliation.get("entryCount") == len(entries)
        and latest_reconciliation.get("totals") == totals
        and reconciliation_settlement.get("id") == settlement.get("id")
        and reconciliation_settlement.get("reconciliationId") == latest_reconciliation.get("id")
        and reconciliation_settlement.get("ledgerDigest") == settlement.get("ledgerDigest")
        and reconciliation_settlement.get("entryCount") == len(entries)
        and reconciliation_settlement.get("totals") == totals
        and reconciliation_verification.get("valid") is True
        and reconciliation_verification.get("signatureValid") is True
    )
    check(
        "signed_settlement_reconciliation",
        reconciliation_ok,
        "Current paid reconciliation is not backed by its matching valid signed receipt",
        reconciliationId=latest_reconciliation.get("id"),
        receiptId=latest_reconciliation.get("receiptId"),
        ledgerDigestMatched=latest_reconciliation.get("ledgerDigest") == settlement.get("ledgerDigest"),
        receiptSettlementMatched=reconciliation_settlement.get("id") == settlement.get("id"),
        signatureValid=reconciliation_verification.get("signatureValid"),
    )

    failures = [
        {
            "check": row["name"],
            "message": row["failure"],
            "resolution": "human_review_or_correct_source_record",
        }
        for row in checks
        if row["status"] == "failed"
    ]
    passed = not failures
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "pilotId": manifest["pilotId"],
        "qualified": passed and not synthetic_run,
        "syntheticRun": synthetic_run,
        "manifestSha256": sha256_json(sanitized_manifest(manifest)),
        "node": {
            "nodeId": node.get("nodeId"),
            "keyId": node.get("keyId"),
            "sourceCodeRevision": node.get("sourceCodeRevision"),
        },
        "permission": {
            "permissionRequestId": manifest["permissionRequestId"],
            "workKey": manifest["workKey"],
            "receiptId": permission.get("receiptId"),
            "settlementId": settlement.get("id"),
        },
        "summary": {
            "passed": sum(row["status"] == "passed" for row in checks),
            "failed": len(failures),
            "total": len(checks),
        },
        "checks": checks,
        "failures": failures,
        "qualificationNote": (
            "Synthetic fixture runs can validate the verifier but never satisfy the real-pilot gate."
            if synthetic_run
            else None
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify one completed, genuine, evidence-backed Clef pilot without mutating the node."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--api-base", default=os.getenv("CLEF_PILOT_API_BASE", "http://127.0.0.1:9247"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--synthetic-run",
        action="store_true",
        help="Exercise the verifier without allowing a qualified result.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        raw_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        manifest = validate_manifest(raw_manifest, manifest_path=args.manifest.resolve())
        token = os.getenv("CLEF_PILOT_API_TOKEN", "")
        client = NodeClient(args.api_base, token, timeout=args.timeout)
        bundle = collect_bundle(client, manifest)
        report = evaluate_pilot(manifest, bundle, synthetic_run=args.synthetic_run)
    except (OSError, json.JSONDecodeError, PilotVerificationError) as error:
        print(f"pilot verification failed before acceptance: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(
            f"pilot={report['pilotId']} qualified={str(report['qualified']).lower()} "
            f"passed={report['summary']['passed']} failed={report['summary']['failed']} "
            f"report={args.output}"
        )
    else:
        print(rendered, end="")
    return 0 if report["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
