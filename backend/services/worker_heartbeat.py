from __future__ import annotations

import datetime
from typing import Mapping

from sqlalchemy.orm import Session

from models import ServiceHeartbeatRecord


ALLOWED_SERVICE_NAMES = frozenset({"expiry_worker", "webhook_worker"})


def record_service_heartbeat(
    db: Session,
    *,
    service_name: str,
    succeeded: bool,
    details: Mapping[str, object] | None = None,
    error_type: str | None = None,
    attempted_at: datetime.datetime | None = None,
) -> ServiceHeartbeatRecord:
    """Upsert one bounded, non-secret service health signal and commit it."""

    if service_name not in ALLOWED_SERVICE_NAMES:
        raise ValueError("Unsupported service heartbeat name")
    now = attempted_at or datetime.datetime.utcnow()
    safe_details = dict(details or {})
    if error_type:
        safe_details["errorType"] = error_type[:120]
    row = db.get(ServiceHeartbeatRecord, service_name)
    if row is None:
        row = ServiceHeartbeatRecord(
            service_name=service_name,
            status="healthy" if succeeded else "error",
            last_attempt_at=now,
            last_success_at=now if succeeded else None,
            details=safe_details,
            updated_at=now,
        )
        db.add(row)
    else:
        row.status = "healthy" if succeeded else "error"
        row.last_attempt_at = now
        if succeeded:
            row.last_success_at = now
        row.details = safe_details
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row
