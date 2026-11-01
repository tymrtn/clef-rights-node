from __future__ import annotations

import requests
import pytest

from services.auth import MagicLinkService
from services.notifications import (
    DisabledNotificationProvider,
    MailgunNotificationProvider,
    NotificationDeliveryError,
    SmtpNotificationProvider,
)
from services.settings import Settings


class FakeResponse:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error


class FakeSmtp:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def ehlo(self) -> None:
        self.calls.append(("ehlo",))

    def starttls(self, *, context) -> None:
        self.calls.append(("starttls", bool(context)))

    def login(self, username: str, password: str) -> None:
        self.calls.append(("login", username, password))

    def send_message(self, message, *, from_addr: str, to_addrs: list[str]) -> None:
        self.calls.append(("send", message["Subject"], from_addr, to_addrs))


class RecordingProvider:
    name = "recording"
    enabled = True

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send(self, **kwargs) -> None:
        self.messages.append(kwargs)


def test_disabled_provider_fails_explicitly() -> None:
    with pytest.raises(NotificationDeliveryError, match="not configured"):
        DisabledNotificationProvider().send(to_emails=["person@example.test"], subject="Test", text="Body")


def test_mailgun_provider_uses_bounded_transport_and_wraps_failures(monkeypatch) -> None:
    observed = {}

    def post(url, **kwargs):
        observed.update({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("services.notifications.requests.post", post)
    provider = MailgunNotificationProvider(api_key="private-mailgun-secret", domain="mail.example.test", from_email="Clef <rights@example.test>")
    provider.send(to_emails=["Person@Example.Test"], subject="Scoped review", text="Body")
    assert observed["timeout"] == (5, 15)
    assert observed["data"]["to"] == ["person@example.test"]
    assert observed["auth"] == ("api", "private-mailgun-secret")

    monkeypatch.setattr("services.notifications.requests.post", lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.Timeout("private-mailgun-secret")))
    with pytest.raises(NotificationDeliveryError) as failure:
        provider.send(to_emails=["person@example.test"], subject="Scoped review", text="Body")
    assert "private-mailgun-secret" not in str(failure.value)


def test_smtp_provider_starttls_authentication_and_secret_redaction(monkeypatch) -> None:
    client = FakeSmtp()
    monkeypatch.setattr("services.notifications.smtplib.SMTP", lambda host, port, timeout: client)
    provider = SmtpNotificationProvider(
        host="smtp.example.test",
        port=587,
        from_email="Clef Rights <rights@example.test>",
        username="rights@example.test",
        password="fixture-private-smtp-secret",
        security="starttls",
    )
    provider.send(to_emails=["operator@example.test"], subject="Sign in", text="Body")
    assert ("starttls", True) in client.calls
    assert ("login", "rights@example.test", "fixture-private-smtp-secret") in client.calls
    assert ("send", "Sign in", "rights@example.test", ["operator@example.test"]) in client.calls

    monkeypatch.setattr("services.notifications.smtplib.SMTP", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("fixture-private-smtp-secret")))
    with pytest.raises(NotificationDeliveryError) as failure:
        provider.send(to_emails=["operator@example.test"], subject="Sign in", text="Body")
    assert "fixture-private-smtp-secret" not in str(failure.value)


def test_magic_link_uses_provider_without_coupling_to_mailgun() -> None:
    provider = RecordingProvider()
    service = MagicLinkService(secret="test-secret", link_exp_minutes=30, session_ttl_minutes=30, notification_provider=provider, base_url="https://node.example.test")
    link = service.create_and_send_link("Operator@Example.Test")
    assert link.startswith("https://node.example.test/login?token=")
    assert provider.messages[0]["to_emails"] == ["operator@example.test"]


def _production_environment(monkeypatch) -> None:
    values = {
        "APP_ENV": "production",
        "NODE_DEPLOYMENT_MODE": "adopter_production",
        "DEMO_MODE": "false",
        "MOCK_INTEGRATIONS": "false",
        "ALLOW_DEV_IDENTITY_HEADERS": "false",
        "ALLOW_DEV_MAGIC_LINKS": "false",
        "RIGHTS_MAGIC_LINK_SECRET": "fixture-a-production-secret-with-more-than-32-characters",
        "DATABASE_URL": "postgresql+psycopg2://rights:secret@db/rights",
        "NODE_OPERATOR_EMAILS": "operator@example.test",
        "CORS_ALLOW_ORIGINS": "https://node.example.test",
        "WEBHOOK_ENCRYPTION_KEY_B64": "configured-separate-key",
        "WEBHOOK_ALLOW_PRIVATE_TARGETS": "false",
        "SOURCE_CODE_URL": "https://github.com/example/node/tree/0123456789abcdef0123456789abcdef01234567",
        "SOURCE_CODE_REVISION": "0123456789abcdef0123456789abcdef01234567",
        "NOTIFICATION_PROVIDER": "smtp",
        "NOTIFICATION_FROM_EMAIL": "Clef Rights <rights@example.test>",
        "SMTP_HOST": "smtp.example.test",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "rights@example.test",
        "SMTP_PASSWORD": "fixture-private-smtp-secret",
        "SMTP_SECURITY": "starttls",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_production_settings_accept_complete_smtp_and_reject_partial_credentials(monkeypatch) -> None:
    _production_environment(monkeypatch)
    configured = Settings()
    assert configured.EMAIL_DELIVERY_CONFIGURED is True
    assert configured.NOTIFICATION_PROVIDER == "smtp"
    monkeypatch.delenv("SMTP_PASSWORD")
    with pytest.raises(RuntimeError, match="configured together"):
        Settings()
