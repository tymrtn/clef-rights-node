"""Authority withdrawal stops new grants while preserving separately issued licenses."""
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from models import AuditEventRecord, AuthorityClaimRecord, OrganizationMembershipRecord
from test_api import client, SessionLocal, _session_headers, _create_api_credential
from test_sandbox_tour import guest, prepared, approval
from test_federation import connected, preview_and_publish, public_search


def withdrawal(guest, side):
    root = f"/v1/organizations/{side['orgId']}/authority-claims/{side['authority']['id']}"
    preview = client.get(root + '/withdrawal-preview', headers=guest)
    assert preview.status_code == 200, preview.text
    return root, {'expected_digest': preview.json()['expectedDigest'], 'reason': 'Fictional mandate ended', 'confirm_withdrawal': True}


def test_withdrawn_authority_blocks_new_requests_and_pending_approval(guest):
    side = prepared(guest)['sides'][0]
    root, request = withdrawal(guest, side)
    response = client.post(root + '/withdraw', headers=guest, json=request)
    assert response.status_code == 200 and response.json()['status'] == 'revoked'
    assert response.json()['pendingRequests'] == 1
    assert client.post('/v1/permission-requests', headers=guest, json=side['request']).status_code == 409
    assert client.post(f"/v1/permission-requests/{side['permissionId']}/decide", headers=guest, json=approval()).status_code == 409
    directory = client.get('/v1/directory/authority-claims', headers=guest, params={'work_key': side['workKey']}).json()
    assert not directory['claims']
    assert client.post(f"/v1/authority-claims/{side['authority']['id']}/verify", headers=guest, json={'evidence_note':'Attempted reactivation'}).status_code == 409


def test_existing_signed_grant_retains_its_status_for_separate_review(guest):
    side = prepared(guest)['sides'][0]
    approved = client.post(f"/v1/permission-requests/{side['permissionId']}/decide", headers=guest, json=approval()).json()
    root, request = withdrawal(guest, side)
    result = client.post(root + '/withdraw', headers=guest, json=request)
    assert result.status_code == 200 and result.json()['approvedGrants'] == 1
    current = client.get(f"/v1/permission-requests/{side['permissionId']}", headers=guest).json()
    assert current['status'] == 'approved' and current['lifecycleRecords'] == []
    assert client.post('/v1/receipts/verify', json={'receipt': approved['receipt']}).json()['valid'] is True


def test_withdrawal_is_scoped_and_human_administered(guest):
    side = prepared(guest)['sides'][0]
    root, request = withdrawal(guest, side)
    stranger = _session_headers(f"stranger-{uuid.uuid4().hex}@example.test")
    credential = _create_api_credential(side['orgId'], guest, scopes=['permissions:lifecycle'])
    for headers, code in [({},401), (stranger,403), ({'Authorization': f"Bearer {credential['token']}"},401)]:
        assert client.get(root + '/withdrawal-preview', headers=headers).status_code == code
        assert client.post(root + '/withdraw', headers=headers, json=request).status_code == code
    user = client.get('/v1/session', headers=guest).json()['user']['id']
    with SessionLocal() as db:
        db.query(OrganizationMembershipRecord).filter_by(org_id=side['orgId'], user_id=user).update({'role':'member'})
        db.commit()
    assert client.post(root + '/withdraw', headers=guest, json=request).status_code == 403


def test_changed_authority_requires_another_preview(guest):
    side = prepared(guest)['sides'][0]
    root, request = withdrawal(guest, side)
    with SessionLocal() as db:
        claim = db.get(AuthorityClaimRecord, side['authority']['id'])
        claim.evidence = {**claim.evidence, 'reference': 'updated-fixture-mandate'}
        db.commit()
    assert client.post(root + '/withdraw', headers=guest, json=request).status_code == 409
    assert client.post(root + '/withdraw', headers=guest, json={**request, 'reason':'  '}).status_code == 422
    assert client.post(root + '/withdraw', headers=guest, json={**request, 'confirm_withdrawal':False}).status_code == 422


def test_concurrent_exact_retries_record_one_withdrawal_and_preserve_review_actor(guest):
    side = prepared(guest)['sides'][0]
    root, request = withdrawal(guest, side)
    with SessionLocal() as db:
        claim = db.get(AuthorityClaimRecord, side['authority']['id'])
        original_review = (claim.reviewed_by_user_id, claim.reviewed_at, claim.verified_by_user_id, claim.verified_at)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(root + '/withdraw', headers=guest, json=request), range(2)))
    assert [r.status_code for r in results] == [200,200]
    with SessionLocal() as db:
        assert db.query(AuditEventRecord).filter_by(action='authority_claim.withdrawn',resource_id=side['authority']['id']).count() == 1
        claim = db.get(AuthorityClaimRecord, side['authority']['id'])
        assert (claim.reviewed_by_user_id, claim.reviewed_at, claim.verified_by_user_id, claim.verified_at) == original_review
    assert client.post(root + '/withdraw', headers=guest, json={**request, 'reason':'Different action'}).status_code == 409


def test_authority_withdrawal_removes_the_published_catalog_from_federation(connected):
    publication, _, _ = preview_and_publish(connected)
    headers, _, side, _ = connected
    assert any(row['publicationId'] == publication['id'] for row in public_search()[1]['payload']['entries'])
    root, request = withdrawal(headers, side)
    assert client.post(root + '/withdraw', headers=headers, json=request).status_code == 200
    assert not any(row['publicationId'] == publication['id'] for row in public_search()[1]['payload']['entries'])
