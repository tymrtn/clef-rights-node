"""Public disclosure, exact commitments and reviewed copy erasure regressions."""
import datetime as dt
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import uuid

import pytest
from main import SessionLocal, receipt_signer
from models import (ReceiptDisclosureRecord, PermissionReceiptRecord, PermissionRequestRecord,
                    CatalogClientRecord, OrganizationPrivacyRecord)
from services.privacy import PUBLIC_FIELDS, private_commitment, verify_commitment
from test_api import client, _create_pending_composition_permission, _session_headers, _create_api_credential


@pytest.fixture
def setup():
    return _create_pending_composition_permission('privacy-'+uuid.uuid4().hex[:10])


def base(s, party='rightsholder'):
    return f"/v1/organizations/{s[party+'_org']['id']}/privacy"


def headers(s, party='rightsholder'):
    return s[party+'_headers']


def settings(s, party='rightsholder', **changes):
    old = client.get(base(s,party),headers=headers(s,party)).json()['settings']
    body = dict(publish_public_receipts=old['publishPublicReceipts'], receipt_retention_days=old['receiptRetentionDays'],
                legal_hold=old['legalHold'], expected_version=old['version'])
    result=client.put(base(s,party),headers=headers(s,party),json={**body,**changes})
    assert result.status_code==200,result.text
    return result.json()


def grant(s, publish=True):
    if publish:
        for p in ['rightsholder','requester']: settings(s,p,publish_public_receipts=True)
    result=client.post(f"/v1/permission-requests/{s['permission']['id']}/decide",headers=headers(s),json={'decision':'approved','note':'private contact@example.com; price $1987'})
    assert result.status_code==200,result.text
    return result.json()['receipt']


def disclosure(s, receipt):
    r=client.get(f"/v1/receipts/{receipt['payload']['receiptId']}/disclosure",headers=headers(s))
    assert r.status_code==200,r.text
    return r.json()


def erase_case(s, receipt, party='rightsholder'):
    r=client.post(base(s,party)+'/requests',headers=headers(s,party),json={'kind':'receipt_copy','resource_id':receipt['payload']['receiptId']})
    assert r.status_code==201,r.text
    return r.json()


def approve(s, case, party='rightsholder'):
    return client.post(base(s,party)+f"/requests/{case['id']}/approve",headers=headers(s,party),json={})


def execute(s, case):
    return client.post(base(s)+f"/requests/{case['id']}/execute",headers=headers(s),json={'confirm_request_id':case['id']})


def test_public_allowlist_exact_private_commitment_and_no_sensitive_fields(setup):
    private=grant(setup); info=disclosure(setup,private)
    public=client.get(info['publicUrl'])
    assert public.status_code==200
    assert public.headers['cache-control']=='no-store'
    public=public.json()
    assert set(public['payload'])==set(PUBLIC_FIELDS)
    encoded=json.dumps(public)
    for marker in ['contact@example.com','1987',setup['rightsholder_org']['id'],setup['requester_org']['id'],setup['permission']['id'],'Example Artist','Example Publisher','Example Licensee','mlc:']:
        assert marker not in encoded
    assert 'commitmentNonce' not in encoded
    nonce=info['commitmentOpening']['nonce']
    assert verify_commitment(public,private,nonce)
    assert private_commitment(private,nonce)==public['payload']['privateEvidenceCommitment']['value']
    assert client.post('/v1/receipts/verify',json={'receipt':public}).json()['valid']
    assert client.post('/v1/receipts/commitment/verify',json={'public_receipt':public,'private_receipt':private,'nonce':nonce}).json()['valid']
    assert client.get('/v1/receipts/'+private['payload']['receiptId']).status_code==401
    assert client.get('/v1/receipts/'+private['payload']['receiptId']+'/disclosure').status_code==401
    assert public['payload']['receiptId']!=private['payload']['receiptId']


@pytest.mark.parametrize('tamper',['nonce','private','public','transparency','algorithm'])
def test_commitment_tampering_is_rejected(setup,tamper):
    private=grant(setup);info=disclosure(setup,private);public=client.get(info['publicUrl']).json();nonce=info['commitmentOpening']['nonce']
    if tamper=='nonce':nonce='0'*64
    elif tamper=='private':private['payload']['decision']['note']='changed'
    elif tamper=='public':public['payload']['statusAtIssue']='paid'
    elif tamper=='transparency':public['transparency']['payloadHash']='0'*64
    else:public['proof']['algorithm']='none'
    assert not verify_commitment(public,private,nonce)


