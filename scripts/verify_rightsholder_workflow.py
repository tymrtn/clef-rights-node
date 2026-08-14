#!/usr/bin/env python3
"""Deterministic end-to-end verifier for the Clef rightsholder transaction."""

from __future__ import annotations

import argparse
import base64
import copy
import datetime
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def configure_environment(database_path: Path, operator_email: str) -> None:
    signing_key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("=")
    values = {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{database_path}",
        "DEMO_MODE": "false",
        "MOCK_INTEGRATIONS": "false",
        "ALLOW_DEV_IDENTITY_HEADERS": "false",
        "ALLOW_DEV_MAGIC_LINKS": "true",
        "MAILGUN_API_KEY": "",
        "MLC_ENABLED": "false",
        "DDEX_ENABLED": "false",
        "MUSICBRAINZ_ENABLED": "false",
        "OPENROUTER_API_KEY": "",
        "SLACK_WEBHOOK_URL": "",
        "RIGHTS_MAGIC_LINK_SECRET": "workflow-verification-secret-change-me",
        "RIGHTS_SESSION_TTL_MINUTES": "30",
        "NODE_ID": "urn:clef:rights-node:workflow-verifier",
        "NODE_SIGNING_PRIVATE_KEY_B64": signing_key,
        "NODE_OPERATOR_EMAILS": operator_email,
        "CORS_ALLOW_ORIGINS": "http://workflow.test",
        "RATE_LIMIT": "1000/minute",
    }
    os.environ.update(values)
    sys.path.insert(0, str(BACKEND))


class WorkflowFailure(RuntimeError):
    pass


