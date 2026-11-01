"""The public demonstration must use the same permission checks as an adopter."""
import copy
import datetime as dt
import uuid
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import sandbox_tour
from models import SandboxTourRecord
from test_api import client, settings, SessionLocal, _session_headers
from main import limiter


@pytest.fixture
def guest(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(settings, "NODE_DEPLOYMENT_MODE", "public_sandbox")
    monkeypatch.setattr(settings, "SANDBOX_GUEST_ACCESS", True)
    response = client.post("/v1/sandbox/session")
    assert response.status_code == 200, response.text
    headers = {"X-Session-Id": response.json()["session"]["id"]}
    return headers


def prepared(headers):
    response = client.post("/v1/sandbox/tour", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def approval():
    return {"decision": "approved", "note": "Fictional approval for the declared instrumental study",
        "obligations": {"attribution": {"required": True,
            "credit_text": "Paper Skies — Mara Vale (fictional sandbox example)",
            "placements": ["description", "metadata"]},
            "publication_reporting_required": True, "publication_evidence_due_days": 30,
            "usage_reporting_frequency": "once"}}


def test_tour_is_opt_in_and_unavailable_in_adopter_mode(monkeypatch):
    monkeypatch.setattr(settings, "NODE_DEPLOYMENT_MODE", "adopter_staging")
    monkeypatch.setattr(settings, "SANDBOX_GUEST_ACCESS", True)
    assert client.post("/v1/sandbox/tour").status_code == 404
    assert client.get("/v1/sandbox/tour").status_code == 404


def test_tour_requires_an_actual_guest_session(guest):
    assert client.post("/v1/sandbox/tour").status_code == 401
    headers = _session_headers(f"ordinary-{uuid.uuid4().hex}@example.test")
    assert client.post("/v1/sandbox/tour", headers=headers).status_code == 403
    assert client.get("/v1/sandbox/tour", headers=guest).status_code == 404


def test_tour_has_two_separate_pending_rights_and_real_signed_receipts(guest):
    tour = prepared(guest)
    assert tour["synthetic"] is True
    assert [side["rightType"] for side in tour["sides"]] == ["master", "composition"]
    for side in tour["sides"]:
        assert side["permission"]["status"] == "pending"
        assignment = side["permission"]["reviewAssignment"]
        assert assignment and assignment["action"] == "assigned"
        assert side["policy"]["contract"]["metadata"]["synthetic"] is True
        assets = client.get(f"/v1/organizations/{side['orgId']}/catalog/assets", headers=guest).json()["assets"]
        assert len(assets) == 1 and assets[0]["sourceReference"].startswith("urn:clef:synthetic:")
        assert assets[0]["client"]["name"] == tour["artist"]
        response = client.post(f"/v1/permission-requests/{side['permissionId']}/decide", headers=guest, json=approval())
        assert response.status_code == 200, response.text
        receipt = response.json()["receipt"]
        verified = client.post("/v1/receipts/verify", json={"receipt": receipt}).json()
        assert verified["valid"] is True and verified["signatureValid"] is True
        tampered = copy.deepcopy(receipt)
        tampered["payload"]["permission"]["territory"] = "worldwide"
        assert client.post("/v1/receipts/verify", json={"receipt": tampered}).json()["valid"] is False
        assert client.get(f"/v1/receipts/{receipt['payload']['receiptId']}").status_code == 401
    refreshed = prepared(guest)
    assert [s["permissionId"] for s in refreshed["sides"]] == [s["permissionId"] for s in tour["sides"]]
    assert all(s["permission"]["status"] == "approved" for s in refreshed["sides"])
    assert len(client.get("/v1/session", headers=guest).json()["organizations"]) == 3


@pytest.mark.parametrize("probe", ["training", "territory", "duration", "political", "voice"])
def test_tour_safeguards_reject_out_of_scope_requests(guest, probe):
    side = prepared(guest)["sides"][0]
    request = copy.deepcopy(side["request"])
    if probe == "training": request["intended_usage"] = "ai_model_training"
    if probe == "territory": request["territory"] = "worldwide"
    if probe == "duration": request["context"]["aiUse"]["sourceDurationSeconds"] = 31
    if probe == "political": request["context"]["restrictionCategories"] = ["political"]
    if probe == "voice": request["context"]["aiUse"]["inputAssets"] = ["isolated_vocals"]
    response = client.post("/v1/permission-requests", headers=guest, json=request)
    assert response.status_code == 409, response.text


def test_tour_resume_preserves_policy_changes_and_blocks_stale_approval(guest):
    side = prepared(guest)["sides"][0]
    contract = side["policy"]["contract"]
    contract["matrix"]["usage"]["ai_grounded_generation"] = "blocked"
    changed = client.put(f"/v1/organizations/{side['orgId']}/rights/{side['workKey']}", headers=guest,
        json={"artist_name": "Mara Vale (fictional)", "expected_version": 1, "contract": contract})
    assert changed.status_code == 200
    refreshed = prepared(guest)
    assert refreshed["sides"][0]["policy"]["version"] == 2
    assert client.post(f"/v1/permission-requests/{side['permissionId']}/decide", headers=guest, json=approval()).status_code == 409


def test_interrupted_tour_resumes_without_duplicate_catalogs_or_requests(guest, monkeypatch):
    original = sandbox_tour._call
    failed = False

    async def interrupt(client_, method, path, **kwargs):
        nonlocal failed
        value = await original(client_, method, path, **kwargs)
        if path == "/v1/permission-requests" and method == "POST" and not failed:
            failed = True
            raise sandbox_tour.HTTPException(503, "Simulated lost response")
        return value

    monkeypatch.setattr(sandbox_tour, "_call", interrupt)
    assert client.post("/v1/sandbox/tour", headers=guest).status_code == 503
    tour = prepared(guest)
    ledger = client.get(f"/v1/organizations/{tour['requester']['id']}/permission-requests", headers=guest).json()
    assert len(ledger["permissionRequests"]) == 2
    assert len(client.get("/v1/session", headers=guest).json()["organizations"]) == 3


def test_guest_lease_prevents_concurrent_preparation_and_recovers_after_expiry(guest):
    user_id = client.get("/v1/session", headers=guest).json()["user"]["id"]
    with SessionLocal() as db:
        db.add(SandboxTourRecord(user_id=user_id, lease_token="another-worker", lease_until=dt.datetime.utcnow() + dt.timedelta(minutes=5)))
        db.commit()
    response = client.post("/v1/sandbox/tour", headers=guest)
    assert response.status_code == 409 and response.headers["Retry-After"] == "5"
    with SessionLocal() as db:
        db.get(SandboxTourRecord, user_id).lease_until = dt.datetime.utcnow() - dt.timedelta(seconds=1)
        db.commit()
    assert prepared(guest)["synthetic"] is True


def test_each_guest_gets_separate_records_and_cannot_read_another_tour(guest):
    first = prepared(guest)
    response = client.post("/v1/sandbox/session")
    other = {"X-Session-Id": response.json()["session"]["id"]}
    assert client.get("/v1/sandbox/tour", headers=other).status_code == 404
    second = prepared(other)
    assert second["requester"]["id"] != first["requester"]["id"]
    assert second["identifiers"]["isrc"] != first["identifiers"]["isrc"]
    assert client.get(f"/v1/permission-requests/{first['sides'][0]['permissionId']}", headers=other).status_code == 403


def test_expired_worker_is_fenced_before_it_can_duplicate_a_permission(guest, monkeypatch):
    original = sandbox_tour._call
    paused, resume = threading.Event(), threading.Event()
    first_call = True

    async def suspend(client_, method, path, **kwargs):
        nonlocal first_call
        if method == "POST" and path == "/v1/permission-requests" and first_call:
            first_call = False
            paused.set()
            assert await asyncio.to_thread(resume.wait, 15), "Worker was not released"
        return await original(client_, method, path, **kwargs)

    monkeypatch.setattr(sandbox_tour, "_call", suspend)
    user_id = client.get("/v1/session", headers=guest).json()["user"]["id"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        old_worker = pool.submit(client.post, "/v1/sandbox/tour", headers=guest)
        try:
            assert paused.wait(10), "Worker did not reach the permission mutation"
            with SessionLocal() as db:
                db.get(SandboxTourRecord, user_id).lease_until = dt.datetime.utcnow() - dt.timedelta(seconds=1)
                db.commit()
            tour = prepared(guest)
        finally:
            resume.set()
        assert old_worker.result(timeout=10).status_code == 409
    ledger = client.get(f"/v1/organizations/{tour['requester']['id']}/permission-requests", headers=guest).json()
    assert len(ledger["permissionRequests"]) == 2
