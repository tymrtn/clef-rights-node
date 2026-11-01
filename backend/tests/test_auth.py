import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from services.auth import MagicLinkService
from services.notifications import DisabledNotificationProvider


@pytest.fixture
def service():
    return MagicLinkService(
        secret="fixture-test-sign-in-secret-with-at-least-32-characters",
        link_exp_minutes=30,
        session_ttl_minutes=30,
        notification_provider=DisabledNotificationProvider(),
        base_url="https://node.example.test",
    )


def test_same_second_links_are_independently_identifiable(service, monkeypatch):
    now = datetime.datetime.utcnow()
    clock = SimpleNamespace(
        datetime=SimpleNamespace(utcnow=lambda: now),
        timedelta=datetime.timedelta,
    )
    monkeypatch.setattr("services.auth.datetime", clock)
    tokens = [
        parse_qs(urlparse(service.create_and_send_link("Artist@Example.test")).query)["token"][0]
        for _ in range(2)
    ]
    assert tokens[0] != tokens[1]
    for token in tokens:
        assert service.validate_token(token) == (True, "artist@example.test")


@pytest.mark.parametrize("claims", [
    {"email": "artist@example.test"},
    {"exp": 4102444800},
    {"exp": 4102444800, "email": ""},
    {"exp": 4102444800, "email": 42},
    {"exp": 4102444800, "email": ["artist@example.test"]},
    {"exp": 4102444800, "email": "artist@example.test@other.test"},
    {"exp": 4102444800, "email": "artist\n@example.test"},
    {"exp": "tomorrow", "email": "artist@example.test"},
])
def test_invalid_signed_identity_claims_fail_closed(service, claims):
    token = jwt.encode(claims, service.secret, algorithm="HS256")
    assert service.validate_token(token) == (False, "Invalid sign-in link")


def test_existing_unexpired_links_still_validate_and_expired_links_fail(service):
    now = datetime.datetime.utcnow()
    for expiry, expected in [
        (now + datetime.timedelta(minutes=1), (True, "artist@example.test")),
        (now - datetime.timedelta(minutes=1), (False, "Token expired")),
    ]:
        token = jwt.encode({"email": "artist@example.test", "exp": expiry}, service.secret, algorithm="HS256")
        assert service.validate_token(token) == expected


def test_wrong_signing_key_is_rejected(service):
    token = jwt.encode(
        {"email": "artist@example.test", "exp": 4102444800},
        "different-test-secret-with-at-least-32-characters", algorithm="HS256",
    )
    assert service.validate_token(token) == (False, "Invalid sign-in link")