@pytest.mark.parametrize('consenting',['neither','authority','requester','both'])
def test_publication_requires_both_parties_at_issuance(setup,consenting):
    for p in ['rightsholder','requester']:
        if consenting=='both' or (consenting=='authority' and p=='rightsholder') or consenting==p:
            settings(setup,p,publish_public_receipts=True)
    receipt=grant(setup,publish=False); info=disclosure(setup,receipt)
    assert info['published']==(consenting=='both')
    assert receipt['payload']['disclosure']['publicationAuthorized']==(consenting=='both')
    if consenting!='both':
        for p in ['rightsholder','requester']:settings(setup,p,publish_public_receipts=True)
        assert not disclosure(setup,receipt)['published']
        assert client.get('/v1/public/receipts/'+info['publicReceiptId']).status_code==404


def test_withdrawal_preserves_private_original_and_public_chain(setup):
    receipt=grant(setup);info=disclosure(setup,receipt);public=client.get(info['publicUrl']).json()
    chain=client.get('/v1/public/transparency/entries').json()
    for _ in range(2):
        assert client.post(base(setup,'requester')+'/receipts/'+receipt['payload']['receiptId']+'/withdraw-public',headers=headers(setup,'requester'),json={}).json()=={'withdrawn':True}
    assert client.get(info['publicUrl']).status_code==404
    assert client.get(info['publicUrl']+'/status').status_code==404
    assert client.get('/v1/public/transparency/entries').json()==chain
    assert client.get('/v1/receipts/'+receipt['payload']['receiptId'],headers=headers(setup)).json()==receipt
    assert receipt_signer.verify_receipt(public).valid


def test_lifecycle_public_summary_and_current_status(setup):
    private=grant(setup);info=disclosure(setup,private)
    r=client.post(f"/v1/permission-requests/{setup['permission']['id']}/lifecycle-events",headers=headers(setup),json={'event_type':'revocation','reason':'Private agreement with confidential reason'})
    assert r.status_code==200,r.text
    lifecycle=r.json()['receipt']; public=client.get(disclosure(setup,lifecycle)['publicUrl']).json()
    assert public['payload']['statusAtIssue']=='revoked'
    assert 'confidential' not in json.dumps(public)
    assert client.get(info['publicUrl']+'/status').json()['currentStatus']=='revoked'
    assert client.get(info['publicUrl']).json()['payload']['statusAtIssue']=='permissioned'


def test_copy_erasure_requires_both_approvals_preserves_signatures_and_reports_residuals(setup):
    receipt=grant(setup);info=disclosure(setup,receipt);public=client.get(info['publicUrl']).json();case=erase_case(setup,receipt)
    assert erase_case(setup,receipt,'requester')['id']==case['id']
    assert execute(setup,case).status_code==409
    assert approve(setup,case).status_code==200
    assert approve(setup,case).status_code==200
    assert execute(setup,case).status_code==409
    assert approve(setup,case,'requester').status_code==200
    preview=client.get(base(setup)+f"/requests/{case['id']}/preview",headers=headers(setup)).json()
    assert preview['canExecute'] and len(preview['retained'])>=5
    r=execute(setup,case); assert r.status_code==200,r.text
    assert r.json()['request']['status']=='completed'
    assert execute(setup,case).json()['erased']==[]
    assert client.get('/v1/receipts/'+receipt['payload']['receiptId'],headers=headers(setup)).status_code==410
    assert client.post('/v1/receipts/verify',json={'receipt':receipt}).json()['valid']
    assert client.get(info['publicUrl']).json()==public
    assert disclosure(setup,receipt)['commitmentOpening'] is None
    assert disclosure(setup,receipt)['privateCopyErased']
    with SessionLocal() as db:
        assert db.get(PermissionReceiptRecord,receipt['payload']['receiptId']).payload=={}
        assert db.get(PermissionRequestRecord,setup['permission']['id']).status=='approved'


