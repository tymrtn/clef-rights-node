from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import uuid
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from main import (  # noqa: E402
    AI_INPUT_KEYS,
    AI_LIMIT_KEYS,
    AI_MODEL_SCOPE_KEYS,
    AI_SAFEGUARD_KEYS,
    PROJECT_ENV_PATH,
    SessionLocal,
    engine,
    USAGE_KEYS,
    RESTRICTION_KEYS,
    app,
    ddex_adapter,
    default_ai_policy,
    mlc_adapter,
    receipt_signer,
    settings,
    webhook_secret_box,
)
from models import (  # noqa: E402
    ApiCredentialRecord,
    AuditEventRecord,
    Base,
    DdexAcknowledgementRecord,
    DdexExchangeRecord,
    MagicSession,
    PermissionComplianceReviewRecord,
    PermissionRequestRecord,
    PermissionReviewAssignmentRecord,
    PermissionUsageReportRecord,
    SettlementEntryRecord,
    SettlementRecord,
    UserRecord,
    WebhookEndpointRecord,
)
from services.webhook_outbox import process_due_webhooks  # noqa: E402
from services.webhooks import signed_webhook_body, verify_webhook_signature, webhook_signature  # noqa: E402
from services.settings import Settings  # noqa: E402


Base.metadata.create_all(engine)
client = TestClient(app)


def test_organization_onboarding_persists_conservative_ai_defaults():
    prefix = f"onboarding-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    response = client.post(
        "/v1/organizations",
        json={
            "slug": prefix,
            "name": "Onboarding Publisher",
            "organization_type": "publisher",
            "default_territory": "US",
            "controlled_right_types": ["composition", "lyrics"],
            "ai_policy_preset": "review_each_ai_use",
        },
        headers=headers,
    )
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["organizationType"] == "publisher"
    assert profile["controlledRightTypes"] == ["composition", "lyrics"]
    assert profile["policyDefaults"]["matrix"]["usage"]["ai_grounded_generation"] == "requires_approval"
    assert profile["policyDefaults"]["aiPolicy"]["inputs"]["stems"] == "requires_approval"
    assert profile["policyDefaults"]["aiPolicy"]["modelScopes"]["public_or_open_weights"] == "blocked"

    session_profile = client.get("/v1/session", headers=headers).json()["organizations"][0]["profile"]
    assert session_profile == profile


@pytest.mark.parametrize(
    ("organization_type", "expected_rights"),
    [
        ("label", ["master"]),
        ("publisher", ["composition", "lyrics"]),
        ("administrator", ["composition", "master"]),
        ("pro", ["composition", "performance"]),
        ("cmo", ["composition", "performance"]),
        ("requester", []),
    ],
)
def test_organization_type_supplies_conservative_rights_defaults_when_omitted(organization_type, expected_rights):
    prefix = f"typed-default-{organization_type}-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    response = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": f"Typed {organization_type}", "organization_type": organization_type},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["profile"]["controlledRightTypes"] == expected_rights


def test_requester_cannot_submit_contradictory_controlled_rights():
    prefix = f"requester-rights-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    response = client.post(
        "/v1/organizations",
        json={
            "slug": prefix,
            "name": "Contradictory Requester",
            "organization_type": "requester",
            "controlled_right_types": ["master"],
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Requester organizations cannot select controlled rights"


@pytest.mark.parametrize("organization_type", ["label", "publisher", "administrator", "pro", "cmo", "collective"])
def test_rights_administration_organizations_can_onboard_without_inventing_authority(organization_type):
    prefix = f"admin-{organization_type}-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    response = client.post(
        "/v1/organizations",
        json={
            "slug": prefix,
            "name": f"Test {organization_type}",
            "organization_type": organization_type,
            "default_territory": "US",
            "controlled_right_types": ["composition"],
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["profile"]["organizationType"] == organization_type
    assert response.json()["profile"]["policyDefaults"]["matrix"]["usage"]["ai_model_training"] == "requires_approval"
    assert client.get(f"/v1/organizations/{response.json()['id']}/authority-claims", headers=headers).json()["claims"] == []


def test_requester_onboarding_does_not_invent_catalog_authority():
    prefix = f"requester-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    response = client.post(
        "/v1/organizations",
        json={
            "slug": prefix,
            "name": "AI Production Studio",
            "organization_type": "requester",
            "default_territory": "US",
            "controlled_right_types": [],
        },
        headers=headers,
    )
    assert response.status_code == 200
    organization = response.json()
    assert organization["profile"]["controlledRightTypes"] == []

    publish = client.put(
        f"/v1/organizations/{organization['id']}/rights/requester:invented-work",
        json={"artist_name": "No Authority", "contract": {}, "expected_version": 0},
        headers=headers,
    )
    assert publish.status_code == 403
    assert publish.json()["detail"] == "Requester organizations cannot publish rights policies"


def test_onboarding_status_is_role_scoped_and_never_promotes_setup_to_authority():
    prefix = f"status-{uuid.uuid4().hex[:8]}"
    owner_headers = _session_headers(f"owner-{prefix}@example.com")
    organization = client.post(
        "/v1/organizations",
        json={
            "slug": prefix,
            "name": "Onboarding Status Label",
            "organization_type": "label",
            "controlled_right_types": ["master"],
        },
        headers=owner_headers,
    ).json()
    response = client.get(
        f"/v1/organizations/{organization['id']}/onboarding-status",
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    milestones = {row["key"]: row for row in body["milestones"]}
    assert body["complete"] is False
    assert milestones["catalog"]["status"] == "pending"
    assert milestones["policy"]["status"] == "pending"
    assert milestones["authority"]["status"] == "pending"
    assert milestones["reviewer"]["status"] == "complete"
    assert client.get(
        f"/v1/organizations/{organization['id']}/authority-claims",
        headers=owner_headers,
    ).json()["claims"] == []

    member_email = f"member-{prefix}@example.com"
    assert client.post(
        f"/v1/organizations/{organization['id']}/members",
        json={"email": member_email, "role": "member"},
        headers=owner_headers,
    ).status_code == 200
    forbidden = client.get(
        f"/v1/organizations/{organization['id']}/onboarding-status",
        headers=_session_headers(member_email),
    )
    assert forbidden.status_code == 403


def test_requester_onboarding_status_marks_rightsholder_steps_not_applicable():
    prefix = f"requester-status-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    organization = client.post(
        "/v1/organizations",
        json={
            "slug": prefix,
            "name": "Permission Requester",
            "organization_type": "requester",
            "controlled_right_types": [],
        },
        headers=headers,
    ).json()
    response = client.get(
        f"/v1/organizations/{organization['id']}/onboarding-status",
        headers=headers,
    )
    assert response.status_code == 200
    milestones = {row["key"]: row for row in response.json()["milestones"]}
    assert milestones["catalog"]["status"] == "not_applicable"
    assert milestones["policy"]["status"] == "not_applicable"
    assert milestones["authority"]["status"] == "not_applicable"
    assert milestones["requester"]["status"] == "pending"


def test_label_owner_can_add_client_team_members_without_granting_node_admin():
    prefix = f"team-{uuid.uuid4().hex[:8]}"
    owner_headers = _session_headers(f"owner-{prefix}@example.com")
    organization = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "Client Services Label", "organization_type": "label", "controlled_right_types": ["master"]},
        headers=owner_headers,
    ).json()
    member_email = f"artist-{prefix}@example.com"
    added = client.post(
        f"/v1/organizations/{organization['id']}/members",
        json={"email": member_email, "role": "rights_manager"},
        headers=owner_headers,
    )
    assert added.status_code == 200
    assert added.json()["role"] == "rights_manager"

    member_headers = _session_headers(member_email)
    member_session = client.get("/v1/session", headers=member_headers).json()
    assert member_session["user"]["nodeRole"] != "admin"
    assert member_session["organizations"][0]["role"] == "rights_manager"

    forbidden = client.post(
        f"/v1/organizations/{organization['id']}/members",
        json={"email": f"other-{prefix}@example.com", "role": "member"},
        headers=member_headers,
    )
    assert forbidden.status_code == 403

    listed = client.get(f"/v1/organizations/{organization['id']}/members", headers=owner_headers)
    assert listed.status_code == 200
    assert {(row["email"], row["role"]) for row in listed.json()["members"]} == {
        (f"owner-{prefix}@example.com", "owner"),
        (member_email, "rights_manager"),
    }


def test_label_catalog_import_is_previewed_versioned_and_not_authority():
    prefix = f"catalog-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    organization = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "Northstar Records", "organization_type": "label", "controlled_right_types": ["composition", "master"]},
        headers=headers,
    ).json()
    org_id = organization["id"]
    managed_client = client.post(
        f"/v1/organizations/{org_id}/catalog/clients",
        json={"name": "Mara Vale", "external_reference": "ARTIST-001", "contact_email": "mara@example.com"},
        headers=headers,
    )
    assert managed_client.status_code == 201, managed_client.text
    assert managed_client.json()["externalReference"] == "artist-001"

    csv_body = (
        "item_type,title,artist,iswc,isrc,mlc_song_code,territory,client_reference,source_reference\n"
        "work,Northern Lights,Mara Vale,T-123.456.789-0,,,worldwide,ARTIST-001,agreement-2026-001\n"
        "recording,Northern Lights,Mara Vale,,USABC2600001,,US,ARTIST-001,catalog-2026-001\n"
    )
    preview = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/csv",
        files={"file": ("northstar.csv", csv_body, "text/csv")},
        headers=headers,
    )
    assert preview.status_code == 201, preview.text
    batch = preview.json()
    assert batch["status"] == "preview"
    assert batch["summary"] == {
        "total": 2,
        "counts": {"ready": 2},
        "unresolved": 0,
        "importable": 2,
        "skipped": 0,
    }
    assert {row["normalized"]["work_key"] for row in batch["rows"]} == {
        "iswc:T1234567890",
        "isrc:USABC2600001",
    }

    unconfirmed = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/{batch['id']}/commit",
        json={"confirm_import": False, "expected_preview_digest": batch["previewDigest"]},
        headers=headers,
    )
    assert unconfirmed.status_code == 422
    committed = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/{batch['id']}/commit",
        json={"confirm_import": True, "expected_preview_digest": batch["previewDigest"]},
        headers=headers,
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["status"] == "committed"
    assert committed.json()["summary"]["counts"] == {"imported": 2}

    assets = client.get(f"/v1/organizations/{org_id}/catalog/assets", headers=headers).json()["assets"]
    assert len(assets) == 2
    assert all(asset["version"] == 1 for asset in assets)
    assert all(asset["authorityStatus"] == "unverified" for asset in assets)
    assert all(asset["client"]["externalReference"] == "artist-001" for asset in assets)

    replay = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/csv",
        files={"file": ("renamed.csv", csv_body, "text/csv")},
        headers=headers,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == batch["id"]
    assert replay.json()["status"] == "committed"

    corrected_csv = (
        "item_type,title,artist,iswc,isrc,mlc_song_code,territory,client_reference,source_reference\n"
        "work,Northern Lights (Corrected),Mara Vale,T1234567890,,,worldwide,artist-001,agreement-2026-002\n"
    )
    conflict_preview = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/csv",
        files={"file": ("northstar-correction.csv", corrected_csv, "text/csv")},
        headers=headers,
    )
    assert conflict_preview.status_code == 201, conflict_preview.text
    conflict_batch = conflict_preview.json()
    conflict_row = conflict_batch["rows"][0]
    assert conflict_row["status"] == "conflict"
    assert conflict_row["existingAsset"]["version"] == 1

    blocked_commit = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/{conflict_batch['id']}/commit",
        json={"confirm_import": True, "expected_preview_digest": conflict_batch["previewDigest"]},
        headers=headers,
    )
    assert blocked_commit.status_code == 409
    resolved = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/{conflict_batch['id']}/rows/{conflict_row['id']}/resolution",
        json={"expected_preview_digest": conflict_batch["previewDigest"], "resolution": "new_version", "note": "Corrected title against the executed catalog addendum"},
        headers=headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved_version"
    second_commit = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/{conflict_batch['id']}/commit",
        json={"confirm_import": True, "expected_preview_digest": resolved.json()["previewDigest"]},
        headers=headers,
    )
    assert second_commit.status_code == 200, second_commit.text

    history = client.get(
        f"/v1/organizations/{org_id}/catalog/assets?include_history=true",
        headers=headers,
    ).json()["assets"]
    work_history = [asset for asset in history if asset["workKey"] == "iswc:T1234567890"]
    assert [asset["version"] for asset in work_history] == [2, 1]
    assert work_history[0]["title"] == "Northern Lights (Corrected)"
    assert work_history[1]["title"] == "Northern Lights"


def test_catalog_import_rejects_title_identifiers_and_unknown_clients():
    prefix = f"catalog-invalid-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    org_id = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "Careful Label", "organization_type": "label"},
        headers=headers,
    ).json()["id"]
    csv_body = (
        "item_type,title,artist,iswc,isrc,mlc_song_code,territory,client_reference,source_reference\n"
        "work,Untethered Title,Unknown Artist,,,,worldwide,missing-client,\n"
    )
    preview = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/csv",
        files={"file": ("invalid.csv", csv_body, "text/csv")},
        headers=headers,
    )
    assert preview.status_code == 201
    row = preview.json()["rows"][0]
    assert row["status"] == "invalid"
    assert "titles are not durable identifiers" in " ".join(row["errors"])
    assert "does not match a managed client" in " ".join(row["errors"])
    commit = client.post(
        f"/v1/organizations/{org_id}/catalog/imports/{preview.json()['id']}/commit",
        json={"confirm_import": True, "expected_preview_digest": preview.json()["previewDigest"]},
        headers=headers,
    )
    assert commit.status_code == 409


def test_dotenv_loading_is_scoped_to_the_repository_root():
    assert PROJECT_ENV_PATH == Path(__file__).resolve().parents[2] / ".env"


