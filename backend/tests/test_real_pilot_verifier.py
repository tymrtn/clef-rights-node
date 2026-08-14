import datetime
import hashlib
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_real_pilot.py"
SPEC = importlib.util.spec_from_file_location("verify_real_pilot", SCRIPT)
assert SPEC and SPEC.loader
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def valid_manifest(evidence_digest: str, publication_url: str) -> dict:
    return {
        "schemaVersion": "clef.real-pilot-manifest.v1",
        "pilotId": "controlled-catalog-2026-01",
        "authorityOrganizationId": "authority-org",
        "requesterOrganizationId": "requester-org",
        "permissionRequestId": "permission-1",
        "workKey": "iswc:T1234567890",
        "catalogAssetId": "asset-1",
        "catalogClientReference": "client-001",
        "rightType": "composition",
        "intendedUsage": "ai_grounded_generation",
        "territory": "US",
        "authorityEvidence": {
            "source": "administration_agreement",
            "reference": "agreement-001",
            "documentSha256": evidence_digest,
        },
        "publicationUrlSha256": hashlib.sha256(publication_url.encode()).hexdigest(),
        "requiredCapabilities": ["mlc:catalog_lookup"],
        "requireProductionSource": True,
        "attestations": {name: True for name in pilot.ATTESTATIONS},
    }


def valid_bundle(manifest: dict, publication_url: str) -> dict:
    today = datetime.date.today()
    obligations = {
        "schemaVersion": "clef.license-obligations.v1",
        "attribution": {
            "required": True,
            "creditText": "Example Artist — used under license",
            "backlinkRequired": True,
            "backlinkUrl": "https://artist.invalid/rights",
            "placements": ["description", "metadata"],
            "metadataFields": {"licensor": "Authority Organization"},
        },
        "publicationReporting": {
            "required": True,
            "evidenceDueDaysAfterPublication": 30,
            "frequency": "per_publication",
        },
    }
    reviewer = {
        "type": "organization_member",
        "userId": "reviewer-user",
        "organizationId": "authority-org",
    }
    permission = {
        "id": "permission-1",
        "requester": {"organizationId": "requester-org"},
        "authority": {"organizationId": "authority-org"},
        "workKey": manifest["workKey"],
        "intendedUsage": manifest["intendedUsage"],
        "territory": "US",
        "termStart": (today - datetime.timedelta(days=1)).isoformat(),
        "termEnd": (today + datetime.timedelta(days=365)).isoformat(),
        "status": "approved",
        "provenance": {"sourceArtifact": "sha256:source-audio"},
        "licenseObligations": obligations,
        "reviewAssignment": {
            "reviewer": {"userId": "reviewer-user"},
        },
        "decidedBy": reviewer,
        "receiptId": "grant-receipt",
        "usageReports": [
            {
                "id": "usage-report-1",
                "publicationUrl": publication_url,
                "evidence": {"capturedAt": "2026-01-02", "sha256": "publication-capture"},
                "automatedChecks": {
                    "creditTextExactMatch": True,
                    "backlinkExactMatch": True,
                    "metadataExactMatches": {"licensor": True},
                    "reportedWithinDeadline": True,
                    "effect": "comparison_only",
                },
                "currentReviewOutcome": "compliant",
                "reviews": [
                    {
                        "outcome": "compliant",
                        "effectOnPermission": "none",
                        "evidence": {"captureReviewed": True},
                        "reviewedBy": reviewer,
                    }
                ],
            }
        ],
    }
    receipt_payload = {
        "receiptId": "grant-receipt",
        "node": {"id": "urn:clef:rights-node:pilot", "keyId": "ed25519:pilot"},
        "permission": {
            "requestId": "permission-1",
            "licenseObligations": obligations,
            "requestedBy": {
                "type": "organization_member",
                "userId": "requester-user",
                "organizationId": "requester-org",
            },
        },
        "authority": {
            "organizationId": "authority-org",
            "rightType": "composition",
            "territory": "US",
            "verificationStatus": "verified",
            "evidence": {
                "source": manifest["authorityEvidence"]["source"],
                "reference": manifest["authorityEvidence"]["reference"],
                "documentSha256": manifest["authorityEvidence"]["documentSha256"],
            },
        },
        "decision": {"actor": reviewer},
    }
    settlement = {
        "id": "settlement-1",
        "permissionRequestId": "permission-1",
        "requesterOrganizationId": "requester-org",
        "authorityOrganizationId": "authority-org",
        "assertionType": "paid",
        "ledgerDigest": "ledger-digest",
        "reconciliationCurrent": True,
        "totals": {
            "balanced": True,
            "obligationMinor": 15000,
            "paymentVarianceMinor": 0,
            "payoutVarianceMinor": 0,
        },
        "beneficiaries": [
            {"identifier": "artist", "shareBps": 7000},
            {"identifier": "publisher", "shareBps": 3000},
        ],
        "entries": [
            {
                "kind": "payment_received",
                "externalReference": "bank-payment-001",
                "evidence": {"statementSha256": "payment-evidence"},
            },
            {
                "kind": "payout",
                "externalReference": "artist-payout-001",
                "evidence": {"statementSha256": "artist-payout-evidence"},
            },
            {
                "kind": "payout",
                "externalReference": "publisher-payout-001",
                "evidence": {"statementSha256": "publisher-payout-evidence"},
            },
        ],
        "reconciliations": [
            {
                "id": "reconciliation-1",
                "assertionType": "paid",
                "ledgerDigest": "ledger-digest",
                "receiptId": "settlement-receipt",
            }
        ],
    }
    return {
        "node": {
            "nodeId": "urn:clef:rights-node:pilot",
            "keyId": "ed25519:pilot",
            "ephemeralSigningKey": False,
            "softwareLicense": "AGPL-3.0-only",
            "sourceCodeUrl": "https://source.invalid/releases/pilot",
            "sourceCodeRevision": "pilot-release-1",
        },
        "capabilities": {
            "mlc": [
                {
                    "name": "catalog_lookup",
                    "configured": True,
                    "authorized": True,
                    "reachable": True,
                }
            ],
            "ddex": [],
        },
        "assets": {
            "assets": [
                {
                    "id": "asset-1",
                    "workKey": manifest["workKey"],
                    "version": 1,
                    "sourceReference": "royalty-system-row-001",
                    "client": {"externalReference": "client-001"},
                }
            ]
        },
        "policy": {
            "id": "policy-1",
            "orgId": "authority-org",
            "workKey": manifest["workKey"],
            "version": 1,
            "matrix": {"usage": {manifest["intendedUsage"]: "requires_approval"}},
            "contract": {
                "policyVersion": "clef.rights-policy.v2",
                "metadata": {"simulated": False},
                "aiPolicy": {"schemaVersion": "clef.ai-policy.v1"},
            },
        },
        "permission": permission,
        "receipt": {"payload": receipt_payload},
        "receiptVerification": {
            "valid": True,
            "signatureValid": True,
            "payloadHashValid": True,
            "transparencyHashValid": True,
        },
        "settlement": settlement,
        "reconciliationReceipt": {"payload": {"receiptId": "settlement-receipt"}},
        "reconciliationVerification": {"valid": True, "signatureValid": True},
    }