@pytest.mark.parametrize('block',['hold','retention','retention_extended'])
def test_erasure_rechecks_holds_and_retention_after_approval(setup,block):
    if block=='retention':settings(setup,receipt_retention_days=30)
    receipt=grant(setup);case=erase_case(setup,receipt)
    approve(setup,case);approve(setup,case,'requester')
    if block=='hold':settings(setup,'requester',legal_hold=True)
    elif block=='retention_extended':settings(setup,'requester',receipt_retention_days=60)
    elif block=='retention':settings(setup,receipt_retention_days=None) # issuance minimum survives
    assert execute(setup,case).status_code==409
    assert client.get('/v1/receipts/'+receipt['payload']['receiptId'],headers=headers(setup)).status_code==200


def test_longest_party_retention_recorded_before_signature(setup):
    settings(setup,receipt_retention_days=7);settings(setup,'requester',receipt_retention_days=90)
    private=grant(setup);until=dt.datetime.fromisoformat(private['payload']['disclosure']['retainUntil'].rstrip('Z'))
    assert 89 < (until-dt.datetime.utcnow()).total_seconds()/86400 <=90


def test_legacy_receipt_gets_private_erasure_tracking_without_resigning(setup):
    receipt=grant(setup,publish=False);rid=receipt['payload']['receiptId']
    with SessionLocal() as db:
        db.delete(db.get(ReceiptDisclosureRecord,rid));db.commit()
    assert disclosure(setup,receipt)['publicUrl'] is None
    for p in ['rightsholder','requester']:settings(setup,p,publish_public_receipts=True)
    case=erase_case(setup,receipt)
    assert client.get('/v1/receipts/'+rid,headers=headers(setup)).json()==receipt
    assert not disclosure(setup,receipt)['published']
    approve(setup,case);approve(setup,case,'requester');assert execute(setup,case).status_code==200


def test_privacy_admin_access_and_no_cross_tenant_resource_probing(setup):
    receipt=grant(setup);case=erase_case(setup,receipt)
    stranger=_session_headers('stranger-'+uuid.uuid4().hex+'@example.com')
    org=client.post('/v1/organizations',headers=stranger,json={'slug':uuid.uuid4().hex,'name':'Other organization'}).json()['id']
    for suffix in ['', '/export?resource=receipts','/requests',f"/requests/{case['id']}/preview"]:
        assert client.get(base(setup)+suffix).status_code==401
        assert client.get(base(setup)+suffix,headers=stranger).status_code==403
    assert client.get(f'/v1/organizations/{org}/privacy/requests/{case["id"]}/preview',headers=stranger).status_code==404
    assert client.post(f'/v1/organizations/{org}/privacy/requests',headers=stranger,json={'kind':'receipt_copy','resource_id':receipt['payload']['receiptId']}).status_code==404
    token=_create_api_credential(setup['rightsholder_org']['id'],headers(setup),scopes=['permissions:read'])
    auth={'Authorization':'Bearer '+token['token']}
    assert client.get(base(setup),headers=auth).status_code==401
    assert client.get('/v1/receipts/'+receipt['payload']['receiptId']+'/disclosure',headers=auth).status_code==200


def test_export_is_scoped_and_paginated_and_excludes_credentials(setup):
    grant(setup)
    other=_create_pending_composition_permission('export-other-'+uuid.uuid4().hex[:8]); other_receipt=grant(other)
    response=client.get(base(setup)+'/export?resource=receipts&limit=1',headers=headers(setup))
    assert response.status_code==200,response.text
    data=response.json(); assert len(data['records'])==1 and data['nextCursor'] is None
    assert other_receipt['payload']['receiptId'] not in response.text
    assert response.headers['cache-control']=='private, no-store'
    assert client.get(base(setup)+'/export?resource=credentials',headers=headers(setup)).status_code==422
    for i in range(3):
        r=client.post(f"/v1/organizations/{setup['rightsholder_org']['id']}/catalog/clients",headers=headers(setup),json={'name':f'Client {i}','external_reference':f'client-{i}','contact_email':f'person{i}@example.com'})
        assert r.status_code==201,r.text
    seen=[];cursor=''
    while True:
        page=client.get(base(setup)+'/export?resource=clients&limit=1'+('&cursor='+cursor if cursor else ''),headers=headers(setup)).json()
        seen.extend(r['id'] for r in page['records']);cursor=page['nextCursor']
        if not cursor:break
    assert len(seen)==len(set(seen))==3