def _session_headers(email: str, *, role: str = "artist") -> dict[str, str]:
    db = SessionLocal()
    try:
        user = db.query(UserRecord).filter(UserRecord.email == email).first()
        if not user:
            user = UserRecord(email=email, display_name=email.split("@")[0], role=role)
            db.add(user)
            db.flush()
        else:
            user.role = role
        session_id = f"test-{uuid.uuid4()}"
        db.add(
            MagicSession(
                id=session_id,
                email=email,
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=1),
            )
        )
        db.commit()
        return {"X-Session-Id": session_id}
    finally:
        db.close()


def _create_api_credential(
    org_id: str,
    owner_headers: dict[str, str],
    *,
    scopes: list[str],
    name: str = "Catalog automation",
) -> dict:
    response = client.post(
        f"/v1/organizations/{org_id}/api-credentials",
        json={"name": name, "scopes": scopes, "expires_in_days": 30},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_reports_mock_integrations():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["mock_mode"] is True
    assert set(data["integrations"].keys()) == {"mlc", "musicbrainz", "openrouter"}


def test_rights_summary_default_template():
    headers = {"X-Artist-Name": "Test Artist"}
    res = client.get(
        "/rights/summary",
        params={"key": "demo-key", "intended_usage": "streaming_visual"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["key"] == "demo-key"
    assert data["artist"] == "Test Artist"
    assert data["headlineStatus"] in {"allowed", "requires_approval", "blocked"}
    assert data["matrix"]["usage"]["streaming_visual"] == data["headlineStatus"]


def test_rights_save_and_history_roundtrip():
    headers = {"X-Artist-Name": "Tester"}
    contract = {
        "artist": {
            "usageMatrix": {"streaming_visual": "allowed"},
            "restrictionMatrix": {},
            "approval": {"approvalWindowDays": 14},
        },
        "matrix": {
            "usage": {"streaming_visual": "allowed"},
            "restrictions": {},
        },
    }
    res = client.post(
        "/rights/save",
        json={"key": "demo-save", "artist": "Tester", "contract": contract, "expected_version": 0},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["version"] == 1

    res2 = client.get("/rights/by-key", params={"key": "demo-save"}, headers=headers)
    assert res2.status_code == 200
    body = res2.json()
    assert body["version"] == 1
    assert body["isNew"] is False

    history = client.get("/rights/history", params={"key": "demo-save"}, headers=headers)
    assert history.status_code == 200
    hist_items = history.json()
    assert len(hist_items) >= 1
    assert hist_items[0]["version"] == 1


def test_verified_authority_permission_receipt_roundtrip():
    initial_sequence = client.get("/v1/transparency/head").json()["sequence"]
    rightsholder_headers = _session_headers("rights@example.com")
    requester_headers = _session_headers("requester@example.com")
    operator_headers = _session_headers("operator@example.com", role="admin")

    rightsholder_org = client.post(
        "/v1/organizations",
        json={"slug": "rightsholder", "name": "Rightsholder Records"},
        headers=rightsholder_headers,
    )
    assert rightsholder_org.status_code == 200
    rightsholder_org_id = rightsholder_org.json()["id"]

    requester_org = client.post(
        "/v1/organizations",
        json={"slug": "requester", "name": "Cover Factory"},
        headers=requester_headers,
    )
    assert requester_org.status_code == 200
    requester_org_id = requester_org.json()["id"]

    usage = {key: "blocked" for key in USAGE_KEYS}
    usage["derivative_remix"] = "requires_approval"
    restrictions = {key: "allowed" for key in RESTRICTION_KEYS}
    policy = client.put(
        f"/v1/organizations/{rightsholder_org_id}/rights/MLC-WORK-123",
        json={
            "artist_name": "Example Artist",
            "contract": {
                "policyVersion": "clef.rights-policy.v1",
                "matrix": {"usage": usage, "restrictions": restrictions},
            },
        },
        headers=rightsholder_headers,
    )
    assert policy.status_code == 200
    contract_id = policy.json()["id"]

    claim = client.post(
        "/v1/authority-claims",
        json={
            "org_id": rightsholder_org_id,
            "rights_contract_id": contract_id,
            "right_type": "composition",
            "territory": "US",
            "evidence": {"source": "mlc", "mlcSongCode": "MLC-WORK-123", "share": "100.0000"},
        },
        headers=rightsholder_headers,
    )
    assert claim.status_code == 200
    claim_id = claim.json()["id"]
    assert claim.json()["status"] == "self_asserted"

    unverified_request = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org_id,
            "authority_claim_id": claim_id,
            "intended_usage": "derivative_remix",
        },
        headers=requester_headers,
    )
    assert unverified_request.status_code == 409

    verified = client.post(
        f"/v1/authority-claims/{claim_id}/verify",
        json={"evidence_note": "Matched member catalog and authority evidence"},
        headers=operator_headers,
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"

    missing_term = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org_id,
            "authority_claim_id": claim_id,
            "intended_usage": "derivative_remix",
            "territory": "US",
        },
        headers=requester_headers,
    )
    assert missing_term.status_code == 422
    assert missing_term.json()["detail"] == "License start and end dates are required"

    permission = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org_id,
            "authority_claim_id": claim_id,
            "intended_usage": "derivative_remix",
            "territory": "US",
            "term_start": "2026-08-01",
            "term_end": "2027-07-31",
            "context": {"releaseTitle": "Example Remix", "commercial": True},
            "provenance": {"sourceAssetSha256": "a" * 64},
        },
        headers=requester_headers,
    )
    assert permission.status_code == 200
    assert permission.json()["status"] == "pending"

    decision = client.post(
        f"/v1/permission-requests/{permission.json()['id']}/decide",
        json={"decision": "approved", "note": "Approved for the declared term and territory"},
        headers=rightsholder_headers,
    )
    assert decision.status_code == 200
    receipt = decision.json()["receipt"]
    assert receipt["payload"]["status"] == "permissioned"
    assert receipt["payload"]["authority"]["verificationStatus"] == "verified"
    assert receipt["transparency"]["sequence"] == initial_sequence + 1
    first_entry_hash = receipt["transparency"]["entryHash"]

    verification = client.post("/v1/receipts/verify", json={"receipt": receipt})
    assert verification.status_code == 200
    assert verification.json() == {
        "valid": True,
        "payloadHashValid": True,
        "signatureValid": True,
        "transparencyHashValid": True,
        "signer": "this_node",
        "error": None,
    }
    receipt["payload"]["permission"]["territory"] = "worldwide"
    tampered = client.post("/v1/receipts/verify", json={"receipt": receipt})
    assert tampered.status_code == 200
    assert tampered.json()["valid"] is False

    usage["derivative_remix"] = "allowed"
    updated_policy = client.put(
        f"/v1/organizations/{rightsholder_org_id}/rights/MLC-WORK-123",
        json={
            "artist_name": "Example Artist",
            "contract": {
                "policyVersion": "clef.rights-policy.v1",
                "matrix": {"usage": usage, "restrictions": restrictions},
            },
            "expected_version": 1,
        },
        headers=rightsholder_headers,
    )
    assert updated_policy.status_code == 200
    assert updated_policy.json()["version"] == 2

    auto_permission = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org_id,
            "authority_claim_id": claim_id,
            "intended_usage": "derivative_remix",
            "territory": "US",
            "term_start": "2026-08-01",
            "term_end": "2027-07-31",
        },
        headers=requester_headers,
    )
    assert auto_permission.status_code == 200
    assert auto_permission.json()["status"] == "approved"
    second_receipt = auto_permission.json()["receipt"]
    assert second_receipt["transparency"]["sequence"] == initial_sequence + 2
    assert second_receipt["transparency"]["previousEntryHash"] == first_entry_hash

    head = client.get("/v1/transparency/head")
    assert head.status_code == 200
    assert head.json()["sequence"] == initial_sequence + 2

    entries = client.get("/v1/transparency/entries", params={"from_sequence": initial_sequence + 1})
    assert entries.status_code == 200
    assert [entry["sequence"] for entry in entries.json()["entries"]] == [initial_sequence + 1, initial_sequence + 2]
    assert entries.json()["entries"][1]["previousEntryHash"] == entries.json()["entries"][0]["entryHash"]


def test_ai_grounding_scope_limits_and_assets_are_enforced_and_receipted():
    prefix = uuid.uuid4().hex[:8]
    rightsholder_headers = _session_headers(f"ai-owner-{prefix}@example.com")
    requester_headers = _session_headers(f"ai-requester-{prefix}@example.com")
    operator_headers = _session_headers("operator@example.com", role="admin")
    rightsholder_org = client.post(
        "/v1/organizations",
        json={"slug": f"ai-owner-{prefix}", "name": "AI Rights Owner", "controlled_right_types": ["master"]},
        headers=rightsholder_headers,
    ).json()
    requester_org = client.post(
        "/v1/organizations",
        json={"slug": f"ai-requester-{prefix}", "name": "Licensed Model Lab"},
        headers=requester_headers,
    ).json()

    usage = {key: "blocked" for key in USAGE_KEYS}
    usage["ai_grounded_generation"] = "allowed"
    restrictions = {key: "conditional" for key in RESTRICTION_KEYS}
    ai_policy = default_ai_policy("blocked")
    ai_policy["inputs"]["stems"] = "allowed"
    ai_policy["inputs"]["lyrics"] = "requires_approval"
    ai_policy["modelScopes"]["private_single_tenant"] = "allowed"
    ai_policy["limits"] = {
        "maxSourceDurationSeconds": 30,
        "maxOutputDurationSeconds": 60,
        "maxLyricCharacters": 500,
        "sourceRetentionDays": 7,
        "embeddingRetentionDays": 30,
    }
    policy = client.put(
        f"/v1/organizations/{rightsholder_org['id']}/rights/isrc:AI{prefix}",
        json={
            "artist_name": "Grounded Artist",
            "contract": {
                "policyVersion": "clef.rights-policy.v2",
                "matrix": {"usage": usage, "restrictions": restrictions},
                "aiPolicy": ai_policy,
            },
        },
        headers=rightsholder_headers,
    )
    assert policy.status_code == 200
    stored_ai_policy = policy.json()["contract"]["aiPolicy"]
    assert set(stored_ai_policy["inputs"]) == set(AI_INPUT_KEYS)
    assert set(stored_ai_policy["modelScopes"]) == set(AI_MODEL_SCOPE_KEYS)
    assert set(stored_ai_policy["limits"]) == set(AI_LIMIT_KEYS)
    assert set(stored_ai_policy["safeguards"]) == set(AI_SAFEGUARD_KEYS)

    claim = client.post(
        "/v1/authority-claims",
        json={
            "org_id": rightsholder_org["id"],
            "rights_contract_id": policy.json()["id"],
            "right_type": "master",
            "territory": "US",
            "evidence": {"source": "contract", "reference": f"master-{prefix}", "share": "100.0000"},
        },
        headers=rightsholder_headers,
    ).json()
    verified = client.post(
        f"/v1/authority-claims/{claim['id']}/verify",
        json={"evidence_note": "Master agreement reviewed"},
        headers=operator_headers,
    )
    assert verified.status_code == 200

    ai_use = {
        "inputAssets": ["stems"],
        "modelScope": "private_single_tenant",
        "acceptedSafeguards": list(AI_SAFEGUARD_KEYS),
        "sourceDurationSeconds": 20,
        "outputDurationSeconds": 45,
        "lyricCharacters": 0,
        "sourceRetentionDays": 7,
        "embeddingRetentionDays": 14,
    }
    safeguards_missing = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org["id"],
            "authority_claim_id": claim["id"],
            "intended_usage": "ai_grounded_generation",
            "territory": "US",
            "term_start": "2026-08-01",
            "term_end": "2027-07-31",
            "context": {"aiUse": {**ai_use, "acceptedSafeguards": []}},
        },
        headers=requester_headers,
    )
    assert safeguards_missing.status_code == 409
    assert any("safeguard:provenanceReceipt:not_accepted" in reason for reason in safeguards_missing.json()["detail"]["policyEvaluation"])

    permission = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org["id"],
            "authority_claim_id": claim["id"],
            "intended_usage": "ai_grounded_generation",
            "territory": "US",
            "term_start": "2026-08-01",
            "term_end": "2027-07-31",
            "context": {"releaseTitle": "Grounded Session", "restrictionCategories": [], "aiUse": ai_use},
        },
        headers=requester_headers,
    )
    assert permission.status_code == 200
    assert permission.json()["status"] == "pending"
    assert permission.json()["policyState"] == "requires_approval"
    permission_ledger = client.get(
        f"/v1/permission-requests/{permission.json()['id']}",
        headers=rightsholder_headers,
    )
    assert permission_ledger.status_code == 200
    assert permission_ledger.json()["decisionRequirements"] == {"exactAttributionRequired": True}
    missing_exact_attribution = client.post(
        f"/v1/permission-requests/{permission.json()['id']}/decide",
        json={"decision": "approved", "note": "Attribution accepted without exact terms"},
        headers=rightsholder_headers,
    )
    assert missing_exact_attribution.status_code == 422
    assert "exact attribution terms" in missing_exact_attribution.json()["detail"]
    approved = client.post(
        f"/v1/permission-requests/{permission.json()['id']}/decide",
        json={
            "decision": "approved",
            "note": "Approved with exact creator credit and publication reporting",
            "obligations": {
                "attribution": {
                    "required": True,
                    "credit_text": "Grounded Artist — licensed master source",
                    "backlink_required": True,
                    "backlink_url": "https://artist.example/grounded-artist",
                    "placements": ["description", "metadata"],
                    "metadata_fields": {"artist": "Grounded Artist"},
                },
                "publication_reporting_required": True,
                "publication_evidence_due_days": 14,
                "usage_reporting_frequency": "once",
            },
        },
        headers=rightsholder_headers,
    )
    assert approved.status_code == 200, approved.text
    receipt = approved.json()["receipt"]
    assert receipt["payload"]["permission"]["context"]["aiUse"] == ai_use
    assert receipt["payload"]["permission"]["context"]["policyEvaluation"]["state"] == "requires_approval"
    assert receipt["payload"]["permission"]["licenseObligations"]["attribution"] == {
        "required": True,
        "creditText": "Grounded Artist — licensed master source",
        "backlinkRequired": True,
        "backlinkUrl": "https://artist.example/grounded-artist",
        "placements": ["description", "metadata"],
        "metadataFields": {"artist": "Grounded Artist"},
    }
    assert receipt["payload"]["policy"]["snapshot"]["aiPolicy"]["limits"]["maxSourceDurationSeconds"] == 30

    excessive = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org["id"],
            "authority_claim_id": claim["id"],
            "intended_usage": "ai_grounded_generation",
            "territory": "US",
            "term_start": "2026-08-01",
            "term_end": "2027-07-31",
            "context": {"aiUse": {**ai_use, "sourceDurationSeconds": 31}},
        },
        headers=requester_headers,
    )
    assert excessive.status_code == 409
    assert any("exceeds_30" in reason for reason in excessive.json()["detail"]["policyEvaluation"])


