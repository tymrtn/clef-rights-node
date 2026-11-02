"""Rate limits key on the client the hosting edge saw, not on the web proxy in front of the API."""
import uuid

from test_api import client, settings


def invite(address=None):
    headers = {"X-Real-IP": address} if address else {}
    return client.post("/auth/invite", json={"email": f"limit-{uuid.uuid4().hex}@example.test"}, headers=headers)


def test_configured_edge_header_gives_each_client_its_own_limit(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_HEADER", "X-Real-IP")
    first, second = f"198.51.100.{uuid.uuid4().int % 250}", f"203.0.113.{uuid.uuid4().int % 250}"
    assert all(invite(first).status_code == 202 for _ in range(5))
    assert invite(first).status_code == 429
    assert invite(second).status_code == 202


def test_without_a_configured_header_a_client_cannot_choose_its_own_key(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_HEADER", "")
    # The test client's own address carries the limit; a supplied header changes nothing.
    statuses = [invite(f"192.0.2.{index}").status_code for index in range(7)]
    assert 429 in statuses