def test_client_contact_erasure_is_explicit_scoped_and_detects_changes(setup):
    c=client.post(f"/v1/organizations/{setup['rightsholder_org']['id']}/catalog/clients",headers=headers(setup),json={'name':'Keep client name','external_reference':'contact','contact_email':'erase@example.com'}).json()
    r=client.post(base(setup)+'/requests',headers=headers(setup),json={'kind':'client_contact_email','resource_id':c['id']})
    assert r.status_code==201,r.text
    case=r.json();approve(setup,case)
    with SessionLocal() as db:
        db.get(CatalogClientRecord,c['id']).contact_email='changed@example.com';db.commit()
    assert execute(setup,case).status_code==409
    case=client.post(base(setup)+'/requests',headers=headers(setup),json={'kind':'client_contact_email','resource_id':c['id']}).json()
    approve(setup,case);assert execute(setup,case).status_code==200
    with SessionLocal() as db:
        assert db.get(CatalogClientRecord,c['id']).contact_email is None
        assert db.get(CatalogClientRecord,c['id']).name=='Keep client name'


def test_settings_conflict_and_strict_input_validation(setup):
    settings(setup)
    payload={'publish_public_receipts':True,'receipt_retention_days':None,'legal_hold':False,'expected_version':0}
    assert client.put(base(setup),headers=headers(setup),json=payload).status_code==409
    assert client.put(base(setup),headers=headers(setup),json={**payload,'receipt_retention_days':0}).status_code==422
    assert client.put(base(setup),headers=headers(setup),json={**payload,'publish_public_receipts':'false'}).status_code==422


def test_audit_export_does_not_grow_from_its_own_page_requests(setup):
    grant(setup)
    cursor = None
    seen = []
    for _ in range(100):
        result = client.get(base(setup)+'/export', headers=headers(setup),
                            params={'resource': 'audit', 'limit': 1, **({'cursor': cursor} if cursor else {})})
        assert result.status_code == 200, result.text
        page = result.json()
        assert all(r['action'] != 'privacy.export.created' for r in page['records'])
        seen.extend(r['id'] for r in page['records'])
        cursor = page['nextCursor']
        if not cursor:
            break
    else:
        pytest.fail('Audit pagination did not terminate')
    assert seen and len(seen) == len(set(seen))


@pytest.mark.parametrize("days_from_today,expected", [(-1, "expired"), (0, "approved"), (1, "approved")])
def test_public_status_accounts_for_expiry_before_worker_runs(setup, days_from_today, expected):
    receipt = grant(setup)
    info = disclosure(setup, receipt)
    with SessionLocal() as db:
        row = db.get(PermissionRequestRecord, setup['permission']['id'])
        row.term_end = (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=days_from_today)).isoformat()
        db.commit()
    status = client.get(info['publicUrl']+'/status').json()
    assert status['currentStatus'] == expected
    assert status['recordedPermissionStatus'] == 'approved'
    assert client.get(info['publicUrl']).json()['payload']['statusAtIssue'] == 'permissioned'


