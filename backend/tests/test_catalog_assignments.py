"""Client assignment changes in CSV imports require visible human resolution."""
import csv
import io
import uuid
import pytest
from test_api import client, _session_headers


def catalog():
    suffix = uuid.uuid4().hex[:10]
    headers = _session_headers(f"catalog-{suffix}@example.test")
    org = client.post('/v1/organizations', headers=headers, json={
        'slug': f'catalog-{suffix}', 'name': 'Fictional label', 'organization_type': 'label',
        'controlled_right_types': ['master']}).json()
    root = f"/v1/organizations/{org['id']}/catalog"
    clients = {}
    for reference in ['artist-a', 'artist-b']:
        result = client.post(root + '/clients', headers=headers, json={'name':reference, 'external_reference':reference})
        assert result.status_code == 201
        clients[reference] = result.json()
    return root, headers, clients


def upload(root, headers, reference, title='Fictional recording'):
    row = {'item_type':'recording', 'title':title, 'isrc':'ZZDEM0000001'}
    if reference is not None:
        row['client_reference'] = reference
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(row))
    writer.writeheader(); writer.writerow(row)
    response = client.post(root + '/imports/csv', headers=headers,
                           files={'file': ('fictional.csv', output.getvalue(), 'text/csv')})
    assert response.status_code == 201, response.text
    return response.json()


def commit(root, headers, batch):
    return client.post(root + f"/imports/{batch['id']}/commit", headers=headers, json={'confirm_import':True, 'expected_preview_digest':batch['previewDigest']})


def resolve(root, headers, batch):
    response = client.post(root + f"/imports/{batch['id']}/rows/{batch['rows'][0]['id']}/resolution",
        headers=headers, json={'expected_preview_digest':batch['previewDigest'], 'resolution':'new_version', 'note':'Reviewed fictional catalog correction'})
    assert response.status_code == 200, response.text
    batch["previewDigest"] = response.json()["previewDigest"]


@pytest.mark.parametrize('original,replacement', [('artist-a','artist-b'), ('artist-a',''), ('','artist-b')])
def test_client_only_csv_correction_requires_resolution(original, replacement):
    root, headers, clients = catalog()
    assert commit(root, headers, upload(root, headers, original)).status_code == 200
    correction = upload(root, headers, replacement)
    assert correction['rows'][0]['status'] == 'conflict'
    assert commit(root, headers, correction).status_code == 409
    resolve(root, headers, correction)
    assert commit(root, headers, correction).status_code == 200
    latest = client.get(root + '/assets', headers=headers).json()['assets'][0]
    assert latest['version'] == 2
    assert latest['client'] == (clients[replacement] if replacement else None)
    history = client.get(root + '/assets?include_history=true', headers=headers).json()['assets']
    assert len(history) == 2
    old = next(row for row in history if row['version'] == 1)
    assert old['client'] == (clients[original] if original else None)


@pytest.mark.parametrize('change_title', [False, True])
def test_omitted_client_column_preserves_existing_assignment(change_title):
    root, headers, clients = catalog()
    assert commit(root, headers, upload(root, headers, 'artist-a')).status_code == 200
    correction = upload(root, headers, None, 'Corrected fictional recording' if change_title else 'Fictional recording')
    assert correction['rows'][0]['status'] == ('conflict' if change_title else 'duplicate_existing')
    if change_title:
        resolve(root, headers, correction)
    assert commit(root, headers, correction).status_code == 200
    latest = client.get(root + '/assets', headers=headers).json()['assets'][0]
    assert latest['client'] == clients['artist-a']
