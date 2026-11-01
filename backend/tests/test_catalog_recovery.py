"""Recover the original CSV batch while preserving explicit review and history."""
from concurrent.futures import ThreadPoolExecutor
from test_catalog_assignments import catalog, upload, commit, resolve
from test_api import client, _session_headers, SessionLocal
from models import CatalogImportRowRecord, AuditEventRecord


def refresh(root, headers, batch):
    return client.post(f"{root}/imports/{batch['id']}/refresh", headers=headers,
        json={"expected_preview_digest": batch['previewDigest']})


def test_stale_exact_file_recovers_and_old_preview_cannot_commit():
    root, headers, _ = catalog()
    first = upload(root, headers, 'artist-a', 'First fictional title')
    other = upload(root, headers, 'artist-a', 'Other fictional title')
    assert commit(root, headers, other).status_code == 200
    stale = commit(root, headers, first)
    assert stale.status_code == 409 and 'Refresh preview' in stale.text
    assert upload(root, headers, 'artist-a', 'First fictional title')['id'] == first['id']
    renewed = refresh(root, headers, first)
    assert renewed.status_code == 200, renewed.text
    renewed = renewed.json()
    assert renewed['id'] == first['id'] and renewed['fileSha256'] == first['fileSha256']
    assert renewed['rows'][0]['status'] == 'conflict'
    resolve(root, headers, renewed)
    assert commit(root, headers, first).status_code == 409
    assert commit(root, headers, renewed).status_code == 200
    assert commit(root, headers, renewed).status_code == 200  # response-loss retry
    assert len(client.get(root + '/assets?include_history=true', headers=headers).json()['assets']) == 2
    assert refresh(root, headers, renewed).status_code == 409


def test_missing_client_can_be_added_then_original_preview_refreshed():
    root, headers, _ = catalog()
    batch = upload(root, headers, 'new-client')
    assert batch['rows'][0]['status'] == 'invalid'
    added = client.post(root + '/clients', headers=headers, json={'name':'Fictional new artist', 'external_reference':'new-client'})
    assert added.status_code == 201
    renewed = refresh(root, headers, batch).json()
    assert renewed['rows'][0]['status'] == 'ready'
    assert commit(root, headers, renewed).status_code == 200


def test_assignment_change_after_resolution_requires_new_review_and_keeps_audit():
    root, headers, _ = catalog()
    assert commit(root, headers, upload(root, headers, 'artist-a')).status_code == 200
    correction = upload(root, headers, 'artist-b')
    resolve(root, headers, correction)
    asset = client.get(root + '/assets', headers=headers).json()['assets'][0]
    assert client.post(root + f"/assets/{asset['id']}/assignment", headers=headers,
        json={'client_id':None, 'reason':'Fictional administration ended'}).status_code == 201
    assert commit(root, headers, correction).status_code == 409
    renewed = refresh(root, headers, correction).json()
    assert renewed['rows'][0]['existingAsset']['id'] == asset['id']
    assert renewed['rows'][0]['existingAsset']['client'] is None
    assert renewed['rows'][0]['resolution'] is None
    assert renewed['rows'][0]['status'] == 'conflict'
    assert commit(root, headers, renewed).status_code == 409
    with SessionLocal() as db:
        assert db.query(AuditEventRecord).filter_by(resource_id=correction['rows'][0]['id'], action='catalog.import.conflict.new_version').count() == 1
    resolve(root, headers, renewed)
    assert commit(root, headers, renewed).status_code == 200


def test_refreshed_resolution_rejects_the_old_review_digest():
    root, headers, _ = catalog()
    assert commit(root, headers, upload(root, headers, 'artist-a')).status_code == 200
    correction = upload(root, headers, 'artist-b')
    old_digest = correction['previewDigest']
    resolve(root, headers, correction)
    assert refresh(root, headers, {**correction, 'previewDigest':old_digest}).status_code == 409
    renewed = refresh(root, headers, correction).json()
    response = client.post(root + f"/imports/{correction['id']}/rows/{correction['rows'][0]['id']}/resolution",
        headers=headers, json={'expected_preview_digest':correction['previewDigest'], 'resolution':'new_version', 'note':'Stale decision'})
    assert response.status_code == 409
    assert renewed['rows'][0]['status'] == 'conflict'


