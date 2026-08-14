from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from .receipts import canonical_json


def signed_webhook_body(
    *,
    delivery_id: str,
    event: str,
    payload: dict[str, Any],
    occurred_at: str,
) -> bytes:
    return canonical_json(
        {
            "deliveryId": delivery_id,
            "event": event,
            "occurredAt": occurred_at,
            "payload": payload,
        }
    )


def webhook_signature(*, secret: str, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def verify_webhook_signature(
    *,
    secret: str,
    timestamp: int,
    body: bytes,
    signature: str,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> bool:
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        return False
    expected = webhook_signature(secret=secret, timestamp=timestamp, body=body)
    return hmac.compare_digest(expected, signature)
