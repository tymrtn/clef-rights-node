"""Regression coverage for the four 2026-09-15 launch blockers."""
from copy import deepcopy
import uuid

import pytest

from main import RESTRICTION_KEYS, SessionLocal
from models import AuthorityClaimRecord, PermissionReceiptRecord, PermissionRequestRecord
from test_api import client, _create_pending_composition_permission, _create_api_credential, _session_headers


@pytest.fixture
def scenario():
    prefix = f"safety-{uuid.uuid4().hex[:10]}"
    data = _create_pending_composition_permission(prefix, intended_usage="ads_brand")
    data["policy_url"] = f"/v1/organizations/{data['rightsholder_org']['id']}/rights/mlc:{prefix}"
    data["claim"] = client.get(f"/v1/organizations/{data['rightsholder_org']['id']}/authority-claims", headers=data["rightsholder_headers"]).json()["claims"][0]
    data["body"] = {
        "requester_org_id": data["requester_org"]["id"], "authority_claim_id": data["claim"]["id"],
        "intended_usage": "ads_brand", "territory": "US", "term_start": "2026-09-15", "term_end": "2027-07-31",
        "context": {"restrictionCategories": []},
    }
    return data


def publish(data, *, usage="allowed", restrictions=None):
    policy = client.get(data["policy_url"], headers=data["rightsholder_headers"]).json()
    contract = deepcopy(policy["contract"])
    contract["matrix"]["usage"]["ads_brand"] = usage
    contract["matrix"]["restrictions"].update(restrictions or {})
    contract["metadata"]["privateAuditMarker"] = "synthetic-confidential-example"
    result = client.put(data["policy_url"], headers=data["rightsholder_headers"], json={
        "artist_name": "Synthetic Composer", "expected_version": policy["version"], "contract": contract,
    })
    assert result.status_code == 200, result.text
    return result.json()


def request(data, **changes):
    return client.post("/v1/permission-requests", headers=data["requester_headers"], json={**data["body"], **changes})


def decide(data, permission_id=None, decision="approved", headers=None):
    return client.post(f"/v1/permission-requests/{permission_id or data['permission']['id']}/decide",
        headers=headers or data["rightsholder_headers"], json={"decision": decision, "note": "Reviewed declared use and current conditions"})


def assert_pending_without_receipt(permission_id):
    with SessionLocal() as db:
        assert db.get(PermissionRequestRecord, permission_id).status == "pending"
        assert db.query(PermissionReceiptRecord).filter_by(permission_request_id=permission_id).count() == 0


@pytest.mark.parametrize("category", RESTRICTION_KEYS)
@pytest.mark.parametrize("declaration", ["categories", "legacy"])
def test_denied_content_cannot_be_automatically_approved(scenario, category, declaration):
    publish(scenario, restrictions={category: "denied"})
    context = {"restrictionCategories": [category]} if declaration == "categories" else {"restrictionCategories": [], category: True}
    response = request(scenario, context=context)
    assert response.status_code == 409, response.text
    assert f"restriction:{category}:denied" in response.json()["detail"]["policyEvaluation"]
    with SessionLocal() as db:
        assert db.query(PermissionRequestRecord).filter_by(authority_claim_id=scenario["claim"]["id"]).count() == 1
        assert db.query(PermissionReceiptRecord).filter_by(permission_request_id=scenario["permission"]["id"]).count() == 0


def test_conditional_content_requires_review_and_receipts_record_the_reason(scenario):
    publish(scenario, restrictions={"political": "conditional"})
    pending = request(scenario, context={"restrictionCategories": ["political"]}).json()
    assert pending["status"] == "pending"
    approved = decide(scenario, pending["id"])
    assert approved.status_code == 200, approved.text
    trace = approved.json()["receipt"]["payload"]["permission"]["context"]["policyEvaluation"]
    assert "restriction:political:conditional" in trace["reasons"]
    assert client.post("/v1/receipts/verify", json={"receipt": approved.json()["receipt"]}).json()["valid"]


def test_explicit_nonapplicability_can_auto_approve_and_omission_cannot(scenario):
    publish(scenario, restrictions={"political": "denied"})
    pending = request(scenario, context={}).json()
    assert pending["status"] == "pending"
    assert decide(scenario, pending["id"]).status_code == 409
    assert_pending_without_receipt(pending["id"])
    allowed = request(scenario)
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "approved"


@pytest.mark.parametrize("context", [{"restrictionCategories": "political"}, {"restrictionCategories": ["unknown"]}, {"restrictionCategories": [{}]}, {"political": "false"}])
def test_malformed_content_declarations_are_rejected(scenario, context):
    publish(scenario)
    assert request(scenario, context=context).status_code == 422


