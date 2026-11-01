from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Optional, Protocol, Sequence

import requests


class NotificationDeliveryError(RuntimeError):
    """A provider-safe delivery failure that never includes credentials."""


class NotificationProvider(Protocol):
    name: str
    enabled: bool

    def send(self, *, to_emails: Sequence[str], subject: str, text: str) -> None: ...


def _recipients(values: Sequence[str]) -> list[str]:
    recipients = [value.strip().lower() for value in values if value and value.strip()]
    if not recipients or any(value.count("@") != 1 or "\n" in value or "\r" in value for value in recipients):
        raise ValueError("At least one valid recipient email is required")
    return recipients


def _header(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise ValueError(f"{label} must be a non-empty single-line value")
    return normalized


@dataclass(frozen=True)
class DisabledNotificationProvider:
    name: str = "disabled"
    enabled: bool = False

    def send(self, *, to_emails: Sequence[str], subject: str, text: str) -> None:
        raise NotificationDeliveryError("Email delivery is not configured")


@dataclass(frozen=True)
class MailgunNotificationProvider:
    api_key: str
    domain: str
    from_email: str
    connect_timeout_seconds: int = 5
    read_timeout_seconds: int = 15
    name: str = "mailgun"
    enabled: bool = True

    def send(self, *, to_emails: Sequence[str], subject: str, text: str) -> None:
        recipients = _recipients(to_emails)
        try:
            response = requests.post(
                f"https://api.mailgun.net/v3/{self.domain}/messages",
                auth=("api", self.api_key),
                data={
                    "from": _header(self.from_email, "from email"),
                    "to": recipients,
                    "subject": _header(subject, "subject"),
                    "text": text,
                },
                timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
            )
            response.raise_for_status()
        except (requests.RequestException, ValueError) as error:
            raise NotificationDeliveryError("Mailgun email delivery failed") from error


@dataclass(frozen=True)
class SmtpNotificationProvider:
    host: str
    port: int
    from_email: str
    username: Optional[str] = None
    password: Optional[str] = None
    security: str = "starttls"
    timeout_seconds: int = 15
    name: str = "smtp"
    enabled: bool = True

    def send(self, *, to_emails: Sequence[str], subject: str, text: str) -> None:
        recipients = _recipients(to_emails)
        message = EmailMessage()
        message["From"] = _header(self.from_email, "from email")
        message["To"] = ", ".join(recipients)
        message["Subject"] = _header(subject, "subject")
        message.set_content(text)
        context = ssl.create_default_context()
        envelope_sender = parseaddr(self.from_email)[1]
        if not envelope_sender or envelope_sender.count("@") != 1:
            raise ValueError("from email must contain a valid mailbox")
        try:
            if self.security == "implicit":
                client: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout_seconds, context=context)
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds)
            with client:
                client.ehlo()
                if self.security == "starttls":
                    client.starttls(context=context)
                    client.ehlo()
                if self.username:
                    client.login(self.username, self.password or "")
                client.send_message(message, from_addr=envelope_sender, to_addrs=recipients)
        except (OSError, smtplib.SMTPException, ValueError) as error:
            raise NotificationDeliveryError("SMTP email delivery failed") from error


def notification_provider_from_settings(settings: object) -> NotificationProvider:
    provider = str(getattr(settings, "NOTIFICATION_PROVIDER", "disabled")).casefold()
    if provider == "mailgun":
        return MailgunNotificationProvider(
            api_key=str(getattr(settings, "MAILGUN_API_KEY")),
            domain=str(getattr(settings, "MAILGUN_DOMAIN")),
            from_email=str(getattr(settings, "NOTIFICATION_FROM_EMAIL")),
            connect_timeout_seconds=int(getattr(settings, "NOTIFICATION_CONNECT_TIMEOUT_SECONDS")),
            read_timeout_seconds=int(getattr(settings, "NOTIFICATION_READ_TIMEOUT_SECONDS")),
        )
    if provider == "smtp":
        return SmtpNotificationProvider(
            host=str(getattr(settings, "SMTP_HOST")),
            port=int(getattr(settings, "SMTP_PORT")),
            from_email=str(getattr(settings, "NOTIFICATION_FROM_EMAIL")),
            username=getattr(settings, "SMTP_USERNAME"),
            password=getattr(settings, "SMTP_PASSWORD"),
            security=str(getattr(settings, "SMTP_SECURITY")),
            timeout_seconds=int(getattr(settings, "NOTIFICATION_READ_TIMEOUT_SECONDS")),
        )
    return DisabledNotificationProvider()


def send_slack_message(*, slack_webhook_url: Optional[str], text: str) -> None:
    if not slack_webhook_url:
        return
    response = requests.post(slack_webhook_url, json={"text": text}, timeout=(5, 10))
    response.raise_for_status()