def test_stale_policy_save_is_rejected_without_lost_update():
    headers = {"X-Artist-Name": "Concurrency Artist"}
    contract = {
        "matrix": {
            "usage": {"derivative_remix": "requires_approval"},
            "restrictions": {},
        }
    }
    created = client.post(
        "/rights/save",
        json={"key": "concurrency-work", "artist": "Concurrency Artist", "contract": contract, "expected_version": 0},
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["version"] == 1

    first_update = client.post(
        "/rights/save",
        json={"key": "concurrency-work", "artist": "Concurrency Artist", "contract": contract, "expected_version": 1},
        headers=headers,
    )
    assert first_update.status_code == 200
    assert first_update.json()["version"] == 2

    stale_update = client.post(
        "/rights/save",
        json={"key": "concurrency-work", "artist": "Concurrency Artist", "contract": contract, "expected_version": 1},
        headers=headers,
    )
    assert stale_update.status_code == 409
    assert stale_update.json()["detail"]["currentVersion"] == 2

    omitted_version = client.post(
        "/rights/save",
        json={"key": "concurrency-work", "artist": "Concurrency Artist", "contract": contract},
        headers=headers,
    )
    assert omitted_version.status_code == 422


@pytest.mark.parametrize("key", ["candidate:collision", "unresolved:temporary"])
def test_legacy_rights_writes_reject_provisional_catalog_keys(key):
    headers = {"X-Artist-Name": "Identity Guard Artist"}
    contract = {"matrix": {"usage": {}, "restrictions": {}}}
    save = client.post(
        "/rights/save",
        json={"key": key, "artist": "Identity Guard Artist", "contract": contract, "expected_version": 0},
        headers=headers,
    )
    assert save.status_code == 422

    bulk = client.post(
        "/rights/bulk-update",
        json={"keys": [key], "changes": {"usage.streaming_visual": "blocked"}},
        headers=headers,
    )
    assert bulk.status_code == 422


def test_legacy_identity_headers_reject_malformed_email_values():
    payload = {
        "key": "identity-check",
        "artist": "Identity Guard Artist",
        "contract": {"matrix": {"usage": {}, "restrictions": {}}},
        "expected_version": 0,
    }
    bad_owner = client.post(
        "/rights/save",
        json=payload,
        headers={"X-Owner-Email": "@"},
    )
    assert bad_owner.status_code == 400

    bad_user = client.post(
        "/rights/save",
        json=payload,
        headers={"X-Owner-Email": "rights@example.com", "X-User-Email": "a@"},
    )
    assert bad_user.status_code == 400


def test_external_adapters_fail_closed_without_explicit_capability_authority():
    response = client.get("/v1/integrations/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert {item["name"] for item in data["mlc"]} == {
        "catalog_lookup",
        "ownership_evidence_read",
        "work_registration_write",
        "claim_submission_write",
        "permission_request_exchange",
        "usage_reporting_write",
        "royalty_statement_read",
    }
    assert all(item["authorized"] is False for item in data["mlc"])
    assert all(item["authorized"] is False for item in data["ddex"])


def test_legacy_owner_header_routes_are_unavailable_outside_demo_mode():
    original = settings.DEMO_MODE
    settings.DEMO_MODE = False
    try:
        response = client.get("/rights/list", headers={"X-Owner-Email": "victim@example.com"})
        assert response.status_code == 410
        assert "legacy Rights Console route" in response.json()["detail"]
    finally:
        settings.DEMO_MODE = original


def test_webhook_signatures_are_tamper_evident_and_time_bounded():
    body = signed_webhook_body(
        delivery_id="delivery-1",
        event="permission.decided",
        payload={"permissionId": "permission-1", "decision": "approved"},
        occurred_at="2026-07-10T12:00:00Z",
    )
    signature = webhook_signature(secret="fixture-test-webhook-secret", timestamp=1000, body=body)
    assert verify_webhook_signature(
        secret="fixture-test-webhook-secret",
        timestamp=1000,
        body=body,
        signature=signature,
        now=1000,
    )
    assert not verify_webhook_signature(
        secret="fixture-test-webhook-secret",
        timestamp=1000,
        body=body + b" ",
        signature=signature,
        now=1000,
    )
    assert not verify_webhook_signature(
        secret="fixture-test-webhook-secret",
        timestamp=1000,
        body=body,
        signature=signature,
        now=2000,
    )


def test_v1_webhooks_encrypt_secrets_queue_atomically_and_record_attempts():
    prefix = f"webhook-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    org_id = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "Webhook Label", "organization_type": "label"},
        headers=headers,
    ).json()["id"]
    created = client.post(
        f"/v1/organizations/{org_id}/webhooks",
        json={"url": "https://hooks.example.com/clef", "events": ["rights_policy.published"]},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    endpoint = created.json()
    secret = endpoint["signingSecret"]
    assert secret.startswith("whsec_")
    assert endpoint["secretHint"] == secret[-4:]

    db = SessionLocal()
    try:
        stored = db.query(WebhookEndpointRecord).filter(WebhookEndpointRecord.id == endpoint["id"]).one()
        assert stored.secret_ciphertext != secret
        assert secret not in stored.secret_ciphertext
    finally:
        db.close()
    listed = client.get(f"/v1/organizations/{org_id}/webhooks", headers=headers)
    assert listed.status_code == 200
    assert "signingSecret" not in listed.json()["endpoints"][0]

    usage = {key: "blocked" for key in USAGE_KEYS}
    restrictions = {key: "allowed" for key in RESTRICTION_KEYS}
    published = client.put(
        f"/v1/organizations/{org_id}/rights/mlc:{prefix}",
        json={
            "artist_name": "Webhook Artist",
            "expected_version": 0,
            "contract": {"policyVersion": "clef.rights-policy.v2", "matrix": {"usage": usage, "restrictions": restrictions}, "aiPolicy": default_ai_policy("review_each_ai_use")},
        },
        headers=headers,
    )
    assert published.status_code == 200, published.text
    pending = client.get(f"/v1/organizations/{org_id}/webhook-deliveries", headers=headers).json()["deliveries"]
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert pending[0]["event"] == "rights_policy.published"

    captured = {}

    class Delivered:
        status_code = 204

    def transport(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Delivered()

    db = SessionLocal()
    try:
        result = process_due_webhooks(
            db,
            secret_box=webhook_secret_box,
            allow_private_targets=False,
            max_attempts=6,
            request_timeout_seconds=10,
            transport=transport,
            target_validator=lambda _url: None,
        )
    finally:
        db.close()
    assert result == {"selected": 1, "delivered": 1, "retry": 0, "deadLetter": 0}
    assert captured["url"] == "https://hooks.example.com/clef"
    timestamp = int(captured["headers"]["X-Clef-Timestamp"])
    assert verify_webhook_signature(
        secret=secret,
        timestamp=timestamp,
        body=captured["data"],
        signature=captured["headers"]["X-Clef-Signature"],
        now=timestamp,
    )
    delivered = client.get(f"/v1/organizations/{org_id}/webhook-deliveries", headers=headers).json()["deliveries"][0]
    assert delivered["status"] == "succeeded"
    assert delivered["attemptCount"] == 1
    assert delivered["attempts"][0]["outcome"] == "succeeded"


def test_v1_webhooks_retry_transient_failures_and_dead_letter_permanent_targets():
    prefix = f"webhook-failure-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    org_id = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "Webhook Failure Label", "organization_type": "label"},
        headers=headers,
    ).json()["id"]
    endpoint = client.post(
        f"/v1/organizations/{org_id}/webhooks",
        json={"url": "https://hooks.example.com/clef", "events": ["*"]},
        headers=headers,
    ).json()
    queued = client.post(f"/v1/organizations/{org_id}/webhooks/{endpoint['id']}/test", headers=headers)
    assert queued.status_code == 201

    class Unavailable:
        status_code = 503

    db = SessionLocal()
    try:
        result = process_due_webhooks(
            db,
            secret_box=webhook_secret_box,
            allow_private_targets=False,
            max_attempts=6,
            request_timeout_seconds=10,
            transport=lambda *_args, **_kwargs: Unavailable(),
            target_validator=lambda _url: None,
        )
    finally:
        db.close()
    assert result["retry"] == 1
    retrying = client.get(f"/v1/organizations/{org_id}/webhook-deliveries", headers=headers).json()["deliveries"][0]
    assert retrying["status"] == "retry"
    assert retrying["lastStatusCode"] == 503

    private_target = client.post(
        f"/v1/organizations/{org_id}/webhooks",
        json={"url": "http://localhost:9999/hook", "events": ["webhook.test"]},
        headers=headers,
    )
    assert private_target.status_code == 422


def test_v1_mlc_lookup_never_falls_back_to_demo_data():
    headers = _session_headers("catalog-user@example.com")
    response = client.post(
        "/v1/catalog/mlc/search/works",
        json={"title": "Example Work"},
        headers=headers,
    )
    assert response.status_code == 503
    assert "capability is unavailable" in response.json()["detail"]


def test_organization_mlc_lookup_supports_scoped_machine_access_and_audit(monkeypatch):
    prefix = f"mlc-machine-{uuid.uuid4().hex[:8]}"
    owner_headers = _session_headers(f"{prefix}@example.com")
    organization = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "Registry Lookup Label"},
        headers=owner_headers,
    ).json()

    class ObservedMLC:
        calls = []

        def search_songcode(self, *, title, writer_lastname):
            self.calls.append((title, writer_lastname))
            return [
                {
                    "mlcSongCode": "MLC-OBSERVED-1",
                    "workTitle": "Observed Work",
                }
            ]

    observed = ObservedMLC()
    monkeypatch.setattr(mlc_adapter, "require", lambda capability: observed)
    credential = _create_api_credential(
        organization["id"],
        owner_headers,
        scopes=["registry:read"],
        name="MLC catalog reader",
    )
    bearer = {"Authorization": f"Bearer {credential['token']}"}
    response = client.post(
        f"/v1/organizations/{organization['id']}/catalog/mlc/search/works",
        json={"title": "  Observed   Work  ", "writer_lastname": None},
        headers=bearer,
    )
    assert response.status_code == 200, response.text
    assert response.json()["assertionType"] == "observed"
    assert response.json()["permissionStatus"] == "unknown"
    assert response.json()["results"][0]["mlcSongCode"] == "MLC-OBSERVED-1"
    scope = response.json()["sourceScope"]
    assert scope["providerName"] == "The MLC"
    assert scope["publishingAdministrationTerritory"] == "US"
    assert scope["recordingMetadataSource"] == "digital_service_providers"
    assert scope["masterOwnershipEvidenceProvided"] is False
    assert scope["masterRightsSharesProvided"] is False
    assert scope["permissionAuthoritySource"] == "separately_reviewed_rightsholder_evidence"
    assert observed.calls == [("Observed Work", None)]

    audit = client.get(
        f"/v1/organizations/{organization['id']}/audit-events?limit=100",
        headers=owner_headers,
    ).json()["events"]
    lookup = next(row for row in audit if row["action"] == "registry.mlc.lookup")
    assert lookup["actor"]["credentialId"] == credential["id"]
    assert lookup["details"]["queryFields"] == ["title"]
    assert lookup["details"]["resultCount"] == 1
    assert "Observed Work" not in str(lookup["details"])

    insufficient = _create_api_credential(
        organization["id"],
        owner_headers,
        scopes=["rights:read"],
        name="Policy reader",
    )
    denied_scope = client.post(
        f"/v1/organizations/{organization['id']}/catalog/mlc/search/works",
        json={"title": "Observed Work"},
        headers={"Authorization": f"Bearer {insufficient['token']}"},
    )
    assert denied_scope.status_code == 403

    outsider_headers = _session_headers(f"outside-{prefix}@example.com")
    outsider = client.post(
        "/v1/organizations",
        json={"slug": f"outside-{prefix}", "name": "Outside Registry User"},
        headers=outsider_headers,
    ).json()
    outsider_credential = _create_api_credential(
        outsider["id"],
        outsider_headers,
        scopes=["registry:read"],
        name="Outside MLC reader",
    )
    denied_tenant = client.post(
        f"/v1/organizations/{organization['id']}/catalog/mlc/search/works",
        json={"title": "Observed Work"},
        headers={"Authorization": f"Bearer {outsider_credential['token']}"},
    )
    assert denied_tenant.status_code == 403


def test_production_configuration_rejects_demo_identity_and_mock_modes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("MOCK_INTEGRATIONS", "true")
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADERS", "true")
    monkeypatch.setenv("ALLOW_DEV_MAGIC_LINKS", "true")
    with pytest.raises(RuntimeError, match="forbidden"):
        Settings()


