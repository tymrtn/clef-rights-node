from __future__ import annotations

import base64
import datetime
import hashlib
import ipaddress
import secrets
import socket
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import (
    WebhookAttemptRecord,
    WebhookEndpointRecord,
    WebhookEventRecord,
    WebhookOutboxDeliveryRecord,
)
from services.webhooks import signed_webhook_body, webhook_signature


SUPPORTED_WEBHOOK_EVENTS = frozenset(
    {
        "organization.member.added",
        "webhook.test",
        "catalog.import.committed",
        "catalog.asset.assigned",
        "rights_policy.published",
        "authority_claim.asserted",
        "authority_claim.verified",
        "authority_claim.rejected",
        "authority_claim.conflict_detected",
        "authority_conflict.resolved",
        "permission_request.created",
        "permission_request.approved",
        "permission_request.rejected",
        "permission_request.reviewer_assigned",
        "permission_request.reviewer_cleared",
        "permission_request.disputed",
        "permission_request.revoked",
        "permission_request.corrected",
        "permission_request.expired",
        "permission_usage.reported",
        "permission_usage.reviewed",
        "settlement.terms.created",
        "settlement.entry.reserve",
        "settlement.entry.reserve_release",
        "settlement.entry.payment_received",
        "settlement.entry.payment_reversal",
        "settlement.entry.payout",
        "settlement.entry.payout_reversal",
        "settlement.entry.royalty_adjustment_increase",
        "settlement.entry.royalty_adjustment_decrease",
        "settlement.royalty.calculated",
        "settlement.reconciliation.recorded",
        "ddex_exchange.generated",
        "ddex_acknowledgement.recorded",
    }
)


class WebhookSecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Webhook encryption key must contain exactly 32 bytes")
        self._cipher = AESGCM(key)

    @classmethod
    def from_config(cls, *, key_b64: str | None, development_secret: str) -> "WebhookSecretBox":
        if key_b64:
            try:
                key = base64.urlsafe_b64decode(key_b64 + "=" * (-len(key_b64) % 4))
            except Exception as error:
                raise ValueError("WEBHOOK_ENCRYPTION_KEY_B64 is not valid URL-safe base64") from error
        else:
            key = hashlib.sha256(f"clef-development-webhook-key:{development_secret}".encode("utf-8")).digest()
        return cls(key)

    def encrypt(self, secret: str, *, endpoint_id: str) -> str:
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(nonce, secret.encode("utf-8"), endpoint_id.encode("utf-8"))
        return "v1." + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")

    def decrypt(self, value: str, *, endpoint_id: str) -> str:
        version, separator, encoded = value.partition(".")
        if version != "v1" or not separator:
            raise ValueError("Unsupported webhook secret ciphertext version")
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if len(raw) < 29:
            raise ValueError("Webhook secret ciphertext is truncated")
        plaintext = self._cipher.decrypt(raw[:12], raw[12:], endpoint_id.encode("utf-8"))
        return plaintext.decode("utf-8")


def generate_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def normalize_webhook_url(url: str, *, production: bool) -> str:
    normalized = url.strip()
    parsed = urlparse(normalized)
    allowed_schemes = {"https"} if production else {"https", "http"}
    if parsed.scheme.lower() not in allowed_schemes:
        requirement = "https" if production else "http or https"
        raise ValueError(f"Webhook URL must use {requirement}")
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Webhook URL requires a host and cannot contain credentials or a fragment")
    if parsed.hostname.lower() == "localhost":
        raise ValueError("Webhook URL cannot target localhost")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Webhook URL contains an invalid port") from error
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Webhook URL contains an invalid port")
    return normalized


def assert_safe_webhook_target(url: str, *, allow_private: bool) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook target has no hostname")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as error:
        raise ValueError("Webhook target hostname did not resolve") from error
    if not addresses:
        raise ValueError("Webhook target hostname did not resolve")
    if allow_private:
        return
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise ValueError("Webhook target resolved to a private, local, reserved, or otherwise non-public address")


def subscription_matches(events: list[str], event: str) -> bool:
    return "*" in events or event in events


def enqueue_webhook_event(
    db: Session,
    *,
    org_id: str,
    event: str,
    payload: dict[str, Any],
    occurred_at: datetime.datetime,
) -> WebhookEventRecord | None:
    if event not in SUPPORTED_WEBHOOK_EVENTS:
        return None
    endpoints = (
        db.query(WebhookEndpointRecord)
        .filter(WebhookEndpointRecord.org_id == org_id, WebhookEndpointRecord.enabled.is_(True))
        .all()
    )
    matching = [endpoint for endpoint in endpoints if subscription_matches(endpoint.events or [], event)]
    if not matching:
        return None
    webhook_event = WebhookEventRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        event=event,
        payload=payload,
        occurred_at=occurred_at,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(webhook_event)
    db.flush()
    for endpoint in matching:
        db.add(
            WebhookOutboxDeliveryRecord(
                id=str(uuid.uuid4()),
                endpoint_id=endpoint.id,
                event_id=webhook_event.id,
                org_id=org_id,
                status="pending",
                attempt_count=0,
                next_attempt_at=occurred_at,
                created_at=datetime.datetime.utcnow(),
                updated_at=datetime.datetime.utcnow(),
            )
        )
    return webhook_event


def _safe_error(error: Any) -> str:
    text = " ".join(str(error or "delivery failed").split())
    return text[:500]


