"""An idempotency key identifies a retry; it never authorizes its caller."""
import uuid

import pytest

from test_api import client, _create_pending_composition_permission, _create_api_credential, _session_headers


@pytest.fixture
def settlement_case():
    prefix = f"settlement-access-{uuid.uuid4().hex[:8]}"
    setup = _create_pending_composition_permission(prefix)
    terms = {
        "currency": "USD", "minimum_commitment_minor": 1000, "royalty_rate_bps": 1000,
        "beneficiaries": [{"name": "Fictional Artist", "identifier": "synthetic:artist", "share_bps": 10000}],
        "confirm_immutable_terms": True,
    }
    url = f"/v1/permission-requests/{setup['permission']['id']}/settlement"
    created = client.post(url, headers=setup["rightsholder_headers"], json=terms)
    assert created.status_code == 201, created.text
    setup.update(settlement=created.json(), terms=terms, terms_url=url)
    return setup


@pytest.mark.parametrize("actor", ["unrelated_member", "unrelated_machine", "counterparty"])
@pytest.mark.parametrize("changed_payload", [False, True])
def test_entry_retry_authorizes_before_returning_or_comparing_cached_data(settlement_case, actor, changed_payload):
    setup = settlement_case
    url = f"/v1/settlements/{setup['settlement']['id']}/entries"
    payload = {"kind": "reserve", "amount_minor": 1000, "idempotency_key": "synthetic-reserve"}
    first = client.post(url, headers=setup["requester_headers"], json=payload)
    assert first.status_code == 201
    retry = client.post(url, headers=setup["requester_headers"], json=payload)
    assert retry.status_code == 201 and retry.json()["id"] == first.json()["id"]
    if actor == "counterparty":
        headers = setup["rightsholder_headers"]
    else:
        prefix = uuid.uuid4().hex[:8]
        headers = _session_headers(f"unrelated-{prefix}@example.test")
        if actor == "unrelated_machine":
            org = client.post("/v1/organizations", headers=headers, json={"slug": f"outsider-{prefix}", "name": "Fictional Outsider"}).json()
            credential = _create_api_credential(org["id"], headers, scopes=["settlements:write"], name="Synthetic outsider")
            headers = {"Authorization": f"Bearer {credential['token']}"}
    response = client.post(url, headers=headers, json={**payload, "amount_minor": 1001 if changed_payload else 1000})
    assert response.status_code == 403, response.text
    assert first.json()["id"] not in response.text
    after = client.get(setup["terms_url"], headers=setup["requester_headers"]).json()
    assert len(after["entries"]) == 1
    assert after["totals"]["reserveMinor"] == 1000


def test_duplicate_terms_cannot_disclose_settlement_state_to_an_outsider(settlement_case):
    headers = _session_headers(f"outsider-{uuid.uuid4().hex[:8]}@example.test")
    response = client.post(settlement_case["terms_url"], headers=headers, json=settlement_case["terms"])
    assert response.status_code == 403, response.text
