"""The operator-only seed command that publishes a reference node's fictional catalog."""
import pytest

import seed_reference_catalog
from models import MagicSession
from services.federation import FederationConfig, PeerSearchInput
from test_api import app, client, settings, SessionLocal
from test_sandbox_tour import guest  # noqa: F401

ORIGIN = "https://label.nodes.example.test"


@pytest.fixture
def reference_node(monkeypatch):
    monkeypatch.setattr(settings, "NODE_DEPLOYMENT_MODE", "public_sandbox")
    monkeypatch.setattr(settings, "SANDBOX_GUEST_ACCESS", True)
    monkeypatch.setattr(app.state, "federation_config", FederationConfig(True, ORIGIN))


def published(query):
    response = client.post("/v1/federation/catalog/search", json=PeerSearchInput(query=query, nonce="r" * 32).model_dump())
    assert response.status_code == 200, response.text
    return response.json()["payload"]["entries"]


def operator_sessions():
    with SessionLocal() as db:
        return db.query(MagicSession).filter_by(email="operator@example.com").count()


def test_operator_seed_publishes_once_and_leaves_no_session(reference_node, capsys):
    before = operator_sessions()
    assert seed_reference_catalog.main(["label", "--operator-email", "operator@example.com"]) == 0
    first = capsys.readouterr().out
    assert any(entry["organization"]["name"] == "Example Records · fictional" and entry["synthetic"]
               for entry in published("Example Records"))
    assert operator_sessions() == before
    assert seed_reference_catalog.main(["label", "--operator-email", "operator@example.com"]) == 0
    assert capsys.readouterr().out == first


def test_seed_refuses_an_address_that_is_not_a_node_operator(reference_node, capsys):
    assert seed_reference_catalog.main(["label", "--operator-email", "visitor@example.test"]) == 2
    assert "NODE_OPERATOR_EMAILS" in capsys.readouterr().err


def test_seed_refuses_a_reference_org_that_someone_else_shares(reference_node, capsys):
    from models import OrganizationMembershipRecord, OrganizationRecord, UserRecord
    assert seed_reference_catalog.main(["publisher", "--operator-email", "operator@example.com"]) == 0
    capsys.readouterr()
    with SessionLocal() as db:
        org = db.query(OrganizationRecord).filter_by(slug="connected-example-publisher").one()
        planted = UserRecord(email="planted-colleague@example.test", display_name="planted", role="member")
        db.add(planted); db.flush()
        db.add(OrganizationMembershipRecord(org_id=org.id, user_id=planted.id, role="admin"))
        db.commit()
    assert seed_reference_catalog.main(["publisher", "--operator-email", "operator@example.com"]) == 1
    assert "other members" in capsys.readouterr().err


def test_sandbox_guests_cannot_take_reference_slugs_or_add_real_addresses(guest):
    taken = client.post("/v1/organizations", headers=guest, json={"slug": "connected-example-label", "name": "Lookalike",
        "organization_type": "label", "default_territory": "US", "controlled_right_types": ["master"]})
    assert taken.status_code == 422 and "reserved" in taken.json()["detail"]
    own = client.post("/v1/organizations", headers=guest, json={"slug": f"guest-label-{__import__('uuid').uuid4().hex[:10]}",
        "name": "Guest label", "organization_type": "label", "default_territory": "US", "controlled_right_types": ["master"]})
    assert own.status_code in {200, 201}, own.text
    members = f"/v1/organizations/{own.json()['id']}/members"
    refused = client.post(members, headers=guest, json={"email": "operator@example.com", "role": "admin"})
    assert refused.status_code == 422 and "synthetic" in refused.json()["detail"]
    assert client.post(members, headers=guest, json={"email": "colleague-1@sandbox.invalid", "role": "member"}).status_code in {200, 201}