def test_production_configuration_requires_email_delivery(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("MOCK_INTEGRATIONS", "false")
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADERS", "false")
    monkeypatch.setenv("ALLOW_DEV_MAGIC_LINKS", "false")
    monkeypatch.setenv("RIGHTS_MAGIC_LINK_SECRET", "fixture-a-production-secret-with-32-characters")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://rights:secret@db/rights")
    monkeypatch.setenv("NODE_OPERATOR_EMAILS", "operator@example.com")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://rights.example.com")
    monkeypatch.delenv("MAILGUN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="email delivery"):
        Settings()


def test_production_configuration_requires_separate_webhook_encryption_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("MOCK_INTEGRATIONS", "false")
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADERS", "false")
    monkeypatch.setenv("ALLOW_DEV_MAGIC_LINKS", "false")
    monkeypatch.setenv("RIGHTS_MAGIC_LINK_SECRET", "fixture-a-production-secret-with-32-characters")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://rights:secret@db/rights")
    monkeypatch.setenv("NODE_OPERATOR_EMAILS", "operator@example.com")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://rights.example.com")
    monkeypatch.setenv("MAILGUN_API_KEY", "key-production-test")
    monkeypatch.setenv("MAILGUN_DOMAIN", "mail.rights.example.com")
    monkeypatch.setenv("WEBHOOK_ALLOW_PRIVATE_TARGETS", "false")
    monkeypatch.delenv("WEBHOOK_ENCRYPTION_KEY_B64", raising=False)
    with pytest.raises(RuntimeError, match="WEBHOOK_ENCRYPTION_KEY_B64"):
        Settings()


def test_production_mlc_connector_requires_complete_credentials_and_https(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("MOCK_INTEGRATIONS", "false")
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADERS", "false")
    monkeypatch.setenv("ALLOW_DEV_MAGIC_LINKS", "false")
    monkeypatch.setenv("RIGHTS_MAGIC_LINK_SECRET", "fixture-a-production-secret-with-32-characters")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://rights:secret@db/rights")
    monkeypatch.setenv("NODE_OPERATOR_EMAILS", "operator@example.com")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://rights.example.com")
    monkeypatch.setenv("MAILGUN_API_KEY", "key-production-test")
    monkeypatch.setenv("MAILGUN_DOMAIN", "mail.rights.example.com")
    monkeypatch.setenv("WEBHOOK_ENCRYPTION_KEY_B64", "configured-separate-key")
    monkeypatch.setenv("WEBHOOK_ALLOW_PRIVATE_TARGETS", "false")
    monkeypatch.setenv("SOURCE_CODE_URL", "https://source.example.com/clef-rights-node/0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("SOURCE_CODE_REVISION", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("MLC_ENABLED", "true")
    monkeypatch.delenv("MLC_USERNAME", raising=False)
    monkeypatch.delenv("MLC_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="MLC_USERNAME and MLC_PASSWORD"):
        Settings()

    monkeypatch.setenv("MLC_USERNAME", "member@example.com")
    monkeypatch.setenv("MLC_PASSWORD", "production-credential")
    monkeypatch.setenv("MLC_BASE_URL", "http://public-api.themlc.com")
    with pytest.raises(RuntimeError, match="HTTPS origin"):
        Settings()


def test_production_configuration_requires_a_corresponding_source_offer(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("MOCK_INTEGRATIONS", "false")
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADERS", "false")
    monkeypatch.setenv("ALLOW_DEV_MAGIC_LINKS", "false")
    monkeypatch.setenv("RIGHTS_MAGIC_LINK_SECRET", "fixture-a-production-secret-with-32-characters")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://rights:secret@db/rights")
    monkeypatch.setenv("NODE_OPERATOR_EMAILS", "operator@example.com")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://rights.example.com")
    monkeypatch.setenv("MAILGUN_API_KEY", "key-production-test")
    monkeypatch.setenv("MAILGUN_DOMAIN", "mail.rights.example.com")
    monkeypatch.setenv("WEBHOOK_ENCRYPTION_KEY_B64", "configured-separate-key")
    monkeypatch.setenv("WEBHOOK_ALLOW_PRIVATE_TARGETS", "false")
    monkeypatch.delenv("SOURCE_CODE_URL", raising=False)
    monkeypatch.delenv("SOURCE_CODE_REVISION", raising=False)
    with pytest.raises(RuntimeError, match="SOURCE_CODE_URL and SOURCE_CODE_REVISION"):
        Settings()

    monkeypatch.setenv("SOURCE_CODE_URL", "http://source.example.com/clef-rights-node")
    monkeypatch.setenv("SOURCE_CODE_REVISION", "0123456789abcdef0123456789abcdef01234567")
    with pytest.raises(RuntimeError, match="SOURCE_CODE_URL must be an HTTPS URL"):
        Settings()

    monkeypatch.setenv("SOURCE_CODE_URL", "https://source.example.com/clef-rights-node/0123456789abcdef0123456789abcdef01234567")
    for revision in ("release-branch", "v1.0.0", "0123456", "a" * 40):
        monkeypatch.setenv("SOURCE_CODE_REVISION", revision)
        with pytest.raises(RuntimeError, match="full Git commit hash named in SOURCE_CODE_URL"):
            Settings()


def test_node_info_discloses_license_and_running_source_revision():
    response = client.get("/v1/node/info")
    assert response.status_code == 200
    assert response.json()["softwareLicense"] == "AGPL-3.0-only"
    assert response.json()["deploymentMode"] == settings.NODE_DEPLOYMENT_MODE
    assert response.json()["sandboxGuestAccess"] == settings.SANDBOX_GUEST_ACCESS
    assert response.json()["webhookDeliveryEnabled"] == settings.WEBHOOK_DELIVERY_ENABLED
    assert response.json()["sourceCodeRevision"] == settings.SOURCE_CODE_REVISION
    assert "sourceCodeUrl" in response.json()


def test_node_readiness_is_operator_only_and_contains_no_credentials():
    denied = client.get(
        "/v1/node/readiness",
        headers=_session_headers(f"member-{uuid.uuid4().hex[:8]}@example.com"),
    )
    assert denied.status_code == 403

    response = client.get(
        "/v1/node/readiness",
        headers=_session_headers("operator@example.com", role="admin"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deploymentMode"] == settings.NODE_DEPLOYMENT_MODE
    assert {row["key"] for row in body["checks"]} >= {
        "database_migrations",
        "receipt_signing_key",
        "expiry_worker",
        "webhook_worker",
        "mlc_adapter",
        "ddex_adapter",
    }
    serialized = response.text.lower()
    assert "password" not in serialized
    assert "api_key" not in serialized


def test_database_pool_checks_connections_before_checkout():
    assert engine.pool._pre_ping is True


def test_public_sandbox_configuration_rejects_live_integrations(monkeypatch):
    monkeypatch.setenv("NODE_DEPLOYMENT_MODE", "public_sandbox")
    monkeypatch.setenv("MLC_ENABLED", "true")
    monkeypatch.setenv("MLC_USERNAME", "member@example.com")
    monkeypatch.setenv("MLC_PASSWORD", "not-a-real-credential")
    with pytest.raises(RuntimeError, match="Public sandbox mode forbids live"):
        Settings()


def test_deployment_mode_rejects_unknown_values(monkeypatch):
    monkeypatch.setenv("NODE_DEPLOYMENT_MODE", "publicish")
    with pytest.raises(RuntimeError, match="NODE_DEPLOYMENT_MODE"):
        Settings()


def test_sandbox_guest_access_is_unavailable_outside_explicit_mode():
    response = client.post("/v1/sandbox/session")
    assert response.status_code == 404


def test_public_sandbox_creates_anonymous_short_lived_operator_session(monkeypatch):
    monkeypatch.setattr(settings, "NODE_DEPLOYMENT_MODE", "public_sandbox")
    monkeypatch.setattr(settings, "SANDBOX_GUEST_ACCESS", True)

    response = client.post("/v1/sandbox/session")
    assert response.status_code == 200
    session = response.json()["session"]
    assert session["email"].startswith("sandbox-")
    assert session["email"].endswith("@sandbox.invalid")

    context = client.get("/v1/session", headers={"X-Session-Id": session["id"]})
    assert context.status_code == 200
    assert context.json()["user"]["nodeRole"] == "admin"
    assert context.json()["organizations"] == []


def test_sandbox_guest_access_requires_public_sandbox_mode(monkeypatch):
    monkeypatch.setenv("NODE_DEPLOYMENT_MODE", "adopter_staging")
    monkeypatch.setenv("SANDBOX_GUEST_ACCESS", "true")
    with pytest.raises(RuntimeError, match="may only be enabled"):
        Settings()


def test_public_sandbox_guest_profile_requires_no_email_identity(monkeypatch):
    values = {
        "APP_ENV": "production",
        "NODE_DEPLOYMENT_MODE": "public_sandbox",
        "SANDBOX_GUEST_ACCESS": "true",
        "AUTH_SIGNUP_MODE": "operator_only",
        "DEMO_MODE": "false",
        "MOCK_INTEGRATIONS": "false",
        "ALLOW_DEV_IDENTITY_HEADERS": "false",
        "ALLOW_DEV_MAGIC_LINKS": "false",
        "RIGHTS_MAGIC_LINK_SECRET": "fixture-a-production-secret-with-32-characters",
        "DATABASE_URL": "postgresql+psycopg2://rights:secret@db/rights",
        "CORS_ALLOW_ORIGINS": "https://sandbox.example.com",
        "WEBHOOK_ENCRYPTION_KEY_B64": "configured-separate-key",
        "WEBHOOK_ALLOW_PRIVATE_TARGETS": "false",
        "WEBHOOK_DELIVERY_ENABLED": "false",
        "SOURCE_CODE_URL": "https://source.example.com/clef-rights-node/0123456789abcdef0123456789abcdef01234567",
        "SOURCE_CODE_REVISION": "0123456789abcdef0123456789abcdef01234567",
        "MLC_ENABLED": "false",
        "DDEX_ENABLED": "false",
        "DDEX_LIVE_MESSAGES": "false",
        "MUSICBRAINZ_ENABLED": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for key in (
        "MAILGUN_API_KEY",
        "NODE_OPERATOR_EMAILS",
        "OPENROUTER_API_KEY",
        "SLACK_WEBHOOK_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    configured = Settings()
    assert configured.SANDBOX_GUEST_ACCESS is True
    assert configured.MAILGUN_API_KEY is None
    assert configured.NODE_OPERATOR_EMAILS == set()


def test_disabled_webhook_delivery_rejects_partner_endpoints(monkeypatch):
    prefix = f"no-webhooks-{uuid.uuid4().hex[:8]}"
    headers = _session_headers(f"{prefix}@example.com")
    organization = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "No Webhooks Label"},
        headers=headers,
    ).json()
    monkeypatch.setattr(settings, "WEBHOOK_DELIVERY_ENABLED", False)

    response = client.get(
        f"/v1/organizations/{organization['id']}/webhooks/events",
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Webhook partner delivery is disabled for this deployment"


def _create_pending_composition_permission(
    prefix: str,
    *,
    term_start: str = "2026-08-01",
    term_end: str = "2027-07-31",
    intended_usage: str = "derivative_remix",
):
    rightsholder_headers = _session_headers(f"{prefix}-rights@example.com")
    requester_headers = _session_headers(f"{prefix}-requester@example.com")
    operator_headers = _session_headers("operator@example.com", role="admin")

    rightsholder_org = client.post(
        "/v1/organizations",
        json={"slug": f"{prefix}-rights", "name": "Example Publisher"},
        headers=rightsholder_headers,
    ).json()
    requester_org = client.post(
        "/v1/organizations",
        json={"slug": f"{prefix}-requester", "name": "Example Licensee"},
        headers=requester_headers,
    ).json()
    usage = {key: "blocked" for key in USAGE_KEYS}
    usage[intended_usage] = "requires_approval"
    restrictions = {key: "allowed" for key in RESTRICTION_KEYS}
    policy = client.put(
        f"/v1/organizations/{rightsholder_org['id']}/rights/mlc:{prefix}",
        json={
            "artist_name": "Example Artist",
            "contract": {
                "policyVersion": "clef.rights-policy.v1",
                "matrix": {"usage": usage, "restrictions": restrictions},
            },
        },
        headers=rightsholder_headers,
    ).json()
    claim = client.post(
        "/v1/authority-claims",
        json={
            "org_id": rightsholder_org["id"],
            "rights_contract_id": policy["id"],
            "right_type": "composition",
            "territory": "US",
            "evidence": {"source": "mlc", "mlcSongCode": prefix, "share": "100.0000"},
        },
        headers=rightsholder_headers,
    ).json()
    verified = client.post(
        f"/v1/authority-claims/{claim['id']}/verify",
        json={"evidence_note": "Matched authorized catalog"},
        headers=operator_headers,
    )
    assert verified.status_code == 200
    permission = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org["id"],
            "authority_claim_id": claim["id"],
            "intended_usage": intended_usage,
            "territory": "US",
            "term_start": term_start,
            "term_end": term_end,
        },
        headers=requester_headers,
    ).json()
    return {
        "permission": permission,
        "requester_org": requester_org,
        "rightsholder_org": rightsholder_org,
        "requester_headers": requester_headers,
        "rightsholder_headers": rightsholder_headers,
        "operator_headers": operator_headers,
    }


def test_permission_assignment_routes_the_decision_to_the_named_rights_administrator():
    prefix = f"assignment-{uuid.uuid4().hex[:8]}"
    setup = _create_pending_composition_permission(prefix)
    reviewer_email = f"reviewer-{prefix}@example.com"
    added = client.post(
        f"/v1/organizations/{setup['rightsholder_org']['id']}/members",
        json={"email": reviewer_email, "role": "rights_manager"},
        headers=setup["rightsholder_headers"],
    )
    assert added.status_code == 200
    reviewer_headers = _session_headers(reviewer_email)
    permission_id = setup["permission"]["id"]

    blank_reason = client.post(
        f"/v1/permission-requests/{permission_id}/review-assignments",
        json={"reviewer_user_id": added.json()["userId"], "reason": "   "},
        headers=setup["rightsholder_headers"],
    )
    assert blank_reason.status_code == 422

    assigned = client.post(
        f"/v1/permission-requests/{permission_id}/review-assignments",
        json={
            "reviewer_user_id": added.json()["userId"],
            "reason": "Composition requests for this client route to its assigned administrator",
        },
        headers=setup["rightsholder_headers"],
    )
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()["action"] == "assigned"
    assert assigned.json()["reviewer"]["email"] == reviewer_email

    requester_view = client.get(
        f"/v1/permission-requests/{permission_id}",
        headers=setup["requester_headers"],
    ).json()["reviewAssignment"]
    assert requester_view == {
        "id": assigned.json()["id"],
        "action": "assigned",
        "createdAt": assigned.json()["createdAt"],
    }

    wrong_reviewer = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Owner attempted to bypass routing"},
        headers=setup["rightsholder_headers"],
    )
    assert wrong_reviewer.status_code == 403
    assert wrong_reviewer.json()["detail"] == "This request is assigned to another reviewer"

    approved = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Assigned administrator reviewed the requested scope"},
        headers=reviewer_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["receipt"]["payload"]["decision"]["actor"]["userId"] == added.json()["userId"]

    db = SessionLocal()
    try:
        assignment = (
            db.query(PermissionReviewAssignmentRecord)
            .filter(PermissionReviewAssignmentRecord.id == assigned.json()["id"])
            .one()
        )
        assignment.reason = "rewritten routing reason"
        with pytest.raises(RuntimeError, match="append-only"):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_exact_credit_obligations_and_post_use_compliance_evidence_remain_separate():
    prefix = f"compliance-{uuid.uuid4().hex[:8]}"
    today = datetime.datetime.utcnow().date()
    term_start = today - datetime.timedelta(days=30)
    term_end = today + datetime.timedelta(days=365)
    published_at = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    setup = _create_pending_composition_permission(
        prefix,
        term_start=term_start.isoformat(),
        term_end=term_end.isoformat(),
    )
    permission_id = setup["permission"]["id"]
    obligations = {
        "attribution": {
            "required": True,
            "credit_text": "Written by Example Artist; licensed through Example Publisher",
            "backlink_required": True,
            "backlink_url": "https://example.com/artists/example-artist",
            "placements": ["description", "metadata"],
            "metadata_fields": {
                "composer": "Example Artist",
                "rights_url": "https://example.com/artists/example-artist",
            },
        },
        "publication_reporting_required": True,
        "publication_evidence_due_days": 14,
        "usage_reporting_frequency": "quarterly",
    }
    approved = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={
            "decision": "approved",
            "note": "Approved with exact credit and reporting obligations",
            "obligations": obligations,
        },
        headers=setup["rightsholder_headers"],
    )
    assert approved.status_code == 200, approved.text
    signed_obligations = approved.json()["receipt"]["payload"]["permission"]["licenseObligations"]
    assert signed_obligations["attribution"]["creditText"] == obligations["attribution"]["credit_text"]
    assert signed_obligations["attribution"]["backlinkUrl"] == obligations["attribution"]["backlink_url"]
    assert signed_obligations["publicationReporting"] == {
        "required": True,
        "evidenceDueDaysAfterPublication": 14,
        "frequency": "quarterly",
    }

    outside_term = client.post(
        f"/v1/permission-requests/{permission_id}/usage-reports",
        json={
            "publication_url": "https://video.example/outside-term",
            "published_at": datetime.datetime.combine(
                term_start - datetime.timedelta(days=1),
                datetime.time(hour=12),
            ).isoformat() + "Z",
            "idempotency_key": "outside-term",
        },
        headers=setup["requester_headers"],
    )
    assert outside_term.status_code == 422

    future_report = client.post(
        f"/v1/permission-requests/{permission_id}/usage-reports",
        json={
            "publication_url": "https://video.example/future",
            "published_at": (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat() + "Z",
            "idempotency_key": "future-publication",
        },
        headers=setup["requester_headers"],
    )
    assert future_report.status_code == 422
    assert future_report.json()["detail"] == "Reported publication cannot be in the future"

    report_payload = {
        "publication_url": "https://video.example/releases/licensed-remix",
        "published_at": published_at.replace(microsecond=0).isoformat() + "Z",
        "platform": "Example Video",
        "declared_credit_text": obligations["attribution"]["credit_text"],
        "declared_backlink_url": obligations["attribution"]["backlink_url"],
        "metadata": obligations["attribution"]["metadata_fields"],
        "evidence": {"snapshotSha256": "b" * 64},
        "idempotency_key": "release-1-publication",
    }
    report = client.post(
        f"/v1/permission-requests/{permission_id}/usage-reports",
        json=report_payload,
        headers=setup["requester_headers"],
    )
    assert report.status_code == 201, report.text
    report_json = report.json()
    assert report_json["assertionType"] == "requester_reported"
    assert report_json["effectOnPermission"] == "none"
    assert report_json["currentReviewOutcome"] == "pending"
    assert report_json["automatedChecks"] == {
        "creditTextExactMatch": True,
        "backlinkExactMatch": True,
        "metadataExactMatches": {"composer": True, "rights_url": True},
        "reportedWithinDeadline": True,
        "effect": "comparison_only",
    }
    replay = client.post(
        f"/v1/permission-requests/{permission_id}/usage-reports",
        json=report_payload,
        headers=setup["requester_headers"],
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == report_json["id"]
    conflict = client.post(
        f"/v1/permission-requests/{permission_id}/usage-reports",
        json={**report_payload, "publication_url": "https://video.example/changed"},
        headers=setup["requester_headers"],
    )
    assert conflict.status_code == 409

    requester_review = client.post(
        f"/v1/permission-usage-reports/{report_json['id']}/reviews",
        json={
            "outcome": "compliant",
            "note": "Requester attempted to review its own declaration",
            "idempotency_key": "self-review",
        },
        headers=setup["requester_headers"],
    )
    assert requester_review.status_code == 403

    blank_review_note = client.post(
        f"/v1/permission-usage-reports/{report_json['id']}/reviews",
        json={"outcome": "compliant", "note": "   ", "idempotency_key": "blank-review"},
        headers=setup["rightsholder_headers"],
    )
    assert blank_review_note.status_code == 422

    reviewed = client.post(
        f"/v1/permission-usage-reports/{report_json['id']}/reviews",
        json={
            "outcome": "compliant",
            "note": "Credit text, backlink, and required metadata match the signed grant",
            "evidence": {"reviewedSnapshotSha256": "c" * 64},
            "idempotency_key": "authority-review-1",
        },
        headers=setup["rightsholder_headers"],
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["assertionType"] == "authority_reviewed"
    assert reviewed.json()["effectOnPermission"] == "none"

    ledger = client.get(
        f"/v1/permission-requests/{permission_id}",
        headers=setup["rightsholder_headers"],
    ).json()
    assert ledger["status"] == "approved"
    assert ledger["licenseObligations"] == signed_obligations
    assert ledger["usageReports"][0]["currentReviewOutcome"] == "compliant"

    db = SessionLocal()
    try:
        stored_report = db.query(PermissionUsageReportRecord).filter(PermissionUsageReportRecord.id == report_json["id"]).one()
        stored_review = db.query(PermissionComplianceReviewRecord).filter(PermissionComplianceReviewRecord.id == reviewed.json()["id"]).one()
        stored_report.platform = "rewritten platform"
        with pytest.raises(RuntimeError, match="append-only"):
            db.commit()
        db.rollback()
        stored_review.note = "rewritten compliance conclusion"
        with pytest.raises(RuntimeError, match="append-only"):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_permission_dispute_and_revocation_create_signed_linked_records():
    setup = _create_pending_composition_permission(f"lifecycle-{uuid.uuid4().hex[:8]}")
    permission_id = setup["permission"]["id"]
    approved = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Approved for the declared scope"},
        headers=setup["rightsholder_headers"],
    )
    assert approved.status_code == 200
    grant = approved.json()["receipt"]
    grant_id = grant["payload"]["receiptId"]

    requester_cannot_revoke = client.post(
        f"/v1/permission-requests/{permission_id}/lifecycle-events",
        json={"event_type": "revocation", "reason": "Requester attempted revocation"},
        headers=setup["requester_headers"],
    )
    assert requester_cannot_revoke.status_code == 403

    disputed = client.post(
        f"/v1/permission-requests/{permission_id}/lifecycle-events",
        json={"event_type": "dispute", "reason": "Delivered use exceeds the declared edit"},
        headers=setup["requester_headers"],
    )
    assert disputed.status_code == 200
    assert disputed.json()["status"] == "disputed"
    dispute_receipt = disputed.json()["receipt"]
    assert dispute_receipt["payload"]["schemaVersion"] == "clef.permission-status-receipt.v1"
    assert dispute_receipt["payload"]["event"]["type"] == "dispute"
    assert dispute_receipt["payload"]["event"]["priorReceiptId"] == grant_id
    assert dispute_receipt["payload"]["event"]["priorPayloadHash"] == grant["proof"]["payloadHash"]
    assert dispute_receipt["transparency"]["previousEntryHash"] == grant["transparency"]["entryHash"]
    assert client.post("/v1/receipts/verify", json={"receipt": dispute_receipt}).json()["valid"] is True

    duplicate_dispute = client.post(
        f"/v1/permission-requests/{permission_id}/lifecycle-events",
        json={"event_type": "dispute", "reason": "Duplicate dispute"},
        headers=setup["requester_headers"],
    )
    assert duplicate_dispute.status_code == 409

    revoked = client.post(
        f"/v1/permission-requests/{permission_id}/lifecycle-events",
        json={"event_type": "revocation", "reason": "Authority revoked the disputed grant"},
        headers=setup["rightsholder_headers"],
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    revocation_receipt = revoked.json()["receipt"]
    assert revocation_receipt["payload"]["event"]["priorReceiptId"] == dispute_receipt["payload"]["receiptId"]
    assert revocation_receipt["payload"]["event"]["previousStatus"] == "disputed"
    assert revocation_receipt["payload"]["event"]["resultingStatus"] == "revoked"
    assert revocation_receipt["transparency"]["previousEntryHash"] == dispute_receipt["transparency"]["entryHash"]
    assert client.post("/v1/receipts/verify", json={"receipt": revocation_receipt}).json()["valid"] is True
    assert client.post("/v1/receipts/verify", json={"receipt": grant}).json()["valid"] is True

    ledger = client.get(
        f"/v1/permission-requests/{permission_id}",
        headers=setup["requester_headers"],
    ).json()
    assert ledger["status"] == "revoked"
    assert ledger["receiptId"] == grant_id
    assert ledger["latestReceiptId"] == revocation_receipt["payload"]["receiptId"]
    assert [row["eventType"] for row in ledger["lifecycleRecords"]] == ["dispute", "revocation"]


def test_permission_correction_requires_a_compatible_active_replacement_grant():
    setup = _create_pending_composition_permission(f"correction-{uuid.uuid4().hex[:8]}")
    original_id = setup["permission"]["id"]
    original = client.post(
        f"/v1/permission-requests/{original_id}/decide",
        json={"decision": "approved", "note": "Original approval"},
        headers=setup["rightsholder_headers"],
    ).json()["receipt"]
    original_details = client.get(
        f"/v1/permission-requests/{original_id}",
        headers=setup["requester_headers"],
    ).json()
    replacement_request = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": original_details["requester"]["organizationId"],
            "authority_claim_id": original_details["authority"]["claimId"],
            "intended_usage": original_details["intendedUsage"],
            "territory": original_details["territory"],
            "term_start": "2026-09-01",
            "term_end": "2027-08-31",
            "context": {"releaseTitle": "Corrected scope"},
        },
        headers=setup["requester_headers"],
    )
    assert replacement_request.status_code == 200
    replacement_id = replacement_request.json()["id"]
    replacement = client.post(
        f"/v1/permission-requests/{replacement_id}/decide",
        json={"decision": "approved", "note": "Replacement approval"},
        headers=setup["rightsholder_headers"],
    ).json()["receipt"]

    missing_replacement = client.post(
        f"/v1/permission-requests/{original_id}/lifecycle-events",
        json={"event_type": "correction", "reason": "Corrected dates"},
        headers=setup["rightsholder_headers"],
    )
    assert missing_replacement.status_code == 422

    corrected = client.post(
        f"/v1/permission-requests/{original_id}/lifecycle-events",
        json={
            "event_type": "correction",
            "reason": "Superseded by the corrected term",
            "replacement_receipt_id": replacement["payload"]["receiptId"],
        },
        headers=setup["rightsholder_headers"],
    )
    assert corrected.status_code == 200
    correction_receipt = corrected.json()["receipt"]
    assert corrected.json()["status"] == "corrected"
    assert correction_receipt["payload"]["event"]["originalGrantReceiptId"] == original["payload"]["receiptId"]
    assert correction_receipt["payload"]["event"]["replacementReceiptId"] == replacement["payload"]["receiptId"]
    assert correction_receipt["payload"]["event"]["replacementPayloadHash"] == replacement["proof"]["payloadHash"]
    assert client.post("/v1/receipts/verify", json={"receipt": correction_receipt}).json()["valid"] is True


def test_operator_expiry_run_creates_one_signed_record_after_the_declared_term():
    setup = _create_pending_composition_permission(
        f"expiry-{uuid.uuid4().hex[:8]}",
        term_start="2025-02-01",
        term_end="2026-01-31",
    )
    permission_id = setup["permission"]["id"]
    approved = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Short controlled term"},
        headers=setup["rightsholder_headers"],
    )
    assert approved.status_code == 200
    grant = approved.json()["receipt"]

    forbidden = client.post(
        "/v1/operator/permission-requests/expire-due",
        json={"as_of": "2026-02-01"},
        headers=setup["requester_headers"],
    )
    assert forbidden.status_code == 403

    not_due = client.post(
        "/v1/operator/permission-requests/expire-due",
        json={"as_of": "2026-01-31"},
        headers=setup["operator_headers"],
    )
    assert not_due.status_code == 200
    assert not_due.json()["expiredCount"] == 0

    expired = client.post(
        "/v1/operator/permission-requests/expire-due",
        json={"as_of": "2026-02-01"},
        headers=setup["operator_headers"],
    )
    assert expired.status_code == 200
    assert expired.json()["expiredCount"] == 1
    expiry_id = expired.json()["receipts"][0]["receiptId"]
    assert client.get(f"/v1/receipts/{expiry_id}").status_code == 401
    receipt = client.get(f"/v1/receipts/{expiry_id}", headers=setup["requester_headers"]).json()
    assert receipt["payload"]["status"] == "expired"
    assert receipt["payload"]["event"]["type"] == "expiry"
    assert receipt["payload"]["event"]["priorReceiptId"] == grant["payload"]["receiptId"]
    assert receipt["payload"]["event"]["effectiveAt"] == "2026-02-01T00:00:00Z"
    assert client.post("/v1/receipts/verify", json={"receipt": receipt}).json()["valid"] is True
    details = client.get(
        f"/v1/permission-requests/{permission_id}",
        headers=setup["requester_headers"],
    ).json()
    assert details["status"] == "expired"
    assert details["latestReceiptId"] == expiry_id

    idempotent = client.post(
        "/v1/operator/permission-requests/expire-due",
        json={"as_of": "2026-02-02"},
        headers=setup["operator_headers"],
    )
    assert idempotent.status_code == 200
    assert idempotent.json()["expiredCount"] == 0


def test_approval_and_grant_receipt_are_one_atomic_transaction(monkeypatch):
    setup = _create_pending_composition_permission(f"atomic-{uuid.uuid4().hex[:8]}")
    permission_id = setup["permission"]["id"]

    def fail_signing(**_kwargs):
        raise RuntimeError("signing service failed")

    monkeypatch.setattr(receipt_signer, "sign_receipt", fail_signing)
    with pytest.raises(RuntimeError, match="signing service failed"):
        client.post(
            f"/v1/permission-requests/{permission_id}/decide",
            json={"decision": "approved", "note": "Must roll back with receipt failure"},
            headers=setup["rightsholder_headers"],
        )

    details = client.get(
        f"/v1/permission-requests/{permission_id}",
        headers=setup["requester_headers"],
    ).json()
    assert details["status"] == "pending"
    assert details["receiptId"] is None


def test_concurrent_approvals_allocate_distinct_linked_transparency_entries():
    setups = [
        _create_pending_composition_permission(f"concurrent-{uuid.uuid4().hex[:8]}")
        for _ in range(2)
    ]

    def approve(setup):
        return client.post(
            f"/v1/permission-requests/{setup['permission']['id']}/decide",
            json={"decision": "approved", "note": "Concurrent controlled approval"},
            headers=setup["rightsholder_headers"],
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(approve, setups))
    assert [response.status_code for response in responses] == [200, 200]
    receipts = sorted(
        [response.json()["receipt"] for response in responses],
        key=lambda receipt: receipt["transparency"]["sequence"],
    )
    assert receipts[1]["transparency"]["sequence"] == receipts[0]["transparency"]["sequence"] + 1
    assert receipts[1]["transparency"]["previousEntryHash"] == receipts[0]["transparency"]["entryHash"]
    assert all(client.post("/v1/receipts/verify", json={"receipt": receipt}).json()["valid"] for receipt in receipts)


def test_ddex_mwl_exports_are_authorized_persisted_and_retrievable(monkeypatch):
    setup = _create_pending_composition_permission(f"ddex-{uuid.uuid4().hex[:8]}", intended_usage="ugc_creator")
    monkeypatch.setattr(ddex_adapter, "dpid", "PADPIDA0000000001O")
    monkeypatch.setattr(ddex_adapter, "partner_dpid", "PADPIDA0000000002M")
    monkeypatch.setattr(ddex_adapter, "sender_name", "Clef Rights Node")
    monkeypatch.setattr(ddex_adapter, "partner_name", "DDEX Partner")
    monkeypatch.setattr(ddex_adapter, "require", lambda capability: None)
    monkeypatch.setattr(ddex_adapter, "validate_mwl", lambda payload: ET.fromstring(payload))

    export_body = {
        "work_title": "Example Work",
        "work_identifier": "MLC-WORK-123",
        "rights_controller_role": "owner",
        "territory": "US",
        "rights_type": "MechanicalRight",
        "use_type": "UserMakeAvailableUserProvided",
        "distribution_channel_type": "Internet",
        "right_share_percentage": "100",
        "royalty_rate_calculation_type": "NegotiatedRoyaltyRate",
        "royalty_percentage": "100",
        "percentage_type": "PercentageOfNetRevenue",
        "confirm_composition_only_scope": True,
    }
    permission_id = setup["permission"]["id"]
    requester_credential = _create_api_credential(
        setup["requester_org"]["id"],
        setup["requester_headers"],
        scopes=["ddex:read", "ddex:write"],
        name="DDEX request transport",
    )
    requester_bearer = {
        "Authorization": f"Bearer {requester_credential['token']}"
    }
    request_export = client.post(
        f"/v1/permission-requests/{permission_id}/ddex/mwl/license-request",
        json=export_body,
        headers=requester_bearer,
    )
    assert request_export.status_code == 200
    assert request_export.headers["x-clef-rights-scope"] == "composition-only"
    request_root = ET.fromstring(request_export.content)
    assert request_root.tag.endswith("LicenseRequestMessage")
    assert request_root.findtext("MessageHeader/MessageControlType") == "TestMessage"
    controller = request_root.find("RightShareList/RightShare/RightsController")
    assert controller is not None and controller.attrib == {"IsOwner": "true"}

    exchange_id = request_export.headers["x-clef-ddex-exchange-id"]
    stored = client.get(
        f"/v1/ddex/exchanges/{exchange_id}", headers=requester_bearer
    )
    assert stored.status_code == 200
    assert stored.content == request_export.content
    db = SessionLocal()
    try:
        exchange = db.query(DdexExchangeRecord).filter(DdexExchangeRecord.id == exchange_id).one()
        assert exchange.payload_sha256 == hashlib.sha256(request_export.content).hexdigest()
        assert exchange.validation_status == "schema_valid"
        assert exchange.generated_by_user_id is None
        assert exchange.generated_by_api_credential_id == requester_credential["id"]
    finally:
        db.close()

    outsider_headers = _session_headers(f"ddex-outsider-{uuid.uuid4()}@example.com")
    forbidden = client.get(f"/v1/ddex/exchanges/{exchange_id}", headers=outsider_headers)
    assert forbidden.status_code == 403

    acknowledgement_body = {
        "acknowledgement_type": "transport",
        "status": "received",
        "partner_message_id": "partner-ack-001",
        "media_type": "application/xml",
        "payload": "<Acknowledgement status=\"received\" />",
        "evidence": {
            "source": "partner-sftp-receipt",
            "observedAt": "2026-07-13T12:00:00Z",
        },
        "idempotency_key": "partner-ack-001",
    }
    acknowledgement = client.post(
        f"/v1/ddex/exchanges/{exchange_id}/acknowledgements",
        json=acknowledgement_body,
        headers=requester_bearer,
    )
    assert acknowledgement.status_code == 201, acknowledgement.text
    acknowledgement_json = acknowledgement.json()
    assert acknowledgement_json["assertionType"] == "observed"
    assert acknowledgement_json["effectOnPermission"] == "none"
    assert acknowledgement_json["recordedBy"]["credentialId"] == requester_credential["id"]
    assert acknowledgement_json["payloadSha256"] == hashlib.sha256(
        acknowledgement_body["payload"].encode("utf-8")
    ).hexdigest()
    replay = client.post(
        f"/v1/ddex/exchanges/{exchange_id}/acknowledgements",
        json=acknowledgement_body,
        headers=requester_bearer,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == acknowledgement_json["id"]
    conflicting = client.post(
        f"/v1/ddex/exchanges/{exchange_id}/acknowledgements",
        json={**acknowledgement_body, "status": "accepted"},
        headers=requester_bearer,
    )
    assert conflicting.status_code == 409
    listed_acknowledgements = client.get(
        f"/v1/ddex/exchanges/{exchange_id}/acknowledgements",
        headers=setup["rightsholder_headers"],
    )
    assert listed_acknowledgements.status_code == 200
    assert listed_acknowledgements.json()[0]["id"] == acknowledgement_json["id"]
    assert "payload" not in listed_acknowledgements.json()[0]
    acknowledgement_detail = client.get(
        f"/v1/ddex/acknowledgements/{acknowledgement_json['id']}",
        headers=requester_bearer,
    )
    assert acknowledgement_detail.json()["payload"] == acknowledgement_body["payload"]
    db = SessionLocal()
    try:
        persisted_ack = (
            db.query(DdexAcknowledgementRecord)
            .filter(DdexAcknowledgementRecord.id == acknowledgement_json["id"])
            .one()
        )
        assert persisted_ack.recorded_by_user_id is None
        assert persisted_ack.recorded_by_api_credential_id == requester_credential["id"]
        persisted_ack.status = "accepted"
        with pytest.raises(RuntimeError, match="append-only"):
            db.commit()
        db.rollback()
    finally:
        db.close()

    decision = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Approved for the declared scope"},
        headers=setup["rightsholder_headers"],
    )
    assert decision.status_code == 200
    receipt_id = decision.json()["receipt"]["payload"]["receiptId"]
    decision_export = client.post(
        f"/v1/permission-requests/{permission_id}/ddex/mwl/license-decision",
        json=export_body,
        headers=setup["rightsholder_headers"],
    )
    assert decision_export.status_code == 200
    decision_root = ET.fromstring(decision_export.content)
    assert decision_root.tag.endswith("LicenseMessage")
    assert decision_root.findtext("LicenseList/License/LicenseId/ProprietaryId") == receipt_id
    request_reference = decision_root.find("LicenseList/License/LicenseRequestId")
    assert request_reference is not None
    assert request_reference.attrib["Namespace"] == "PADPIDA0000000001O"


def test_ddex_mwl_refuses_derivative_scope_even_when_connector_is_available(monkeypatch):
    setup = _create_pending_composition_permission(f"ddex-derivative-{uuid.uuid4().hex[:8]}")
    monkeypatch.setattr(ddex_adapter, "require", lambda capability: None)
    response = client.post(
        f"/v1/permission-requests/{setup['permission']['id']}/ddex/mwl/license-request",
        json={
            "work_title": "Derivative Work",
            "work_identifier": "MLC-DERIVATIVE-1",
            "rights_controller_role": "owner",
            "territory": "US",
            "confirm_composition_only_scope": True,
        },
        headers=setup["requester_headers"],
    )
    assert response.status_code == 409
    assert "cannot represent" in response.json()["detail"]


def test_magic_link_is_single_use_session_is_hashed_and_logout_revokes_it(monkeypatch):
    from types import SimpleNamespace

    now = datetime.datetime.utcnow()
    monkeypatch.setattr("services.auth.datetime", SimpleNamespace(
        datetime=SimpleNamespace(utcnow=lambda: now), timedelta=datetime.timedelta,
    ))
    email = f"magic-{uuid.uuid4()}@example.com"
    invited = client.post("/auth/invite", json={"email": email})
    assert invited.status_code == 202
    token = parse_qs(urlparse(invited.json()["devLink"]).query)["token"][0]
    second_invite = client.post("/auth/invite", json={"email": email})
    assert second_invite.status_code == 202
    second_token = parse_qs(urlparse(second_invite.json()["devLink"]).query)["token"][0]
    assert second_token != token

    validated = client.get("/auth/validate", params={"token": token})
    assert validated.status_code == 200
    raw_session_id = validated.json()["session"]["id"]
    assert raw_session_id
    db = SessionLocal()
    try:
        stored = db.query(MagicSession).filter(MagicSession.email == email).one()
        assert stored.id == hashlib.sha256(raw_session_id.encode("utf-8")).hexdigest()
        assert stored.id != raw_session_id
    finally:
        db.close()

    replay = client.get("/auth/validate", params={"token": token})
    assert replay.status_code == 409
    second_validation = client.get("/auth/validate", params={"token": second_token})
    assert second_validation.status_code == 200
    assert client.get("/auth/validate", params={"token": second_token}).status_code == 409
    session_headers = {"X-Session-Id": raw_session_id}
    current = client.get("/v1/session", headers=session_headers)
    assert current.status_code == 200
    assert current.json()["user"]["email"] == email

    revoked = client.delete("/auth/session", headers=session_headers)
    assert revoked.status_code == 204
    expired = client.get("/v1/session", headers=session_headers)
    assert expired.status_code == 401


def test_operator_only_signup_does_not_disclose_or_accept_other_addresses(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SIGNUP_MODE", "operator_only")
    denied = client.post("/auth/invite", json={"email": "outside@example.com"})
    assert denied.status_code == 202
    assert denied.json() == {"ok": True, "sent": True}
    assert "devLink" not in denied.json()

    allowed = client.post("/auth/invite", json={"email": "operator@example.com"})
    assert allowed.status_code == 202
    assert "devLink" in allowed.json()


def test_v1_list_views_are_membership_scoped_and_directory_is_sanitized():
    setup = _create_pending_composition_permission(f"views-{uuid.uuid4().hex[:8]}")
    permission_id = setup["permission"]["id"]
    permission = client.get(
        f"/v1/permission-requests/{permission_id}", headers=setup["requester_headers"]
    )
    assert permission.status_code == 200
    assert permission.json()["directions"] == ["outbound"]

    requester_session = client.get("/v1/session", headers=setup["requester_headers"]).json()
    rightsholder_session = client.get("/v1/session", headers=setup["rightsholder_headers"]).json()
    requester_org_id = requester_session["organizations"][0]["id"]
    rightsholder_org_id = rightsholder_session["organizations"][0]["id"]

    outbound = client.get(
        f"/v1/organizations/{requester_org_id}/permission-requests",
        headers=setup["requester_headers"],
    )
    assert outbound.status_code == 200
    assert outbound.json()["permissionRequests"][0]["directions"] == ["outbound"]
    inbound = client.get(
        f"/v1/organizations/{rightsholder_org_id}/permission-requests",
        headers=setup["rightsholder_headers"],
    )
    assert inbound.status_code == 200
    assert inbound.json()["permissionRequests"][0]["directions"] == ["inbound"]

    policies = client.get(
        f"/v1/organizations/{rightsholder_org_id}/rights",
        headers=setup["rightsholder_headers"],
    )
    assert policies.status_code == 200
    assert len(policies.json()["policies"]) == 1
    cross_tenant = client.get(
        f"/v1/organizations/{rightsholder_org_id}/rights",
        headers=setup["requester_headers"],
    )
    assert cross_tenant.status_code == 403

    directory = client.get(
        "/v1/directory/authority-claims", headers=setup["requester_headers"]
    )
    assert directory.status_code == 200
    matching = [
        claim
        for claim in directory.json()["claims"]
        if claim["id"] == permission.json()["authority"]["claimId"]
    ]
    assert len(matching) == 1
    assert "evidence" not in matching[0]


def test_operator_review_queue_rejects_claim_with_distinct_review_audit():
    prefix = f"review-{uuid.uuid4().hex[:8]}"
    rightsholder_headers = _session_headers(f"{prefix}@example.com")
    operator_headers = _session_headers("operator@example.com", role="admin")
    org = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "Review Publisher"},
        headers=rightsholder_headers,
    ).json()
    usage = {key: "blocked" for key in USAGE_KEYS}
    restrictions = {key: "allowed" for key in RESTRICTION_KEYS}
    policy = client.put(
        f"/v1/organizations/{org['id']}/rights/mlc:{prefix}",
        json={
            "artist_name": "Review Artist",
            "contract": {"matrix": {"usage": usage, "restrictions": restrictions}},
        },
        headers=rightsholder_headers,
    ).json()
    invalid_fingerprint = client.post(
        "/v1/authority-claims",
        json={
            "org_id": org["id"],
            "rights_contract_id": policy["id"],
            "right_type": "composition",
            "territory": "US",
            "evidence": {
                "source": "manual",
                "reference": "unverified-document",
                "documentSha256": "not-a-digest",
            },
        },
        headers=rightsholder_headers,
    )
    assert invalid_fingerprint.status_code == 422

    document_sha256 = "a" * 64
    claim = client.post(
        "/v1/authority-claims",
        json={
            "org_id": org["id"],
            "rights_contract_id": policy["id"],
            "right_type": "composition",
            "territory": "US",
            "evidence": {
                "source": "manual",
                "reference": "unverified-document",
                "evidenceUri": f"urn:label-dms:{prefix}",
                "documentSha256": document_sha256,
            },
        },
        headers=rightsholder_headers,
    ).json()

    forbidden = client.get(
        "/v1/operator/authority-claims", headers=rightsholder_headers
    )
    assert forbidden.status_code == 403
    queue = client.get("/v1/operator/authority-claims", headers=operator_headers)
    assert queue.status_code == 200
    assert claim["id"] in {item["id"] for item in queue.json()["claims"]}
    queued_claim = next(item for item in queue.json()["claims"] if item["id"] == claim["id"])
    assert queued_claim["evidence"]["documentSha256"] == document_sha256
    assert queued_claim["evidence"]["evidenceUri"] == f"urn:label-dms:{prefix}"

    rejected = client.post(
        f"/v1/authority-claims/{claim['id']}/reject",
        json={"evidence_note": "Submitted reference did not establish authority"},
        headers=operator_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["reviewedAt"] is not None

    own_claims = client.get(
        f"/v1/organizations/{org['id']}/authority-claims",
        headers=rightsholder_headers,
    ).json()["claims"]
    reviewed = next(item for item in own_claims if item["id"] == claim["id"])
    assert reviewed["status"] == "rejected"
    assert reviewed["verifiedAt"] is None


def test_operator_detects_overclaimed_authority_and_preserves_valid_split_ownership():
    prefix = f"conflict-{uuid.uuid4().hex[:8]}"
    operator_headers = _session_headers("operator@example.com", role="admin")
    usage = {key: "blocked" for key in USAGE_KEYS}
    usage["derivative_remix"] = "requires_approval"
    restrictions = {key: "allowed" for key in RESTRICTION_KEYS}
    work_key = f"mlc:{prefix}"

    def create_claim(label: str, share: str):
        headers = _session_headers(f"{label}-{prefix}@example.com")
        org = client.post(
            "/v1/organizations",
            json={"slug": f"{label}-{prefix}", "name": f"{label.title()} Publisher"},
            headers=headers,
        ).json()
        policy = client.put(
            f"/v1/organizations/{org['id']}/rights/{work_key}",
            json={
                "artist_name": "Shared Work Artist",
                "contract": {
                    "policyVersion": "clef.rights-policy.v1",
                    "matrix": {"usage": usage, "restrictions": restrictions},
                },
            },
            headers=headers,
        ).json()
        claim = client.post(
            "/v1/authority-claims",
            json={
                "org_id": org["id"],
                "rights_contract_id": policy["id"],
                "right_type": "composition",
                "territory": "US",
                "evidence": {"source": "controlled-test", "reference": f"{label}-{prefix}", "share": share},
            },
            headers=headers,
        ).json()
        return headers, org, claim

    _, first_org, first_claim = create_claim("first", "70")
    first_verified = client.post(
        f"/v1/authority-claims/{first_claim['id']}/verify",
        json={"evidence_note": "First controlled share reviewed"},
        headers=operator_headers,
    )
    assert first_verified.status_code == 200
    assert first_verified.json()["status"] == "verified"

    second_headers, _, second_claim = create_claim("second", "50")
    second_verification = client.post(
        f"/v1/authority-claims/{second_claim['id']}/verify",
        json={"evidence_note": "Combined share requires conflict resolution"},
        headers=operator_headers,
    )
    assert second_verification.status_code == 200
    assert second_verification.json()["status"] == "disputed"
    conflict = second_verification.json()["conflicts"][0]
    assert conflict["basis"]["reason"] == "controlled_share_exceeds_100"
    assert conflict["basis"]["combinedShare"] == "120"

    directory = client.get(
        "/v1/directory/authority-claims",
        params={"work_key": work_key},
        headers=second_headers,
    ).json()["claims"]
    assert directory == []
    forbidden = client.get(
        "/v1/operator/authority-conflicts",
        headers=second_headers,
    )
    assert forbidden.status_code == 403
    queue = client.get(
        "/v1/operator/authority-conflicts",
        headers=operator_headers,
    )
    assert queue.status_code == 200
    assert conflict["id"] in {row["id"] for row in queue.json()["conflicts"]}

    keep_first = "claim_a" if conflict["claimA"]["claimId"] == first_claim["id"] else "claim_b"
    resolved = client.post(
        f"/v1/operator/authority-conflicts/{conflict['id']}/resolve",
        json={"resolution": keep_first, "note": "First claimant supplied controlling evidence; second claim rejected"},
        headers=operator_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    resolved_claims = {resolved.json()["claimA"]["claimId"]: resolved.json()["claimA"], resolved.json()["claimB"]["claimId"]: resolved.json()["claimB"]}
    assert resolved_claims[first_claim["id"]]["status"] == "verified"
    assert resolved_claims[second_claim["id"]]["status"] == "rejected"

    restored_directory = client.get(
        "/v1/directory/authority-claims",
        params={"work_key": work_key},
        headers=second_headers,
    ).json()["claims"]
    assert {row["id"] for row in restored_directory} == {first_claim["id"]}

    _, _, compatible_claim = create_claim("compatible", "30")
    compatible = client.post(
        f"/v1/authority-claims/{compatible_claim['id']}/verify",
        json={"evidence_note": "Thirty percent plus seventy percent is a valid split"},
        headers=operator_headers,
    )
    assert compatible.status_code == 200
    assert compatible.json()["status"] == "verified"
    final_directory = client.get(
        "/v1/directory/authority-claims",
        params={"work_key": work_key},
        headers=second_headers,
    ).json()["claims"]
    assert {row["id"] for row in final_directory} == {first_claim["id"], compatible_claim["id"]}
    assert first_org["id"] in {row["organization"]["id"] for row in final_directory}


def test_api_credentials_are_hashed_scoped_expiring_revocable_and_audited():
    prefix = f"credential-{uuid.uuid4().hex[:8]}"
    owner_headers = _session_headers(f"{prefix}@example.com")
    other_headers = _session_headers(f"other-{prefix}@example.com")
    org = client.post(
        "/v1/organizations",
        json={"slug": prefix, "name": "Automation Label", "organization_type": "label"},
        headers=owner_headers,
    ).json()
    other_org = client.post(
        "/v1/organizations",
        json={"slug": f"other-{prefix}", "name": "Other Label", "organization_type": "label"},
        headers=other_headers,
    ).json()
    member_email = f"member-{prefix}@example.com"
    client.post(
        f"/v1/organizations/{org['id']}/members",
        json={"email": member_email, "role": "member"},
        headers=owner_headers,
    )
    member_headers = _session_headers(member_email)
    assert client.get(
        f"/v1/organizations/{org['id']}/api-credentials",
        headers=member_headers,
    ).status_code == 403
    invalid_scope = client.post(
        f"/v1/organizations/{org['id']}/api-credentials",
        json={"name": "Unsafe key", "scopes": ["operator:admin"], "expires_in_days": 30},
        headers=owner_headers,
    )
    assert invalid_scope.status_code == 422

    issued = _create_api_credential(
        org["id"],
        owner_headers,
        scopes=["directory:read", "rights:read", "audit:read"],
    )
    token = issued["token"]
    assert token.startswith("clef_rn_")
    assert issued["tokenPrefix"] == token[:20]

    listed = client.get(
        f"/v1/organizations/{org['id']}/api-credentials",
        headers=owner_headers,
    )
    assert listed.status_code == 200
    assert listed.json()["credentials"][0]["id"] == issued["id"]
    assert "token" not in listed.json()["credentials"][0]
    assert "tokenSha256" not in listed.json()["credentials"][0]

    db = SessionLocal()
    try:
        stored = db.query(ApiCredentialRecord).filter(ApiCredentialRecord.id == issued["id"]).one()
        assert stored.token_sha256 == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert stored.token_sha256 != token
    finally:
        db.close()

    bearer = {"Authorization": f"Bearer {token}"}
    own_rights = client.get(f"/v1/organizations/{org['id']}/rights", headers=bearer)
    assert own_rights.status_code == 200
    cross_tenant = client.get(f"/v1/organizations/{other_org['id']}/rights", headers=bearer)
    assert cross_tenant.status_code == 403

    missing_scope = client.get(
        f"/v1/organizations/{org['id']}/permission-requests",
        headers=bearer,
    )
    assert missing_scope.status_code == 403
    ambiguous = client.get(
        f"/v1/organizations/{org['id']}/rights",
        headers={**owner_headers, **bearer},
    )
    assert ambiguous.status_code == 400

    machine_audit = client.get(f"/v1/organizations/{org['id']}/audit-events", headers=bearer)
    assert machine_audit.status_code == 200
    assert "api_credential.created" in {row["action"] for row in machine_audit.json()["events"]}

    db = SessionLocal()
    try:
        credential = db.query(ApiCredentialRecord).filter(ApiCredentialRecord.id == issued["id"]).one()
        credential.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    expired = client.get(f"/v1/organizations/{org['id']}/rights", headers=bearer)
    assert expired.status_code == 401

    active = _create_api_credential(org["id"], owner_headers, scopes=["rights:read"], name="Rotated key")
    revoked = client.delete(
        f"/v1/organizations/{org['id']}/api-credentials/{active['id']}",
        headers=owner_headers,
    )
    assert revoked.status_code == 204
    rejected = client.get(
        f"/v1/organizations/{org['id']}/rights",
        headers={"Authorization": f"Bearer {active['token']}"},
    )
    assert rejected.status_code == 401
    audit = client.get(f"/v1/organizations/{org['id']}/audit-events", headers=owner_headers)
    actions = [row["action"] for row in audit.json()["events"]]
    assert "api_credential.revoked" in actions

    db = SessionLocal()
    try:
        audit_event = db.query(AuditEventRecord).filter(AuditEventRecord.org_id == org["id"]).first()
        audit_event.action = "tampered"
        with pytest.raises(RuntimeError, match="append-only"):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_api_credentials_create_decide_and_revoke_permission_without_synthetic_users():
    setup = _create_pending_composition_permission(f"machine-{uuid.uuid4().hex[:8]}")
    requester_context = client.get("/v1/session", headers=setup["requester_headers"]).json()
    rightsholder_context = client.get("/v1/session", headers=setup["rightsholder_headers"]).json()
    requester_org_id = requester_context["organizations"][0]["id"]
    rightsholder_org_id = rightsholder_context["organizations"][0]["id"]
    original = client.get(
        f"/v1/permission-requests/{setup['permission']['id']}",
        headers=setup["requester_headers"],
    ).json()
    claim_id = original["authority"]["claimId"]

    requester_credential = _create_api_credential(
        requester_org_id,
        setup["requester_headers"],
        scopes=["directory:read", "permissions:request", "permissions:read", "permissions:lifecycle"],
        name="License requester bot",
    )
    authority_credential = _create_api_credential(
        rightsholder_org_id,
        setup["rightsholder_headers"],
        scopes=["permissions:read", "permissions:decide", "permissions:lifecycle"],
        name="Rights decision bot",
    )
    requester_bearer = {"Authorization": f"Bearer {requester_credential['token']}"}
    authority_bearer = {"Authorization": f"Bearer {authority_credential['token']}"}

    created = client.post(
        "/v1/permission-requests",
        json={
            "requester_org_id": requester_org_id,
            "authority_claim_id": claim_id,
            "intended_usage": "derivative_remix",
            "territory": "US",
            "term_start": "2026-09-01",
            "term_end": "2027-08-31",
            "context": {"releaseTitle": "Machine-requested remix"},
            "provenance": {"sourceAssetSha256": "b" * 64},
        },
        headers=requester_bearer,
    )
    assert created.status_code == 200
    assert created.json()["status"] == "pending"
    permission_id = created.json()["id"]

    unauthorized_decision = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Wrong organization"},
        headers=requester_bearer,
    )
    assert unauthorized_decision.status_code == 403
    readable_by_both = [
        client.get(f"/v1/permission-requests/{permission_id}", headers=headers)
        for headers in (requester_bearer, authority_bearer)
    ]
    assert all(response.status_code == 200 for response in readable_by_both)

    approved = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Approved by scoped label automation"},
        headers=authority_bearer,
    )
    assert approved.status_code == 200
    grant = approved.json()["receipt"]
    assert grant["payload"]["permission"]["requestedBy"] == {
        "type": "api_credential",
        "credentialId": requester_credential["id"],
        "credentialName": "License requester bot",
        "organizationId": requester_org_id,
    }
    assert grant["payload"]["decision"]["actor"] == {
        "type": "api_credential",
        "credentialId": authority_credential["id"],
        "credentialName": "Rights decision bot",
        "organizationId": rightsholder_org_id,
    }
    assert client.post("/v1/receipts/verify", json={"receipt": grant}).json()["valid"] is True

    disputed = client.post(
        f"/v1/permission-requests/{permission_id}/lifecycle-events",
        json={"event_type": "dispute", "reason": "Automated delivery check found a scope mismatch"},
        headers=requester_bearer,
    )
    assert disputed.status_code == 200
    assert disputed.json()["receipt"]["payload"]["event"]["actor"]["type"] == "api_credential"
    revoked = client.post(
        f"/v1/permission-requests/{permission_id}/lifecycle-events",
        json={"event_type": "revocation", "reason": "Authority confirmed the scope mismatch"},
        headers=authority_bearer,
    )
    assert revoked.status_code == 200
    assert revoked.json()["receipt"]["payload"]["event"]["actor"]["credentialId"] == authority_credential["id"]

    db = SessionLocal()
    try:
        permission = db.query(PermissionRequestRecord).filter(PermissionRequestRecord.id == permission_id).one()
        assert permission.requested_by_user_id is None
        assert permission.requested_by_api_credential_id == requester_credential["id"]
        assert permission.decided_by_user_id is None
        assert permission.decided_by_api_credential_id == authority_credential["id"]
    finally:
        db.close()

    requester_audit = client.get(
        f"/v1/organizations/{requester_org_id}/audit-events",
        headers=setup["requester_headers"],
    ).json()["events"]
    permission_events = [row for row in requester_audit if row["resource"]["id"] == permission_id]
    assert {row["action"] for row in permission_events} >= {
        "permission_request.created",
        "permission_request.approved",
        "permission_request.disputed",
        "permission_request.revoked",
    }
    assert any(
        row["actor"].get("credentialId") == authority_credential["id"]
        for row in permission_events
        if row["action"] == "permission_request.approved"
    )


def test_settlement_ledger_reconciles_exact_external_payment_and_beneficiary_payouts():
    setup = _create_pending_composition_permission(f"settlement-{uuid.uuid4().hex[:8]}")
    permission_id = setup["permission"]["id"]
    permission = client.get(
        f"/v1/permission-requests/{permission_id}",
        headers=setup["rightsholder_headers"],
    ).json()
    requester_org_id = permission["requester"]["organizationId"]
    authority_org_id = permission["authority"]["organizationId"]

    invalid_shares = client.post(
        f"/v1/permission-requests/{permission_id}/settlement",
        json={
            "currency": "USD",
            "minimum_commitment_minor": 1000,
            "royalty_rate_bps": 1000,
            "beneficiaries": [
                {"name": "Artist", "identifier": "ipi:artist", "share_bps": 9000},
            ],
        },
        headers=setup["rightsholder_headers"],
    )
    assert invalid_shares.status_code == 422

    requester_credential = _create_api_credential(
        requester_org_id,
        setup["requester_headers"],
        scopes=["settlements:read", "settlements:write"],
        name="License finance bot",
    )
    authority_credential = _create_api_credential(
        authority_org_id,
        setup["rightsholder_headers"],
        scopes=["settlements:read", "settlements:write", "settlements:reconcile"],
        name="Royalty operations bot",
    )
    requester_bearer = {"Authorization": f"Bearer {requester_credential['token']}"}
    authority_bearer = {"Authorization": f"Bearer {authority_credential['token']}"}

    created = client.post(
        f"/v1/permission-requests/{permission_id}/settlement",
        json={
            "currency": "usd",
            "minimum_commitment_minor": 1000,
            "minimum_recoupable": True,
            "royalty_rate_bps": 1000,
            "royalty_basis": "net_revenue",
            "beneficiaries": [
                {"name": "Artist", "identifier": "ipi:artist", "share_bps": 6000},
                {"name": "Publisher", "identifier": "ipi:publisher", "share_bps": 4000},
            ],
            "terms": {"statementFrequency": "quarterly"},
            "confirm_immutable_terms": True,
        },
        headers=authority_bearer,
    )
    assert created.status_code == 201, created.text
    settlement = created.json()
    settlement_id = settlement["id"]
    assert settlement["assertionType"] == "provisional"
    assert settlement["createdBy"]["credentialId"] == authority_credential["id"]
    assert settlement["totals"]["obligationMinor"] == 1000

    reserved = client.post(
        f"/v1/settlements/{settlement_id}/entries",
        json={"kind": "reserve", "amount_minor": 1000, "idempotency_key": "reserve-1"},
        headers=requester_bearer,
    )
    assert reserved.status_code == 201
    assert reserved.json()["recordedBy"]["credentialId"] == requester_credential["id"]
    replayed_reserve = client.post(
        f"/v1/settlements/{settlement_id}/entries",
        json={"kind": "reserve", "amount_minor": 1000, "idempotency_key": "reserve-1"},
        headers=requester_bearer,
    )
    assert replayed_reserve.status_code == 201
    assert replayed_reserve.json()["id"] == reserved.json()["id"]
    conflicting_replay = client.post(
        f"/v1/settlements/{settlement_id}/entries",
        json={"kind": "reserve", "amount_minor": 1001, "idempotency_key": "reserve-1"},
        headers=requester_bearer,
    )
    assert conflicting_replay.status_code == 409

    premature_royalty = client.post(
        f"/v1/settlements/{settlement_id}/royalty-calculations",
        json={
            "basis_amount_minor": 12345,
            "period_start": "2026-08-01",
            "period_end": "2026-10-31",
            "external_reference": "statement:2026-q3",
            "evidence": {"sha256": "1" * 64},
            "idempotency_key": "royalty-2026-q3",
        },
        headers=authority_bearer,
    )
    assert premature_royalty.status_code == 409

    approved = client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Approved with the recorded royalty terms"},
        headers=setup["rightsholder_headers"],
    )
    assert approved.status_code == 200

    royalty_payload = {
        "basis_amount_minor": 12345,
        "period_start": "2026-08-01",
        "period_end": "2026-10-31",
        "external_reference": "statement:2026-q3",
        "evidence": {"sha256": "1" * 64},
        "idempotency_key": "royalty-2026-q3",
    }
    royalty = client.post(
        f"/v1/settlements/{settlement_id}/royalty-calculations",
        json=royalty_payload,
        headers=authority_bearer,
    )
    assert royalty.status_code == 201, royalty.text
    assert royalty.json()["amountMinor"] == 1235
    assert royalty.json()["calculation"]["rounding"] == "nearest_minor_unit_half_up"
    overlap = client.post(
        f"/v1/settlements/{settlement_id}/royalty-calculations",
        json={**royalty_payload, "period_start": "2026-10-01", "period_end": "2026-12-31", "idempotency_key": "royalty-overlap"},
        headers=authority_bearer,
    )
    assert overlap.status_code == 409

    current = client.get(
        f"/v1/permission-requests/{permission_id}/settlement",
        headers=requester_bearer,
    ).json()
    beneficiaries = {row["identifier"]: row["id"] for row in current["beneficiaries"]}
    assert current["totals"]["obligationMinor"] == 1235
    assert current["totals"]["beneficiaries"] == [
        {
            "beneficiaryId": beneficiaries["ipi:artist"],
            "identifier": "ipi:artist",
            "name": "Artist",
            "shareBps": 6000,
            "obligationMinor": 741,
            "payoutMinor": 0,
            "varianceMinor": -741,
        },
        {
            "beneficiaryId": beneficiaries["ipi:publisher"],
            "identifier": "ipi:publisher",
            "name": "Publisher",
            "shareBps": 4000,
            "obligationMinor": 494,
            "payoutMinor": 0,
            "varianceMinor": -494,
        },
    ]

    def record_entry(kind: str, amount: int, reference: str, *, beneficiary_id: str | None = None):
        return client.post(
            f"/v1/settlements/{settlement_id}/entries",
            json={
                "kind": kind,
                "amount_minor": amount,
                "beneficiary_id": beneficiary_id,
                "external_reference": reference,
                "evidence": {"sha256": hashlib.sha256(reference.encode()).hexdigest()},
                "idempotency_key": reference,
            },
            headers=authority_bearer,
        )

    payment = record_entry("payment_received", 1235, "bank:payment-001")
    assert payment.status_code == 201, payment.text
    artist_payout = record_entry("payout", 741, "bank:payout-artist", beneficiary_id=beneficiaries["ipi:artist"])
    assert artist_payout.status_code == 201
    unbalanced = client.post(
        f"/v1/settlements/{settlement_id}/reconciliations",
        json={"idempotency_key": "reconcile-before-publisher", "evidence": {"note": "Publisher payout pending"}},
        headers=authority_bearer,
    )
    assert unbalanced.status_code == 201
    assert unbalanced.json()["status"] == "unbalanced"
    assert unbalanced.json()["assertionType"] == "provisional"

    publisher_payout = record_entry("payout", 494, "bank:payout-publisher", beneficiary_id=beneficiaries["ipi:publisher"])
    assert publisher_payout.status_code == 201
    reconciled = client.post(
        f"/v1/settlements/{settlement_id}/reconciliations",
        json={"idempotency_key": "reconcile-paid", "evidence": {"review": "Matched bank and payout records"}},
        headers=authority_bearer,
    )
    assert reconciled.status_code == 201
    assert reconciled.json()["status"] == "balanced"
    assert reconciled.json()["assertionType"] == "paid"
    assert reconciled.json()["totals"]["balanced"] is True
    assert client.get(f"/v1/receipts/{reconciled.json()['receiptId']}").status_code == 401
    reconciliation_receipt = client.get(f"/v1/receipts/{reconciled.json()['receiptId']}", headers=authority_bearer).json()
    assert reconciliation_receipt["payload"]["schemaVersion"] == "clef.settlement-reconciliation-receipt.v1"
    assert reconciliation_receipt["payload"]["settlement"]["ledgerDigest"] == reconciled.json()["ledgerDigest"]
    assert reconciliation_receipt["payload"]["settlement"]["assertionType"] == "paid"
    assert client.post("/v1/receipts/verify", json={"receipt": reconciliation_receipt}).json()["valid"] is True

    final = client.get(
        f"/v1/permission-requests/{permission_id}/settlement",
        headers=authority_bearer,
    ).json()
    assert final["status"] == "paid"
    assert final["assertionType"] == "paid"
    assert final["reconciliationCurrent"] is True
    assert final["totals"]["paymentVarianceMinor"] == 0
    assert final["totals"]["payoutVarianceMinor"] == 0

    audit = client.get(
        f"/v1/organizations/{authority_org_id}/audit-events",
        headers=setup["rightsholder_headers"],
    ).json()["events"]
    actions = {row["action"] for row in audit if row["details"].get("settlementId") == settlement_id}
    assert actions >= {
        "settlement.royalty.calculated",
        "settlement.entry.payment_received",
        "settlement.entry.payout",
        "settlement.reconciliation.recorded",
    }

    db = SessionLocal()
    try:
        stored_settlement = db.query(SettlementRecord).filter(SettlementRecord.id == settlement_id).one()
        stored_settlement.terms = {"tampered": True}
        with pytest.raises(RuntimeError, match="append-only"):
            db.commit()
        db.rollback()
        stored_entry = db.query(SettlementEntryRecord).filter(SettlementEntryRecord.id == payment.json()["id"]).one()
        stored_entry.amount_minor = 1
        with pytest.raises(RuntimeError, match="append-only"):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_paid_settlement_becomes_provisional_when_a_reversal_stales_reconciliation():
    setup = _create_pending_composition_permission(f"reversal-{uuid.uuid4().hex[:8]}")
    permission_id = setup["permission"]["id"]
    permission = client.get(
        f"/v1/permission-requests/{permission_id}",
        headers=setup["rightsholder_headers"],
    ).json()
    created = client.post(
        f"/v1/permission-requests/{permission_id}/settlement",
        json={
            "currency": "USD",
            "minimum_commitment_minor": 100,
            "royalty_rate_bps": 0,
            "beneficiaries": [
                {"name": "Artist", "identifier": "artist:one", "share_bps": 10000},
            ],
            "confirm_immutable_terms": True,
        },
        headers=setup["rightsholder_headers"],
    ).json()
    client.post(
        f"/v1/permission-requests/{permission_id}/decide",
        json={"decision": "approved", "note": "Approved for minimum-fee test"},
        headers=setup["rightsholder_headers"],
    )
    beneficiary_id = created["beneficiaries"][0]["id"]

    def authority_entry(kind: str, amount: int, reference: str, beneficiary: str | None = None):
        return client.post(
            f"/v1/settlements/{created['id']}/entries",
            json={
                "kind": kind,
                "amount_minor": amount,
                "beneficiary_id": beneficiary,
                "external_reference": reference,
                "evidence": {"reference": reference},
                "idempotency_key": reference,
            },
            headers=setup["rightsholder_headers"],
        )

    assert authority_entry("payment_received", 100, "payment-100").status_code == 201
    assert authority_entry("payout", 100, "payout-100", beneficiary_id).status_code == 201
    paid = client.post(
        f"/v1/settlements/{created['id']}/reconciliations",
        json={"idempotency_key": "paid-100"},
        headers=setup["rightsholder_headers"],
    )
    assert paid.json()["assertionType"] == "paid"

    reversed_payment = authority_entry("payment_reversal", 25, "payment-reversal-25")
    assert reversed_payment.status_code == 201
    stale = client.get(
        f"/v1/permission-requests/{permission_id}/settlement",
        headers=setup["requester_headers"],
    ).json()
    assert stale["assertionType"] == "provisional"
    assert stale["reconciliationCurrent"] is False
    assert stale["totals"]["paymentReceivedMinor"] == 75
    excessive_reversal = authority_entry("payment_reversal", 76, "payment-reversal-too-large")
    assert excessive_reversal.status_code == 409

    outsider_headers = _session_headers(f"outsider-{uuid.uuid4().hex[:8]}@example.com")
    outsider_org = client.post(
        "/v1/organizations",
        json={"slug": f"outsider-{uuid.uuid4().hex[:8]}", "name": "Outside Label"},
        headers=outsider_headers,
    ).json()
    outsider_credential = _create_api_credential(
        outsider_org["id"],
        outsider_headers,
        scopes=["settlements:read"],
    )
    forbidden = client.get(
        f"/v1/permission-requests/{permission_id}/settlement",
        headers={"Authorization": f"Bearer {outsider_credential['token']}"},
    )
    assert forbidden.status_code == 403