def _retry_delay_seconds(attempt_number: int) -> int:
    delays = (60, 300, 1800, 7200, 43200, 86400)
    return delays[min(max(attempt_number - 1, 0), len(delays) - 1)]


def process_due_webhooks(
    db: Session,
    *,
    secret_box: WebhookSecretBox,
    allow_private_targets: bool,
    max_attempts: int,
    request_timeout_seconds: int,
    limit: int = 100,
    transport: Callable[..., Any] | None = None,
    target_validator: Callable[[str], None] | None = None,
) -> dict[str, int]:
    if transport is None:
        import requests

        transport = requests.post
    now = datetime.datetime.utcnow()
    due_ids = [
        row[0]
        for row in (
            db.query(WebhookOutboxDeliveryRecord.id)
            .filter(
                WebhookOutboxDeliveryRecord.status.in_(("pending", "retry", "processing")),
                WebhookOutboxDeliveryRecord.next_attempt_at <= now,
                or_(WebhookOutboxDeliveryRecord.lease_until.is_(None), WebhookOutboxDeliveryRecord.lease_until <= now),
            )
            .order_by(WebhookOutboxDeliveryRecord.next_attempt_at.asc(), WebhookOutboxDeliveryRecord.created_at.asc())
            .limit(limit)
            .all()
        )
    ]
    results = {"selected": len(due_ids), "delivered": 0, "retry": 0, "deadLetter": 0}
    for delivery_id in due_ids:
        acquired_at = datetime.datetime.utcnow()
        delivery = (
            db.query(WebhookOutboxDeliveryRecord)
            .filter(WebhookOutboxDeliveryRecord.id == delivery_id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if not delivery or delivery.status not in {"pending", "retry", "processing"}:
            db.rollback()
            continue
        if delivery.lease_until and delivery.lease_until > acquired_at:
            db.rollback()
            continue
        delivery.status = "processing"
        delivery.lease_until = acquired_at + datetime.timedelta(seconds=max(request_timeout_seconds * 2, 30))
        delivery.updated_at = acquired_at
        db.commit()

        endpoint = db.query(WebhookEndpointRecord).filter(WebhookEndpointRecord.id == delivery.endpoint_id).first()
        event = db.query(WebhookEventRecord).filter(WebhookEventRecord.id == delivery.event_id).first()
        attempt_number = delivery.attempt_count + 1
        request_timestamp = int(time.time())
        started = time.monotonic()
        status_code: int | None = None
        error_message: str | None = None
        outcome = "failed"
        transient = False
        try:
            if not endpoint or not endpoint.enabled:
                raise ValueError("Webhook endpoint is disabled or unavailable")
            if not event:
                raise ValueError("Webhook event is unavailable")
            if target_validator:
                target_validator(endpoint.url)
            else:
                assert_safe_webhook_target(endpoint.url, allow_private=allow_private_targets)
            secret = secret_box.decrypt(endpoint.secret_ciphertext, endpoint_id=endpoint.id)
            body = signed_webhook_body(
                delivery_id=delivery.id,
                event=event.event,
                payload=event.payload,
                occurred_at=event.occurred_at.replace(microsecond=0).isoformat() + "Z",
            )
            response = transport(
                endpoint.url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Clef-Rights-Node-Webhook/1.0",
                    "X-Clef-Delivery": delivery.id,
                    "X-Clef-Event": event.event,
                    "X-Clef-Timestamp": str(request_timestamp),
                    "X-Clef-Signature": webhook_signature(secret=secret, timestamp=request_timestamp, body=body),
                },
                timeout=request_timeout_seconds,
                allow_redirects=False,
            )
            status_code = int(response.status_code)
            if 200 <= status_code < 300:
                outcome = "succeeded"
            else:
                error_message = f"HTTP {status_code}"
                transient = status_code in {408, 425, 429} or status_code >= 500
        except Exception as error:
            error_message = _safe_error(error)
            transient = not isinstance(error, ValueError)
        duration_ms = max(0, int((time.monotonic() - started) * 1000))

        delivery = (
            db.query(WebhookOutboxDeliveryRecord)
            .filter(WebhookOutboxDeliveryRecord.id == delivery_id)
            .with_for_update()
            .first()
        )
        if not delivery:
            db.rollback()
            continue
        delivery.attempt_count = attempt_number
        delivery.last_status_code = status_code
        delivery.last_error = error_message
        delivery.lease_until = None
        delivery.updated_at = datetime.datetime.utcnow()
        db.add(
            WebhookAttemptRecord(
                id=str(uuid.uuid4()),
                delivery_id=delivery.id,
                attempt_number=attempt_number,
                request_timestamp=request_timestamp,
                outcome=outcome,
                status_code=status_code,
                error=error_message,
                duration_ms=duration_ms,
                created_at=datetime.datetime.utcnow(),
            )
        )
        if outcome == "succeeded":
            delivery.status = "succeeded"
            delivery.delivered_at = datetime.datetime.utcnow()
            delivery.next_attempt_at = delivery.delivered_at
            results["delivered"] += 1
        elif transient and attempt_number < max_attempts:
            delivery.status = "retry"
            delivery.next_attempt_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=_retry_delay_seconds(attempt_number))
            results["retry"] += 1
        else:
            delivery.status = "dead_letter"
            delivery.dead_lettered_at = datetime.datetime.utcnow()
            delivery.next_attempt_at = delivery.dead_lettered_at
            results["deadLetter"] += 1
        db.commit()
    return results
