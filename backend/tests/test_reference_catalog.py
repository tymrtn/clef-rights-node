"""The operator-only seed command that publishes a reference node's fictional catalog."""
import pytest

import seed_reference_catalog
from models import MagicSession
from services.federation import FederationConfig, PeerSearchInput
from test_api import app, client, settings, SessionLocal

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
