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
        "authority": {"organizationId": "authority-org", "claimId": "claim-1"},
        "workKey": manifest["workKey"],
        "intendedUsage": manifest["intendedUsage"],
        "territory": "US",
        "termStart": (today - datetime.timedelta(days=1)).isoformat(),
        "termEnd": (today + datetime.timedelta(days=365)).isoformat(),
        "status": "approved",
        "context": {"requestPurpose": "Synthetic pilot fixture"},
        "requestedBy": {"type": "organization_member", "userId": "requester-user", "organizationId": "requester-org"},
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
        "status": "permissioned",
        "requester": {"organizationId": "requester-org"},
        "provenance": dict(permission["provenance"]),
        "node": {"id": "urn:clef:rights-node:pilot", "keyId": "ed25519:pilot"},
        "permission": {
            "requestId": "permission-1",
            **{key: permission[key] for key in ("workKey", "intendedUsage", "territory", "termStart", "termEnd", "context")},
            "licenseObligations": obligations,
            "requestedBy": {
                "type": "organization_member",
                "userId": "requester-user",
                "organizationId": "requester-org",
            },
        },
        "authority": {
            "claimId": "claim-1",
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
        "decision": {"actor": dict(reviewer), "result": "approved"},
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
            "paymentReceivedMinor": 15000,
            "payoutMinor": 15000,
            "paymentVarianceMinor": 0,
            "payoutVarianceMinor": 0,
            "beneficiaries": [
                {
                    "beneficiaryId": "beneficiary-artist",
                    "obligationMinor": 10500,
                    "payoutMinor": 10500,
                    "varianceMinor": 0,
                },
                {
                    "beneficiaryId": "beneficiary-publisher",
                    "obligationMinor": 4500,
                    "payoutMinor": 4500,
                    "varianceMinor": 0,
                },
            ],
        },
        "beneficiaries": [
            {"id": "beneficiary-artist", "identifier": "artist", "shareBps": 7000},
            {"id": "beneficiary-publisher", "identifier": "publisher", "shareBps": 3000},
        ],
        "entries": [
            {
                "kind": "payment_received",
                "amountMinor": 15000,
                "beneficiaryId": None,
                "externalReference": "bank-payment-001",
                "evidence": {"statementSha256": "payment-evidence"},
            },
            {
                "kind": "payout",
                "amountMinor": 10500,
                "beneficiaryId": "beneficiary-artist",
                "externalReference": "artist-payout-001",
                "evidence": {"statementSha256": "artist-payout-evidence"},
            },
            {
                "kind": "payout",
                "amountMinor": 4500,
                "beneficiaryId": "beneficiary-publisher",
                "externalReference": "publisher-payout-001",
                "evidence": {"statementSha256": "publisher-payout-evidence"},
            },
        ],
        "reconciliations": [
            {
                "id": "reconciliation-1",
                "assertionType": "paid",
                "entryCount": 3,
                "ledgerDigest": "ledger-digest",
                "receiptId": "settlement-receipt",
                "totals": None,
            }
        ],
    }
    settlement["reconciliations"][0]["totals"] = settlement["totals"]
    return {
        "node": {
            "nodeId": "urn:clef:rights-node:pilot",
            "keyId": "ed25519:pilot",
            "ephemeralSigningKey": False,
            "softwareLicense": "AGPL-3.0-only",
            "sourceCodeUrl": "https://github.com/tymrtn/clef-rights-node/tree/0123456789abcdef0123456789abcdef01234567",
            "sourceCodeRevision": "0123456789abcdef0123456789abcdef01234567",
            "sourceHttpStatus": 200,
            "sourceVerification": {"verified": True, "revision": "0123456789abcdef0123456789abcdef01234567"},
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
        "reconciliationReceipt": {
            "payload": {
                "receiptId": "settlement-receipt",
                "settlement": {
                    "id": "settlement-1",
                    "reconciliationId": "reconciliation-1",
                    "ledgerDigest": "ledger-digest",
                    "entryCount": 3,
                    "totals": settlement["totals"],
                },
            }
        },
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


@pytest.mark.parametrize("path,value", [
    (("permission", "requestId"), "another-permission"),
    (("permission", "workKey"), "iswc:T0000000000"),
    (("permission", "intendedUsage"), "ai_training"),
    (("permission", "territory"), "CA"),
    (("permission", "termStart"), "2000-01-01"),
    (("permission", "termEnd"), "2099-01-01"),
    (("permission", "context"), {"requestPurpose": "Another use"}),
    (("permission", "requestedBy", "userId"), "another-requester"),
    (("permission", "requestedBy", "organizationId"), "another-requester-org"),
    (("requester", "organizationId"), "another-requester-org"),
    (("authority", "claimId"), "another-claim"),
    (("decision", "actor", "userId"), "another-reviewer"),
    (("decision", "actor", "organizationId"), "another-authority-org"),
    (("decision", "result"), "rejected"),
    (("status",), "revoked"),
    (("provenance",), {"sourceArtifact": "another-source"}),
])
def test_valid_signature_cannot_qualify_a_grant_for_a_different_transaction(path, value):
    url = "https://platform.invalid/watch/pilot"
    manifest = pilot.validate_manifest(valid_manifest(hashlib.sha256(b"agreement").hexdigest(), url))
    bundle = valid_bundle(manifest, url)
    target = bundle["receipt"]["payload"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    # Model a genuinely signed but incorrectly associated receipt: signature
    # validity alone must not establish that this is the pilot's transaction.
    assert bundle["receiptVerification"]["valid"] is True
    report = pilot.evaluate_pilot(manifest, bundle)
    assert report["qualified"] is False
    assert "signed_authority_receipt" in {failure["check"] for failure in report["failures"]}


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


def test_required_backlink_and_metadata_checks_cannot_be_omitted():
    digest = hashlib.sha256(b"agreement").hexdigest()
    publication_url = "https://platform.invalid/watch/real"
    manifest = pilot.validate_manifest(valid_manifest(digest, publication_url))

    missing_backlink = valid_bundle(manifest, publication_url)
    missing_backlink["permission"]["usageReports"][0]["automatedChecks"].pop("backlinkExactMatch")
    report = pilot.evaluate_pilot(manifest, missing_backlink)
    assert {failure["check"] for failure in report["failures"]} == {"publication_and_compliance_evidence"}

    missing_metadata = valid_bundle(manifest, publication_url)
    missing_metadata["permission"]["usageReports"][0]["automatedChecks"]["metadataExactMatches"] = {}
    report = pilot.evaluate_pilot(manifest, missing_metadata)
    assert {failure["check"] for failure in report["failures"]} == {"publication_and_compliance_evidence"}


def test_settlement_requires_evidenced_payment_and_exact_beneficiary_payouts():
    digest = hashlib.sha256(b"agreement").hexdigest()
    publication_url = "https://platform.invalid/watch/real"
    manifest = pilot.validate_manifest(valid_manifest(digest, publication_url))

    missing_payouts = valid_bundle(manifest, publication_url)
    missing_payouts["settlement"]["entries"] = missing_payouts["settlement"]["entries"][:1]
    report = pilot.evaluate_pilot(manifest, missing_payouts)
    assert "reconciled_external_payment" in {failure["check"] for failure in report["failures"]}

    missing_payment_evidence = valid_bundle(manifest, publication_url)
    missing_payment_evidence["settlement"]["entries"][0]["evidence"] = {}
    report = pilot.evaluate_pilot(manifest, missing_payment_evidence)
    assert "reconciled_external_payment" in {failure["check"] for failure in report["failures"]}

    incomplete_beneficiary = valid_bundle(manifest, publication_url)
    incomplete_beneficiary["settlement"]["entries"][2]["beneficiaryId"] = "beneficiary-artist"
    report = pilot.evaluate_pilot(manifest, incomplete_beneficiary)
    assert "reconciled_external_payment" in {failure["check"] for failure in report["failures"]}


def test_reconciliation_receipt_must_bind_settlement_and_ledger():
    digest = hashlib.sha256(b"agreement").hexdigest()
    publication_url = "https://platform.invalid/watch/real"
    manifest = pilot.validate_manifest(valid_manifest(digest, publication_url))
    bundle = valid_bundle(manifest, publication_url)
    bundle["reconciliationReceipt"]["payload"]["settlement"]["ledgerDigest"] = "different-ledger"
    report = pilot.evaluate_pilot(manifest, bundle)
    assert "signed_settlement_reconciliation" in {failure["check"] for failure in report["failures"]}


def test_production_source_requires_exact_revision_and_reachability():
    digest = hashlib.sha256(b"agreement").hexdigest()
    publication_url = "https://platform.invalid/watch/real"
    manifest = pilot.validate_manifest(valid_manifest(digest, publication_url))

    substring = valid_bundle(manifest, publication_url)
    substring["node"]["sourceCodeUrl"] += "0-not-the-release"
    report = pilot.evaluate_pilot(manifest, substring)
    assert "corresponding_source" in {failure["check"] for failure in report["failures"]}

    unreachable = valid_bundle(manifest, publication_url)
    unreachable["node"]["sourceHttpStatus"] = None
    report = pilot.evaluate_pilot(manifest, unreachable)
    assert "corresponding_source" in {failure["check"] for failure in report["failures"]}

    for proof in (None, {"verified": False}, {"verified": True, "revision": "a" * 40}):
        unrelated = valid_bundle(manifest, publication_url)
        unrelated["node"]["sourceVerification"] = proof
        report = pilot.evaluate_pilot(manifest, unrelated)
        assert "corresponding_source" in {failure["check"] for failure in report["failures"]}


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