def test_concurrent_commits_create_one_catalog_version():
    root, headers, _ = catalog()
    batch = upload(root, headers, 'artist-a')
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: commit(root, headers, batch), range(2)))
    assert [response.status_code for response in responses] == [200,200]
    assert len(client.get(root + '/assets?include_history=true', headers=headers).json()['assets']) == 1


def test_refresh_enforces_organization_scope_and_required_review_digest():
    root, headers, _ = catalog()
    batch = upload(root, headers, 'artist-a')
    assert refresh(root, {}, batch).status_code == 401
    assert refresh(root, _session_headers('unrelated-import-reviewer@example.test'), batch).status_code == 403
    other, _, _ = catalog()
    assert refresh(other, headers, batch).status_code == 403
    assert client.post(root + f"/imports/{batch['id']}/commit", headers=headers, json={'confirm_import':True}).status_code == 422


def test_pre_upgrade_pending_rows_require_refresh():
    root, headers, _ = catalog()
    batch = upload(root, headers, 'artist-a')
    with SessionLocal() as db:
        db.get(CatalogImportRowRecord, batch['rows'][0]['id']).review_basis = None
        db.commit()
    batch = client.get(root + f"/imports/{batch['id']}", headers=headers).json()
    assert commit(root, headers, batch).status_code == 409
    renewed = refresh(root, headers, batch).json()
    assert commit(root, headers, renewed).status_code == 200


def test_stale_second_row_rolls_back_whole_import_and_duplicate_rows_are_safe():
    root, headers, _ = catalog()
    data = 'item_type,title,isrc\nrecording,New fictional song,ZZDEM0000002\nrecording,Original fictional song,ZZDEM0000001\nrecording,Original fictional song,ZZDEM0000001\n'
    batch = client.post(root + '/imports/csv', headers=headers, files={'file':('fictional.csv',data,'text/csv')}).json()
    assert batch['rows'][2]['status'] == 'duplicate_batch'
    assert commit(root, headers, upload(root, headers, None, 'Concurrent fictional title')).status_code == 200
    assert commit(root, headers, batch).status_code == 409
    assert len(client.get(root + '/assets', headers=headers).json()['assets']) == 1
    renewed = refresh(root, headers, batch).json()
    row = renewed['rows'][1]
    result = client.post(root + f"/imports/{renewed['id']}/rows/{row['id']}/resolution", headers=headers,
        json={'expected_preview_digest':renewed['previewDigest'], 'resolution':'new_version', 'note':'Reviewed correction'})
    assert result.status_code == 200
    renewed['previewDigest'] = result.json()['previewDigest']
    assert commit(root, headers, renewed).status_code == 200
    assert len(client.get(root + '/assets', headers=headers).json()['assets']) == 2


def test_historical_assignment_and_blank_decision_reasons_are_rejected():
    root, headers, clients = catalog()
    assert commit(root, headers, upload(root, headers, 'artist-a')).status_code == 200
    original = client.get(root + '/assets', headers=headers).json()['assets'][0]
    assert client.post(root + f"/assets/{original['id']}/assignment", headers=headers,
        json={'client_id':clients['artist-b']['id'], 'reason':'   '}).status_code == 422
    correction = upload(root, headers, 'artist-b')
    result = client.post(root + f"/imports/{correction['id']}/rows/{correction['rows'][0]['id']}/resolution", headers=headers,
        json={'expected_preview_digest':correction['previewDigest'], 'resolution':'skip', 'note':'   '})
    assert result.status_code == 422
    resolve(root, headers, correction)
    assert commit(root, headers, correction).status_code == 200
    result = client.post(root + f"/assets/{original['id']}/assignment", headers=headers,
        json={'client_id':clients['artist-b']['id'], 'reason':'Obsolete screen'})
    assert result.status_code == 409 and 'newer catalog version' in result.text