def test_real_pilot_acceptance_requires_every_live_evidence_chain():
    evidence_digest = hashlib.sha256(b"private authority agreement").hexdigest()
    publication_url = "https://platform.invalid/watch/real-publication"
    manifest = pilot.validate_manifest(valid_manifest(evidence_digest, publication_url))
    report = pilot.evaluate_pilot(manifest, valid_bundle(manifest, publication_url))
    assert report["qualified"] is True
    assert report["summary"] == {"passed": 12, "failed": 0, "total": 12}
    assert report["manifestSha256"] == pilot.sha256_json(pilot.sanitized_manifest(manifest))


def test_synthetic_run_can_test_rules_but_never_qualifies():
    digest = hashlib.sha256(b"fixture").hexdigest()
    publication_url = "https://platform.invalid/watch/fixture"
    manifest = pilot.validate_manifest(valid_manifest(digest, publication_url))
    report = pilot.evaluate_pilot(
        manifest,
        valid_bundle(manifest, publication_url),
        synthetic_run=True,
    )
    assert report["summary"]["failed"] == 0
    assert report["qualified"] is False
    assert report["syntheticRun"] is True


def test_evidence_fingerprint_mismatch_fails_closed():
    digest = hashlib.sha256(b"expected agreement").hexdigest()
    publication_url = "https://platform.invalid/watch/real"
    manifest = pilot.validate_manifest(valid_manifest(digest, publication_url))
    bundle = valid_bundle(manifest, publication_url)
    bundle["receipt"]["payload"]["authority"]["evidence"]["documentSha256"] = hashlib.sha256(b"other").hexdigest()
    report = pilot.evaluate_pilot(manifest, bundle)
    assert report["qualified"] is False
    assert {failure["check"] for failure in report["failures"]} == {"signed_authority_receipt"}


def test_manifest_hashes_private_evidence_file_and_rejects_unknown_fields(tmp_path):
    evidence_file = tmp_path / "agreement.pdf"
    evidence_file.write_bytes(b"private agreement bytes")
    publication_url = "https://platform.invalid/watch/real"
    manifest = valid_manifest(hashlib.sha256(evidence_file.read_bytes()).hexdigest(), publication_url)
    manifest["authorityEvidence"]["file"] = str(evidence_file)
    normalized = pilot.validate_manifest(manifest, manifest_path=tmp_path / "manifest.json")
    assert normalized["authorityEvidence"]["file"] == str(evidence_file.resolve())
    assert "file" not in pilot.sanitized_manifest(normalized)["authorityEvidence"]

    manifest["inventedField"] = True
    with pytest.raises(pilot.PilotVerificationError, match="human review"):
        pilot.validate_manifest(manifest)


def test_manifest_rejects_truthy_strings_for_production_source_requirement():
    digest = hashlib.sha256(b"agreement").hexdigest()
    manifest = valid_manifest(digest, "https://platform.invalid/watch/real")
    manifest["requireProductionSource"] = "false"
    with pytest.raises(pilot.PilotVerificationError, match="true or false"):
        pilot.validate_manifest(manifest)