def run_workflow(database_path: Path, prefix: str, emails: dict[str, str]) -> dict:
    configure_environment(database_path, emails["operator"])

    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    migration_config = Config(str(BACKEND / "alembic.ini"))
    migration_config.set_main_option("script_location", str(BACKEND / "alembic"))
    migration_config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(migration_config, "head")

    from fastapi.testclient import TestClient  # noqa: PLC0415
    from main import AI_SAFEGUARD_KEYS, RESTRICTION_KEYS, USAGE_KEYS, SessionLocal, app, default_ai_policy, engine, webhook_secret_box  # noqa: PLC0415
    from services.database import database_revision_state  # noqa: PLC0415
    from services.webhook_outbox import process_due_webhooks  # noqa: PLC0415
    from services.webhooks import verify_webhook_signature  # noqa: PLC0415

    logging.getLogger("httpx").disabled = True

    client = TestClient(app)
    steps: list[dict] = []
    today = datetime.datetime.utcnow().date()
    term_start = today - datetime.timedelta(days=30)
    term_end = today + datetime.timedelta(days=365)
    reporting_period_end = today - datetime.timedelta(days=1)
    publication_timestamp = datetime.datetime.combine(
        reporting_period_end,
        datetime.time(hour=12),
    ).isoformat() + "Z"

    def request(method: str, path: str, *, expected: int | tuple[int, ...] = 200, **kwargs):
        response = client.request(method, path, **kwargs)
        accepted = (expected,) if isinstance(expected, int) else expected
        if response.status_code not in accepted:
            try:
                detail = response.json()
            except Exception:
                detail = response.text[:300]
            raise WorkflowFailure(f"{method} {path} returned {response.status_code}: {detail}")
        return response

    def record(name: str, **evidence) -> None:
        steps.append({"name": name, "status": "passed", "evidence": evidence})

    revision = database_revision_state(engine, backend_root=BACKEND)
    if not revision.current:
        raise WorkflowFailure("Verifier database is not at the Alembic migration head")
    record(
        "database_migrations",
        expectedHeads=sorted(revision.expected_heads),
        currentHeads=sorted(revision.current_heads),
    )

    def authenticate(email: str) -> dict[str, str]:
        invited = request("POST", "/auth/invite", expected=202, json={"email": email}).json()
        link = invited.get("devLink")
        if not link:
            raise WorkflowFailure("Verifier requires a local single-use development link")
        token = parse_qs(urlparse(link).query).get("token", [None])[0]
        if not token:
            raise WorkflowFailure("Magic-link response did not contain a token")
        validated = request("GET", "/auth/validate", params={"token": token}).json()
        session_id = validated["session"]["id"]
        replay = request("GET", "/auth/validate", expected=409, params={"token": token})
        if "already been used" not in replay.json().get("detail", ""):
            raise WorkflowFailure("Magic-link replay did not fail as one-time authentication")
        return {"X-Session-Id": session_id}

    rightsholder_headers = authenticate(emails["rightsholder"])
    operator_headers = authenticate(emails["operator"])
    requester_headers = authenticate(emails["requester"])
    client_headers = authenticate(emails["client"])
    record("one_time_authentication", users=4, replayRejected=True)

    node = request("GET", "/v1/node/info").json()
    if node["ephemeralSigningKey"]:
        raise WorkflowFailure("Verifier expected the configured durable signing key")
    record("node_identity", nodeId=node["nodeId"], keyId=node["keyId"], ephemeral=False)

    rightsholder_org = request(
        "POST",
        "/v1/organizations",
        headers=rightsholder_headers,
        json={"slug": f"{prefix}-rightsholder", "name": "Workflow Label", "organization_type": "label", "controlled_right_types": ["composition"]},
    ).json()
    requester_org = request(
        "POST",
        "/v1/organizations",
        headers=requester_headers,
        json={"slug": f"{prefix}-requester", "name": "Workflow Requester", "organization_type": "requester", "controlled_right_types": []},
    ).json()
    record("organization_isolation", rightsholderOrgId=rightsholder_org["id"], requesterOrgId=requester_org["id"])

    request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/members",
        headers=rightsholder_headers,
        json={"email": emails["client"], "role": "rights_manager"},
    )
    client_session = request("GET", "/v1/session", headers=client_headers).json()
    client_membership = next((item for item in client_session["organizations"] if item["id"] == rightsholder_org["id"]), None)
    if not client_membership or client_membership["role"] != "rights_manager" or client_session["user"]["nodeRole"] == "admin":
        raise WorkflowFailure("Client membership did not preserve organization and node-role separation")
    record("label_team_membership", clientRole="rights_manager", nodeAdmin=False)

    requester_credential = request(
        "POST",
        f"/v1/organizations/{requester_org['id']}/api-credentials",
        expected=201,
        headers=requester_headers,
        json={
            "name": "Workflow requester automation",
            "scopes": ["directory:read", "rights:read", "permissions:read", "permissions:request", "compliance:report", "settlements:read", "settlements:write", "audit:read"],
            "expires_in_days": 30,
        },
    ).json()
    rightsholder_credential = request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/api-credentials",
        expected=201,
        headers=rightsholder_headers,
        json={
            "name": "Workflow decision automation",
            "scopes": ["catalog:read", "catalog:write", "webhooks:read", "webhooks:write", "rights:read", "permissions:read", "permissions:decide", "permissions:assign", "compliance:review", "settlements:read", "settlements:write", "settlements:reconcile", "audit:read"],
            "expires_in_days": 30,
        },
    ).json()
    requester_machine_headers = {"Authorization": f"Bearer {requester_credential['token']}"}
    rightsholder_machine_headers = {"Authorization": f"Bearer {rightsholder_credential['token']}"}
    credential_list = request(
        "GET",
        f"/v1/organizations/{requester_org['id']}/api-credentials",
        headers=requester_headers,
    ).json()["credentials"]
    if not credential_list or "token" in credential_list[0]:
        raise WorkflowFailure("API credential secret was not one-time")
    cross_org = request(
        "GET",
        f"/v1/organizations/{rightsholder_org['id']}/rights",
        expected=403,
        headers=requester_machine_headers,
    )
    if "another organization" not in cross_org.json().get("detail", ""):
        raise WorkflowFailure("Organization-bound machine credential did not fail closed across tenants")
    record(
        "scoped_machine_credentials",
        requesterCredentialId=requester_credential["id"],
        rightsholderCredentialId=rightsholder_credential["id"],
        oneTimeSecrets=True,
        crossTenantRejected=True,
    )

    webhook_endpoint = request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/webhooks",
        expected=201,
        headers=rightsholder_machine_headers,
        json={"url": "https://workflow-webhook.test/clef", "events": ["rights_policy.published"]},
    ).json()
    webhook_secret = webhook_endpoint["signingSecret"]
    listed_webhooks = request(
        "GET",
        f"/v1/organizations/{rightsholder_org['id']}/webhooks",
        headers=rightsholder_machine_headers,
    ).json()["endpoints"]
    if not listed_webhooks or "signingSecret" in listed_webhooks[0]:
        raise WorkflowFailure("Webhook signing secret was not one-time")

    catalog_code = "".join(character for character in prefix.upper() if character.isalnum()) + "WORK"
    managed_client = request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/catalog/clients",
        expected=201,
        headers=rightsholder_machine_headers,
        json={
            "name": "Workflow Artist",
            "external_reference": "workflow-artist",
            "contact_email": emails["client"],
        },
    ).json()
    initial_csv = (
        "item_type,title,artist,iswc,isrc,mlc_song_code,territory,client_reference,source_reference\n"
        f"work,Workflow Work Draft,Workflow Artist,,,{catalog_code},US,workflow-artist,agreement:workflow-draft\n"
    )
    catalog_preview = request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/catalog/imports/csv",
        expected=201,
        headers=rightsholder_machine_headers,
        files={"file": ("workflow-catalog.csv", initial_csv.encode("utf-8"), "text/csv")},
    ).json()
    if catalog_preview["summary"]["counts"] != {"ready": 1}:
        raise WorkflowFailure("Catalog preview did not classify the valid durable row as ready")
    request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/catalog/imports/{catalog_preview['id']}/commit",
        expected=422,
        headers=rightsholder_machine_headers,
        json={"confirm_import": False},
    )
    catalog_commit = request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/catalog/imports/{catalog_preview['id']}/commit",
        headers=rightsholder_machine_headers,
        json={"confirm_import": True},
    ).json()
    record(
        "catalog_preview_commit",
        batchId=catalog_commit["id"],
        managedClientId=managed_client["id"],
        imported=1,
        explicitConfirmationRequired=True,
        authorityCreated=False,
    )

    corrected_csv = (
        "item_type,title,artist,iswc,isrc,mlc_song_code,territory,client_reference,source_reference\n"
        f"work,Workflow Work,Workflow Artist,,,{catalog_code},US,workflow-artist,agreement:workflow-final\n"
    )
    correction_preview = request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/catalog/imports/csv",
        expected=201,
        headers=rightsholder_machine_headers,
        files={"file": ("workflow-catalog-correction.csv", corrected_csv.encode("utf-8"), "text/csv")},
    ).json()
    correction_row = correction_preview["rows"][0]
    if correction_row["status"] != "conflict" or correction_row["existingAsset"]["version"] != 1:
        raise WorkflowFailure("Catalog correction did not require explicit conflict resolution")
    request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/catalog/imports/{correction_preview['id']}/rows/{correction_row['id']}/resolution",
        headers=rightsholder_machine_headers,
        json={"resolution": "new_version", "note": "Final executed catalog schedule corrected the provisional title"},
    )
    request(
        "POST",
        f"/v1/organizations/{rightsholder_org['id']}/catalog/imports/{correction_preview['id']}/commit",
        headers=rightsholder_machine_headers,
        json={"confirm_import": True},
    )
    catalog_history = request(
        "GET",
        f"/v1/organizations/{rightsholder_org['id']}/catalog/assets?include_history=true",
        headers=rightsholder_machine_headers,
    ).json()["assets"]
    if [asset["version"] for asset in catalog_history] != [2, 1] or any(asset["authorityStatus"] != "unverified" for asset in catalog_history):
        raise WorkflowFailure("Catalog correction did not preserve immutable versions without authority")
    record(
        "catalog_immutable_correction",
        workKey=f"mlc:{catalog_code}",
        versions=[2, 1],
        clientReference="workflow-artist",
        authorityStatus="unverified",
    )

    usage = {key: "blocked" for key in USAGE_KEYS}
    usage["derivative_remix"] = "requires_approval"
    usage["ai_grounded_generation"] = "requires_approval"
    restrictions = {key: "allowed" for key in RESTRICTION_KEYS}
    ai_policy = default_ai_policy("review_each_ai_use")
    ai_policy["modelScopes"]["public_or_open_weights"] = "blocked"
    ai_policy["limits"] = {
        "maxSourceDurationSeconds": 180,
        "maxOutputDurationSeconds": 240,
        "maxLyricCharacters": 5000,
        "sourceRetentionDays": 7,
        "embeddingRetentionDays": 30,
    }
    work_key = f"mlc:{catalog_code}"
    policy = request(
        "PUT",
        f"/v1/organizations/{rightsholder_org['id']}/rights/{work_key}",
        headers=rightsholder_headers,
        json={
            "artist_name": "Workflow Artist",
            "expected_version": 0,
            "note": "End-to-end workflow fixture",
            "contract": {
                "policyVersion": "clef.rights-policy.v2",
                "matrix": {"usage": usage, "restrictions": restrictions},
                "aiPolicy": ai_policy,
                "metadata": {
                    "fixture": "verify_rightsholder_workflow",
                    "workTitle": "Workflow Work",
                },
            },
        },
    ).json()
    if policy["version"] != 1:
        raise WorkflowFailure("Initial policy version was not 1")
    record("policy_publication", workKey=work_key, policyId=policy["id"], version=policy["version"])

    captured_webhook: dict = {}

    class WebhookAccepted:
        status_code = 204

    def webhook_transport(url: str, **kwargs):
        captured_webhook.update({"url": url, **kwargs})
        return WebhookAccepted()

    webhook_db = SessionLocal()
    try:
        webhook_result = process_due_webhooks(
            webhook_db,
            secret_box=webhook_secret_box,
            allow_private_targets=False,
            max_attempts=6,
            request_timeout_seconds=10,
            transport=webhook_transport,
            target_validator=lambda _url: None,
        )
    finally:
        webhook_db.close()
    webhook_timestamp = int(captured_webhook["headers"]["X-Clef-Timestamp"])
    if webhook_result["delivered"] != 1 or not verify_webhook_signature(
        secret=webhook_secret,
        timestamp=webhook_timestamp,
        body=captured_webhook["data"],
        signature=captured_webhook["headers"]["X-Clef-Signature"],
        now=webhook_timestamp,
    ):
        raise WorkflowFailure("Durable webhook delivery or signature verification failed")
    webhook_delivery = request(
        "GET",
        f"/v1/organizations/{rightsholder_org['id']}/webhook-deliveries",
        headers=rightsholder_machine_headers,
    ).json()["deliveries"][0]
    if webhook_delivery["status"] != "succeeded" or len(webhook_delivery["attempts"]) != 1:
        raise WorkflowFailure("Webhook attempt history did not preserve successful delivery")
    record(
        "durable_webhook_delivery",
        endpointId=webhook_endpoint["id"],
        deliveryId=webhook_delivery["id"],
        event=webhook_delivery["event"],
        encryptedSecret=True,
        signatureValid=True,
        attemptHistory=1,
    )

    claim = request(
        "POST",
        "/v1/authority-claims",
        headers=rightsholder_headers,
        json={
            "org_id": rightsholder_org["id"],
            "rights_contract_id": policy["id"],
            "right_type": "composition",
            "territory": "US",
            "evidence": {
                "source": "workflow_fixture",
                "mlcSongCode": catalog_code,
                "share": "100.0000",
            },
        },
    ).json()
    request(
        "POST",
        f"/v1/authority-claims/{claim['id']}/verify",
        headers=operator_headers,
        json={"evidence_note": "Deterministic fixture matched the declared composition"},
    )
    record("authority_verification", claimId=claim["id"], rightType="composition", territory="US")

    directory = request("GET", "/v1/directory/authority-claims", headers=requester_machine_headers).json()
    visible = next((item for item in directory["claims"] if item["id"] == claim["id"]), None)
    if not visible or "evidence" in visible:
        raise WorkflowFailure("Verified claim was absent from the sanitized authority directory")
    if visible.get("workTitle") != "Workflow Work":
        raise WorkflowFailure("Sanitized directory did not preserve the human-readable work title")
    record("sanitized_directory", claimVisible=True, privateEvidenceExcluded=True, workTitle=visible["workTitle"])

    permission = request(
        "POST",
        "/v1/permission-requests",
        headers=requester_machine_headers,
        json={
            "requester_org_id": requester_org["id"],
            "authority_claim_id": claim["id"],
            "intended_usage": "derivative_remix",
            "territory": "US",
            "term_start": term_start.isoformat(),
            "term_end": term_end.isoformat(),
            "context": {"releaseTitle": "Workflow Remix"},
            "provenance": {"sourceAssetDigest": "sha256:workflow-fixture"},
        },
    ).json()
    if permission["status"] != "pending" or permission["policyState"] != "requires_approval":
        raise WorkflowFailure("Permission request did not enter the expected approval state")
    record("permission_request", permissionId=permission["id"], status="pending", policyState="requires_approval")

    outbound = request(
        "GET",
        f"/v1/organizations/{requester_org['id']}/permission-requests",
        headers=requester_machine_headers,
    ).json()["permissionRequests"]
    inbound = request(
        "GET",
        f"/v1/organizations/{rightsholder_org['id']}/permission-requests",
        headers=rightsholder_machine_headers,
    ).json()["permissionRequests"]
    if outbound[0]["directions"] != ["outbound"] or inbound[0]["directions"] != ["inbound"]:
        raise WorkflowFailure("Permission ledgers did not preserve requester/rightsholder direction")
    if outbound[0].get("workTitle") != "Workflow Work" or inbound[0].get("workTitle") != "Workflow Work":
        raise WorkflowFailure("Permission ledgers did not preserve the human-readable work title")
    record("permission_ledgers", requesterDirection="outbound", rightsholderDirection="inbound", workTitle="Workflow Work")

    decision = request(
        "POST",
        f"/v1/permission-requests/{permission['id']}/decide",
        headers=rightsholder_machine_headers,
        json={"decision": "approved", "note": "Approved for the declared scope only"},
    ).json()
    receipt = decision.get("receipt")
    if decision["status"] != "approved" or not receipt:
        raise WorkflowFailure("Approved decision did not issue a receipt")
    if receipt["payload"]["permission"]["requestedBy"].get("credentialId") != requester_credential["id"]:
        raise WorkflowFailure("Signed receipt did not preserve the requester machine actor")
    if receipt["payload"]["decision"]["actor"].get("credentialId") != rightsholder_credential["id"]:
        raise WorkflowFailure("Signed receipt did not preserve the decision machine actor")
    receipt_id = receipt["payload"]["receiptId"]
    record(
        "rightsholder_decision",
        decision="approved",
        receiptId=receipt_id,
        requesterActor="api_credential",
        decisionActor="api_credential",
    )

    stored_receipt = request("GET", f"/v1/receipts/{receipt_id}").json()
    verification = request("POST", "/v1/receipts/verify", json={"receipt": stored_receipt}).json()
    if not all(verification[key] for key in ("valid", "payloadHashValid", "signatureValid", "transparencyHashValid")):
        raise WorkflowFailure(f"Issued receipt did not verify: {verification}")
    tampered = copy.deepcopy(stored_receipt)
    tampered["payload"]["permission"]["intendedUsage"] = "ads_brand"
    tamper_check = request("POST", "/v1/receipts/verify", json={"receipt": tampered}).json()
    if tamper_check["valid"] or tamper_check["payloadHashValid"]:
        raise WorkflowFailure("Tampered receipt was not rejected")
    record(
        "receipt_verification",
        receiptId=receipt_id,
        payloadHash=stored_receipt["proof"]["payloadHash"],
        signatureValid=True,
        tamperRejected=True,
    )

    settlement = request(
        "POST",
        f"/v1/permission-requests/{permission['id']}/settlement",
        expected=201,
        headers=rightsholder_machine_headers,
        json={
            "currency": "USD",
            "minimum_commitment_minor": 10000,
            "minimum_recoupable": True,
            "royalty_rate_bps": 1000,
            "royalty_basis": "net_revenue",
            "beneficiaries": [
                {"name": "Workflow Artist", "identifier": "party:workflow-artist", "share_bps": 7000},
                {"name": "Workflow Publisher", "identifier": "party:workflow-publisher", "share_bps": 3000},
            ],
            "terms": {"statementFrequency": "quarterly", "fixture": "verify_rightsholder_workflow"},
            "confirm_immutable_terms": True,
        },
    ).json()
    if settlement["assertionType"] != "provisional" or settlement["totals"]["obligationMinor"] != 10000:
        raise WorkflowFailure("Settlement terms did not begin as a provisional minimum obligation")
    record(
        "settlement_terms",
        settlementId=settlement["id"],
        assertionType="provisional",
        minimumCommitmentMinor=10000,
        beneficiaryShareBps=10000,
    )

    reserve = request(
        "POST",
        f"/v1/settlements/{settlement['id']}/entries",
        expected=201,
        headers=requester_machine_headers,
        json={"kind": "reserve", "amount_minor": 10000, "idempotency_key": "workflow-reserve"},
    ).json()
    royalty = request(
        "POST",
        f"/v1/settlements/{settlement['id']}/royalty-calculations",
        expected=201,
        headers=rightsholder_machine_headers,
        json={
            "basis_amount_minor": 150000,
            "period_start": term_start.isoformat(),
            "period_end": reporting_period_end.isoformat(),
            "external_reference": "statement:workflow-2026-q3",
            "evidence": {"sha256": "1" * 64},
            "idempotency_key": "workflow-royalty-2026-q3",
        },
    ).json()
    if reserve["recordedBy"].get("credentialId") != requester_credential["id"] or royalty["amountMinor"] != 15000:
        raise WorkflowFailure("Reserve or royalty accrual did not preserve the expected actor and exact calculation")
    record(
        "reserve_and_royalty",
        reserveMinor=10000,
        royaltyMinor=15000,
        reserveIsPermission=False,
        rounding=royalty["calculation"]["rounding"],
    )

    beneficiaries = {row["identifier"]: row["id"] for row in settlement["beneficiaries"]}

    def financial_entry(kind: str, amount_minor: int, external_reference: str, beneficiary_id: str | None = None):
        return request(
            "POST",
            f"/v1/settlements/{settlement['id']}/entries",
            expected=201,
            headers=rightsholder_machine_headers,
            json={
                "kind": kind,
                "amount_minor": amount_minor,
                "beneficiary_id": beneficiary_id,
                "external_reference": external_reference,
                "evidence": {"sha256": external_reference.encode("utf-8").hex()},
                "idempotency_key": external_reference,
            },
        ).json()

    payment = financial_entry("payment_received", 15000, "bank:workflow-payment")
    artist_payout = financial_entry("payout", 10500, "bank:workflow-artist-payout", beneficiaries["party:workflow-artist"])
    publisher_payout = financial_entry("payout", 4500, "bank:workflow-publisher-payout", beneficiaries["party:workflow-publisher"])
    if any(row["recordedBy"].get("credentialId") != rightsholder_credential["id"] for row in (payment, artist_payout, publisher_payout)):
        raise WorkflowFailure("Payment and payout evidence did not preserve the rightsholder machine actor")
    record(
        "external_payment_and_payouts",
        paymentReceivedMinor=15000,
        artistPayoutMinor=10500,
        publisherPayoutMinor=4500,
        externalEvidence=True,
    )

    reconciliation = request(
        "POST",
        f"/v1/settlements/{settlement['id']}/reconciliations",
        expected=201,
        headers=rightsholder_machine_headers,
        json={
            "idempotency_key": "workflow-reconciliation-paid",
            "evidence": {"review": "Deterministic fixture matched payment and beneficiary payouts"},
        },
    ).json()
    settled = request(
        "GET",
        f"/v1/permission-requests/{permission['id']}/settlement",
        headers=requester_machine_headers,
    ).json()
    if reconciliation["assertionType"] != "paid" or reconciliation["status"] != "balanced":
        raise WorkflowFailure("Balanced payment and payouts did not produce a paid reconciliation")
    if settled["assertionType"] != "paid" or not settled["reconciliationCurrent"] or not settled["totals"]["balanced"]:
        raise WorkflowFailure("The settlement read model did not preserve the current paid assertion")
    reconciliation_receipt = request("GET", f"/v1/receipts/{reconciliation['receiptId']}").json()
    reconciliation_verification = request(
        "POST",
        "/v1/receipts/verify",
        json={"receipt": reconciliation_receipt},
    ).json()
    if not reconciliation_verification["valid"]:
        raise WorkflowFailure("Settlement reconciliation receipt did not verify")
    if reconciliation_receipt["payload"]["settlement"]["ledgerDigest"] != reconciliation["ledgerDigest"]:
        raise WorkflowFailure("Signed settlement receipt did not preserve the reconciled ledger digest")
    record(
        "reconciled_payment",
        reconciliationId=reconciliation["id"],
        receiptId=reconciliation["receiptId"],
        ledgerDigest=reconciliation["ledgerDigest"],
        assertionType="paid",
        signatureValid=True,
        paymentVarianceMinor=settled["totals"]["paymentVarianceMinor"],
        payoutVarianceMinor=settled["totals"]["payoutVarianceMinor"],
    )

    ai_use = {
        "inputAssets": ["full_mix"],
        "modelScope": "private_single_tenant",
        "acceptedSafeguards": list(AI_SAFEGUARD_KEYS),
        "sourceDurationSeconds": 120,
        "outputDurationSeconds": 180,
        "lyricCharacters": 0,
        "sourceRetentionDays": 7,
        "embeddingRetentionDays": 30,
    }
    ai_permission = request(
        "POST",
        "/v1/permission-requests",
        headers=requester_headers,
        json={
            "requester_org_id": requester_org["id"],
            "authority_claim_id": claim["id"],
            "intended_usage": "ai_grounded_generation",
            "territory": "US",
            "term_start": term_start.isoformat(),
            "term_end": term_end.isoformat(),
            "context": {"releaseTitle": "Workflow Grounding Study", "aiUse": ai_use},
            "provenance": {"sourceAssetDigest": "sha256:workflow-ai-fixture"},
        },
    ).json()
    if ai_permission["status"] != "pending" or ai_permission["policyState"] != "requires_approval":
        raise WorkflowFailure("Scoped AI request did not enter the expected approval state")
    assignment = request(
        "POST",
        f"/v1/permission-requests/{ai_permission['id']}/review-assignments",
        expected=201,
        headers=rightsholder_headers,
        json={
            "reviewer_user_id": client_session["user"]["id"],
            "reason": "Route licensed-grounding review to the artist's rights manager",
        },
    ).json()
    if assignment.get("reviewer", {}).get("userId") != client_session["user"]["id"]:
        raise WorkflowFailure("Permission assignment did not identify the named rights administrator")
    requester_assignment_view = request(
        "GET",
        f"/v1/organizations/{requester_org['id']}/permission-requests",
        headers=requester_machine_headers,
    ).json()["permissionRequests"]
    requester_ai_view = next(row for row in requester_assignment_view if row["id"] == ai_permission["id"])
    if "reviewer" in requester_ai_view["reviewAssignment"] or "reason" in requester_ai_view["reviewAssignment"]:
        raise WorkflowFailure("Requester view disclosed private authority routing details")
    request(
        "POST",
        f"/v1/permission-requests/{ai_permission['id']}/decide",
        expected=409,
        headers=rightsholder_machine_headers,
        json={"decision": "approved", "note": "Machine must not bypass a named human reviewer"},
    )
    request(
        "POST",
        f"/v1/permission-requests/{ai_permission['id']}/decide",
        expected=403,
        headers=rightsholder_headers,
        json={"decision": "approved", "note": "Unassigned owner must not bypass the reviewer"},
    )
    record(
        "named_permission_routing",
        assignmentId=assignment["id"],
        reviewerRole="rights_manager",
        requesterDetailsRedacted=True,
        machineBypassRejected=True,
        humanBypassRejected=True,
    )

    ai_credit_text = "Workflow Artist — licensed composition used for Clef Grounding Study"
    ai_backlink_url = "https://rights.workflow.test/works/workflow-work"
    ai_metadata = {
        "artist_credit": "Workflow Artist",
        "clef_license": "license:workflow-ai-grounding",
    }
    ai_decision = request(
        "POST",
        f"/v1/permission-requests/{ai_permission['id']}/decide",
        headers=client_headers,
        json={
            "decision": "approved",
            "note": "Approved for declared grounding scope, safeguards, exact credit, and reporting terms",
            "obligations": {
                "attribution": {
                    "required": True,
                    "credit_text": ai_credit_text,
                    "backlink_required": True,
                    "backlink_url": ai_backlink_url,
                    "placements": ["description", "metadata"],
                    "metadata_fields": ai_metadata,
                },
                "publication_reporting_required": True,
                "publication_evidence_due_days": 30,
                "usage_reporting_frequency": "once",
            },
        },
    ).json()
    ai_receipt = ai_decision.get("receipt")
    if not ai_receipt or ai_receipt["payload"]["permission"]["context"]["aiUse"] != ai_use:
        raise WorkflowFailure("AI receipt did not preserve the complete declared AI scope")
    signed_obligations = ai_receipt["payload"]["permission"].get("licenseObligations", {})
    if signed_obligations.get("attribution", {}).get("creditText") != ai_credit_text:
        raise WorkflowFailure("AI grant did not sign the exact credit obligation")
    if signed_obligations.get("publicationReporting", {}).get("evidenceDueDaysAfterPublication") != 30:
        raise WorkflowFailure("AI grant did not sign the publication evidence deadline")
    ai_receipt_id = ai_receipt["payload"]["receiptId"]
    ai_verification = request("POST", "/v1/receipts/verify", json={"receipt": ai_receipt}).json()
    if not ai_verification["valid"]:
        raise WorkflowFailure(f"AI permission receipt did not verify: {ai_verification}")
    record(
        "ai_scope_and_obligations_receipt",
        receiptId=ai_receipt_id,
        safeguards=len(ai_use["acceptedSafeguards"]),
        modelScope=ai_use["modelScope"],
        exactCreditSigned=True,
        backlinkSigned=True,
        publicationReportingSigned=True,
    )

    usage_report = request(
        "POST",
        f"/v1/permission-requests/{ai_permission['id']}/usage-reports",
        expected=201,
        headers=requester_machine_headers,
        json={
            "publication_url": "https://release.workflow.test/grounding-study",
            "published_at": publication_timestamp,
            "platform": "Workflow Release Service",
            "declared_credit_text": ai_credit_text,
            "declared_backlink_url": ai_backlink_url,
            "metadata": ai_metadata,
            "evidence": {"archiveDigest": "sha256:" + "a" * 64},
            "idempotency_key": "workflow-ai-publication",
        },
    ).json()
    checks = usage_report.get("automatedChecks", {})
    if checks.get("creditTextExactMatch") is not True or checks.get("backlinkExactMatch") is not True:
        raise WorkflowFailure("Publication evidence did not compare exact credit and backlink terms")
    if checks.get("reportedWithinDeadline") is not True:
        raise WorkflowFailure("Publication evidence was not recorded inside the signed reporting deadline")
    if not all(checks.get("metadataExactMatches", {}).values()):
        raise WorkflowFailure("Publication evidence did not compare every required metadata field")
    request(
        "POST",
        f"/v1/permission-usage-reports/{usage_report['id']}/reviews",
        expected=403,
        headers=rightsholder_headers,
        json={
            "outcome": "compliant",
            "note": "Unassigned owner must not review this routed case",
            "idempotency_key": "workflow-owner-compliance-review",
        },
    )
    compliance_review = request(
        "POST",
        f"/v1/permission-usage-reports/{usage_report['id']}/reviews",
        expected=201,
        headers=client_headers,
        json={
            "outcome": "compliant",
            "note": "Archived release evidence exactly matches the signed credit terms",
            "evidence": {"reviewRecord": "workflow:compliance-review:1"},
            "idempotency_key": "workflow-assigned-compliance-review",
        },
    ).json()
    current_ai_permission = request(
        "GET",
        f"/v1/permission-requests/{ai_permission['id']}",
        headers=requester_headers,
    ).json()
    if compliance_review.get("effectOnPermission") != "none" or current_ai_permission["status"] != "approved":
        raise WorkflowFailure("Compliance review improperly changed the signed grant")
    record(
        "publication_credit_compliance",
        usageReportId=usage_report["id"],
        reviewId=compliance_review["id"],
        exactCredit=True,
        exactBacklink=True,
        exactMetadata=True,
        permissionEffect="none",
    )

    from sqlalchemy import text  # noqa: PLC0415

    immutable_rows = {
        "rn_permission_review_assignments": assignment["id"],
        "rn_permission_usage_reports": usage_report["id"],
        "rn_permission_compliance_reviews": compliance_review["id"],
    }
    for table_name, row_id in immutable_rows.items():
        with SessionLocal() as db:
            try:
                db.execute(text(f"UPDATE {table_name} SET id = id WHERE id = :row_id"), {"row_id": row_id})
                db.commit()
            except Exception:
                db.rollback()
            else:
                raise WorkflowFailure(f"Database allowed mutation of append-only table {table_name}")
    record("permission_administration_immutability", tables=len(immutable_rows), databaseTriggersRejectedMutation=True)

    disputed = request(
        "POST",
        f"/v1/permission-requests/{ai_permission['id']}/lifecycle-events",
        headers=requester_headers,
        json={
            "event_type": "dispute",
            "reason": "Verifier dispute: delivered use requires scope review",
        },
    ).json()
    dispute_receipt = disputed.get("receipt")
    if disputed.get("status") != "disputed" or not dispute_receipt:
        raise WorkflowFailure("Requester dispute did not create a signed status record")
    if dispute_receipt["payload"]["event"]["priorReceiptId"] != ai_receipt_id:
        raise WorkflowFailure("Dispute receipt did not reference the prior permission receipt")
    if not request("POST", "/v1/receipts/verify", json={"receipt": dispute_receipt}).json()["valid"]:
        raise WorkflowFailure("Dispute status receipt did not verify")
    record("signed_dispute", receiptId=dispute_receipt["payload"]["receiptId"], priorReceiptId=ai_receipt_id)

    revoked = request(
        "POST",
        f"/v1/permission-requests/{ai_permission['id']}/lifecycle-events",
        headers=client_headers,
        json={
            "event_type": "revocation",
            "reason": "Verifier revocation: authority closes the disputed grant",
        },
    ).json()
    revocation_receipt = revoked.get("receipt")
    if revoked.get("status") != "revoked" or not revocation_receipt:
        raise WorkflowFailure("Authority revocation did not create a signed status record")
    if revocation_receipt["payload"]["event"]["priorReceiptId"] != dispute_receipt["payload"]["receiptId"]:
        raise WorkflowFailure("Revocation receipt did not reference the dispute receipt")
    if not request("POST", "/v1/receipts/verify", json={"receipt": revocation_receipt}).json()["valid"]:
        raise WorkflowFailure("Revocation status receipt did not verify")
    record("signed_revocation", receiptId=revocation_receipt["payload"]["receiptId"], priorReceiptId=dispute_receipt["payload"]["receiptId"])

    head = request("GET", "/v1/transparency/head").json()
    entries = request("GET", "/v1/transparency/entries").json()["entries"]
    if head["sequence"] != 5 or head["receiptId"] != revocation_receipt["payload"]["receiptId"] or len(entries) != 5:
        raise WorkflowFailure("Transparency head and entries do not match the issued receipt")
    if entries[0]["previousEntryHash"] is not None or any(entries[index]["previousEntryHash"] != entries[index - 1]["entryHash"] for index in range(1, 5)) or entries[-1]["entryHash"] != head["entryHash"]:
        raise WorkflowFailure("Transparency chain linkage is invalid")
    if [entry["receiptKind"] for entry in entries] != ["grant", "settlement_reconciliation", "grant", "dispute", "revocation"]:
        raise WorkflowFailure("Transparency chain did not preserve permission, settlement, and lifecycle record types")
    record("transparency_chain", sequence=5, entryHash=head["entryHash"], genesisLinked=True)

    requester_audit = request(
        "GET",
        f"/v1/organizations/{requester_org['id']}/audit-events",
        headers=requester_machine_headers,
    ).json()["events"]
    operator_audit = request("GET", "/v1/operator/audit-events", headers=operator_headers).json()["events"]
    request_events = [event for event in requester_audit if event["resource"].get("id") == permission["id"]]
    settlement_events = [event for event in requester_audit if event["details"].get("settlementId") == settlement["id"]]
    if {event["action"] for event in request_events} < {"permission_request.created", "permission_request.approved"}:
        raise WorkflowFailure("Organization audit did not preserve the machine permission transaction")
    if not any(event["actor"].get("credentialId") == rightsholder_credential["id"] for event in request_events):
        raise WorkflowFailure("Organization audit did not preserve the rightsholder machine actor")
    if not any(event["action"] == "authority_claim.verified" for event in operator_audit):
        raise WorkflowFailure("Node operator audit did not preserve authority verification")
    if not any(event["action"] == "settlement.reconciliation.recorded" and event["details"].get("assertionType") == "paid" for event in settlement_events):
        raise WorkflowFailure("Organization audit did not preserve the paid settlement reconciliation")
    record(
        "append_only_audit",
        requesterEvents=len(request_events),
        operatorEvents=len(operator_audit),
        settlementEvents=len(settlement_events),
        machineActorPreserved=True,
    )

    request(
        "DELETE",
        f"/v1/organizations/{requester_org['id']}/api-credentials/{requester_credential['id']}",
        expected=204,
        headers=requester_headers,
    )
    request(
        "DELETE",
        f"/v1/organizations/{rightsholder_org['id']}/api-credentials/{rightsholder_credential['id']}",
        expected=204,
        headers=rightsholder_headers,
    )
    request("GET", "/v1/directory/authority-claims", expected=401, headers=requester_machine_headers)
    record("machine_credential_revocation", credentialsRevoked=2, rejectedImmediately=True)

    for headers in (rightsholder_headers, operator_headers, requester_headers, client_headers):
        request("DELETE", "/auth/session", expected=204, headers=headers)
        request("GET", "/v1/session", expected=401, headers=headers)
    record("session_revocation", sessionsRevoked=4)

    return {
        "schemaVersion": "clef.rightsholder-workflow-verification.v1",
        "status": "passed",
        "stepCount": len(steps),
        "steps": steps,
        "receipt": {
            "id": receipt_id,
            "payloadHash": stored_receipt["proof"]["payloadHash"],
            "entryHash": head["entryHash"],
        },
        "aiReceipt": {"id": ai_receipt_id, "payloadHash": ai_receipt["proof"]["payloadHash"]},
        "lifecycleReceipts": {
            "dispute": dispute_receipt["payload"]["receiptId"],
            "revocation": revocation_receipt["payload"]["receiptId"],
        },
        "settlement": {
            "id": settlement["id"],
            "reconciliationId": reconciliation["id"],
            "receiptId": reconciliation["receiptId"],
            "ledgerDigest": reconciliation["ledgerDigest"],
            "assertionType": reconciliation["assertionType"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, help="Fresh SQLite path; defaults to a temporary database")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path")
    parser.add_argument("--prefix", default="e2e", help="Slug/work identifier prefix")
    parser.add_argument("--operator-email", default="operator@workflow.test")
    parser.add_argument("--rightsholder-email", default="rightsholder@workflow.test")
    parser.add_argument("--requester-email", default="requester@workflow.test")
    parser.add_argument("--client-email", default="client@workflow.test")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.database_path:
        database_path = args.database_path.expanduser().resolve()
        if database_path.exists():
            raise SystemExit(f"Refusing to overwrite existing database: {database_path}")
        database_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="clef-rightsholder-workflow-")
        database_path = Path(temporary.name) / "workflow.db"

    emails = {
        "operator": args.operator_email.strip().lower(),
        "rightsholder": args.rightsholder_email.strip().lower(),
        "requester": args.requester_email.strip().lower(),
        "client": args.client_email.strip().lower(),
    }
    try:
        result = run_workflow(database_path, args.prefix.strip().lower(), emails)
        rendered = json.dumps(result, indent=2, sort_keys=True)
        if args.output:
            args.output.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            args.output.expanduser().resolve().write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except Exception as error:
        failure = {
            "schemaVersion": "clef.rightsholder-workflow-verification.v1",
            "status": "failed",
            "error": str(error),
        }
        print(json.dumps(failure, indent=2, sort_keys=True))
        return 1
    finally:
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