def test_public_settlement_freshness_survives_private_erasure(setup):
    pid = setup['permission']['id']
    created = client.post(f'/v1/permission-requests/{pid}/settlement', headers=headers(setup), json={
        'currency': 'USD', 'minimum_commitment_minor': 198700, 'royalty_rate_bps': 0,
        'beneficiaries': [{'name': 'Private Artist', 'identifier': 'secret:beneficiary', 'share_bps': 10000}],
        'confirm_immutable_terms': True})
    assert created.status_code == 201, created.text
    settlement = created.json()
    grant(setup)
    def entry(kind, amount, key, beneficiary=None):
        result = client.post(f"/v1/settlements/{settlement['id']}/entries", headers=headers(setup), json={
            'kind': kind, 'amount_minor': amount, 'idempotency_key': key,
            'external_reference': key, 'evidence': {'private': 'bank statement'}, 'beneficiary_id': beneficiary})
        assert result.status_code == 201, result.text
    entry('payment_received', 198700, 'payment')
    entry('payout', 198700, 'payout', settlement['beneficiaries'][0]['id'])
    result = client.post(f"/v1/settlements/{settlement['id']}/reconciliations", headers=headers(setup), json={'idempotency_key':'paid'})
    assert result.status_code == 201, result.text
    private = client.get('/v1/receipts/'+result.json()['receiptId'], headers=headers(setup)).json()
    info = disclosure(setup, private)
    public = client.get(info['publicUrl']).json()
    assert public['payload']['statusAtIssue'] == 'paid'
    for marker in ['198700', 'Private Artist', 'secret:beneficiary', settlement['id'], 'bank statement']:
        assert marker not in json.dumps(public)
    assert verify_commitment(public, private, info['commitmentOpening']['nonce'])
    status = client.get(info['publicUrl']+'/status').json()
    assert status['reconciliationCurrent'] and status['settlementAssertion'] == 'paid'
    token = _create_api_credential(setup['rightsholder_org']['id'], headers(setup), scopes=['permissions:read'])
    assert client.get('/v1/receipts/'+result.json()['receiptId']+'/disclosure', headers={'Authorization':'Bearer '+token['token']}).status_code == 403
    case = erase_case(setup, private)
    approve(setup, case); approve(setup, case, 'requester')
    assert execute(setup, case).status_code == 200
    entry('payment_reversal', 100, 'reversal')
    status = client.get(info['publicUrl']+'/status').json()
    assert status['privateCopyErased'] and status['currentStatus'] == 'approved'
    assert not status['reconciliationCurrent'] and status['settlementAssertion'] == 'provisional'
    assert client.get(info['publicUrl']).json() == public


def test_public_signing_failure_rolls_back_private_receipt_and_approval(setup, monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    for party in ['rightsholder', 'requester']:
        settings(setup, party, publish_public_receipts=True)
    original_sign = receipt_signer.sign_receipt
    def fail_public(**kwargs):
        if kwargs['payload'].get('schemaVersion') == 'clef.public-receipt.v1':
            raise RuntimeError('Public signing failed')
        return original_sign(**kwargs)
    monkeypatch.setattr(receipt_signer, 'sign_receipt', fail_public)
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/v1/permission-requests/{setup['permission']['id']}/decide", headers=headers(setup), json={'decision':'approved', 'note':'Approved with private terms'})
    assert response.status_code == 500
    with SessionLocal() as db:
        assert db.get(PermissionRequestRecord, setup['permission']['id']).status == 'pending'
        assert db.query(PermissionReceiptRecord).filter_by(permission_request_id=setup['permission']['id']).count() == 0
        assert db.query(ReceiptDisclosureRecord).filter_by(authority_org_id=setup['rightsholder_org']['id']).count() == 0


def test_concurrent_public_issuance_uses_one_consistent_hash_chain():
    setups = [_create_pending_composition_permission('concurrent-public-'+uuid.uuid4().hex[:8]) for _ in range(4)]
    for s in setups:
        for party in ['rightsholder', 'requester']:
            settings(s, party, publish_public_receipts=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda s: grant(s, publish=False), setups))
    summaries = [client.get(disclosure(s, r)['publicUrl']).json() for s, r in zip(setups, receipts)]
    entries = sorted((r['transparency'] for r in summaries), key=lambda t:t['sequence'])
    assert len({entry['sequence'] for entry in entries}) == 4
    for prior, entry in zip(entries, entries[1:]):
        assert entry['sequence'] == prior['sequence'] + 1
        assert entry['previousEntryHash'] == prior['entryHash']


@pytest.mark.parametrize('part', ['payload', 'disclosure', 'commitment', 'binding'])
def test_commitment_verifier_rejects_signed_malformed_or_unbound_statements(setup, part):
    private = grant(setup); info = disclosure(setup, private)
    public = client.get(info['publicUrl']).json(); nonce = info['commitmentOpening']['nonce']
    target = private if part in {'payload', 'disclosure', 'binding'} else public
    payload = deepcopy(target['payload'])
    if part == 'payload': payload = ['unexpected array']
    elif part == 'disclosure': payload['disclosure'] = ['unexpected array']
    elif part == 'binding': payload['disclosure']['publicReceiptId'] = str(uuid.uuid4())
    else: payload['privateEvidenceCommitment'] = ['unexpected array']
    replacement = receipt_signer.sign_receipt(payload=payload, transparency_sequence=1, previous_entry_hash=None)
    if target is private: private = replacement
    else: public = replacement
    assert not verify_commitment(public, private, nonce)