@pytest.mark.parametrize("authorized,requested,status", [
    ("US", "FR", 409), ("US", "worldwide", 409), ("US,CA", "US,FR", 409),
    ("US,CA", " ca ", 200), ("US", " us ", 200), ("worldwide", "US,FR", 200),
    ("US", "", 422), ("US", "worldwide except FR", 422),
])
def test_request_must_fit_entire_verified_territory(scenario, authorized, requested, status):
    publish(scenario)
    with SessionLocal() as db:
        db.get(AuthorityClaimRecord, scenario["claim"]["id"]).territory = authorized
        db.commit()
    response = request(scenario, territory=requested)
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["status"] == "approved"
        assert response.json()["receipt"]["payload"]["permission"]["territory"] == ",".join(sorted(code.strip().upper() for code in requested.split(",")))


@pytest.mark.parametrize("changed", ["usage", "restriction", "territory", "authority"])
@pytest.mark.parametrize("actor", ["human", "api"])
def test_pending_request_is_rechecked_before_signing(scenario, changed, actor):
    if changed == "usage":
        publish(scenario, usage="blocked")
    elif changed == "restriction":
        with SessionLocal() as db:
            db.get(PermissionRequestRecord, scenario["permission"]["id"]).context = {"restrictionCategories": ["political"]}
            db.commit()
        publish(scenario, restrictions={"political": "denied"})
    else:
        with SessionLocal() as db:
            claim = db.get(AuthorityClaimRecord, scenario["claim"]["id"])
            if changed == "territory":
                claim.territory = "FR"
            else:
                claim.status = "revoked"
            db.commit()
    headers = scenario["rightsholder_headers"]
    if actor == "api":
        credential = _create_api_credential(scenario["rightsholder_org"]["id"], headers, scopes=["permissions:decide"], name="Decision regression")
        headers = {"Authorization": f"Bearer {credential['token']}"}
    response = decide(scenario, headers=headers)
    assert response.status_code == 409, response.text
    assert_pending_without_receipt(scenario["permission"]["id"])
    assert decide(scenario, decision="rejected", headers=headers).status_code == 200


def test_receipts_require_party_access_and_log_exposes_only_hashes(scenario):
    publish(scenario)
    grant = request(scenario).json()["receipt"]
    receipt_id = grant["payload"]["receiptId"]
    url = f"/v1/receipts/{receipt_id}"
    assert client.get(url).status_code == 401
    stranger = _session_headers(f"stranger-{uuid.uuid4().hex}@example.com")
    assert client.get(url, headers=stranger).status_code == 403
    # Operator status alone confers no access to parties' private grant documents.
    assert client.get(url, headers=scenario["operator_headers"]).status_code == 403
    for side in ("requester", "rightsholder"):
        response = client.get(url, headers=scenario[f"{side}_headers"])
        assert response.status_code == 200
        assert response.json() == grant
        assert response.headers["cache-control"] == "private, no-store"
        credential = _create_api_credential(scenario[f"{side}_org"]["id"], scenario[f"{side}_headers"], scopes=["permissions:read"], name="Receipt reader")
        assert client.get(url, headers={"Authorization": f"Bearer {credential['token']}"}).status_code == 200
    credential = _create_api_credential(scenario["requester_org"]["id"], scenario["requester_headers"], scopes=["directory:read"], name="Directory only")
    assert client.get(url, headers={"Authorization": f"Bearer {credential['token']}"}).status_code == 403
    unrelated = client.post("/v1/organizations", headers=stranger, json={"slug": f"other-{uuid.uuid4().hex[:10]}", "name": "Unrelated Label"}).json()
    credential = _create_api_credential(unrelated["id"], stranger, scopes=["permissions:read"], name="Other organization")
    assert client.get(url, headers={"Authorization": f"Bearer {credential['token']}"}).status_code == 403
    assert set(client.get("/v1/transparency/head").json()) == {"sequence", "entryHash"}
    log = client.get("/v1/transparency/entries", params={"from_sequence": grant["transparency"]["sequence"]})
    assert log.json()["entries"][0] == grant["transparency"]
    assert "synthetic-confidential-example" not in log.text
    assert client.post("/v1/receipts/verify", json={"receipt": grant}).json()["valid"] is True


def test_political_advertising_implies_political_content_even_if_requester_denies_it(scenario):
    policy = publish(scenario, restrictions={"political": "denied"})
    policy["contract"]["matrix"]["usage"]["ads_political"] = "allowed"
    saved = client.put(scenario["policy_url"], headers=scenario["rightsholder_headers"], json={
        "artist_name": "Synthetic Composer", "expected_version": policy["version"], "contract": policy["contract"],
    })
    assert saved.status_code == 200
    response = request(scenario, intended_usage="ads_political", context={"restrictionCategories": [], "political": False})
    assert response.status_code == 409
    assert "restriction:political:denied" in response.json()["detail"]["policyEvaluation"]
