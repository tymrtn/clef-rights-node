#!/usr/bin/env python3
"""Run the signed permission-expiry process on a supervised interval."""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
from pathlib import Path
import signal
import time

logger = logging.getLogger("clef.expiry_worker")
stopping = False


def _stop(*_args) -> None:
    global stopping
    stopping = True


def expire_once(*, as_of: datetime.date | None = None) -> dict[str, object]:
    # Keep imports lazy so heartbeat health checks never initialize the API or database.
    from main import SessionLocal, expire_due_permissions

    evaluated_on = as_of or datetime.date.today()
    db = SessionLocal()
    try:
        receipts = expire_due_permissions(
            db,
            as_of=evaluated_on,
            actor={"type": "node_scheduler", "asOf": evaluated_on.isoformat()},
        )
        return {
            "asOf": evaluated_on.isoformat(),
            "expiredCount": len(receipts),
            "receipts": [row.id for row in receipts],
        }
    finally:
        db.close()


def write_heartbeat(path: str | Path, result: dict[str, object]) -> None:
    heartbeat = Path(path)
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "lastSuccessAt": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        **result,
    }
    temporary = heartbeat.with_suffix(f"{heartbeat.suffix}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(heartbeat)


def heartbeat_is_fresh(
    path: str | Path,
    *,
    maximum_age_seconds: int,
    now: float | None = None,
) -> bool:
    heartbeat = Path(path)
    if not heartbeat.is_file():
        return False
    current_time = time.time() if now is None else now
    return 0 <= current_time - heartbeat.stat().st_mtime <= maximum_age_seconds


def configured_interval_seconds() -> int:
    try:
        interval = int(os.environ.get("EXPIRY_WORKER_INTERVAL_SECONDS", "86400"))
    except ValueError as error:
        raise ValueError("EXPIRY_WORKER_INTERVAL_SECONDS must be an integer") from error
    if not 60 <= interval <= 604800:
        raise ValueError(
            "EXPIRY_WORKER_INTERVAL_SECONDS must be between 60 and 604800"
        )
    return interval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one expiry batch and exit")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=configured_interval_seconds(),
        help="Seconds between successful runs",
    )
    parser.add_argument(
        "--heartbeat-file",
        default="/tmp/clef-expiry-worker-heartbeat.json",
        help="Health record written after each successful run",
    )
    args = parser.parse_args()
    if not 60 <= args.interval_seconds <= 604800:
        parser.error("--interval-seconds must be between 60 and 604800")

    if args.once:
        result = expire_once()
        write_heartbeat(args.heartbeat_file, result)
        print(json.dumps(result, sort_keys=True))
        return 0

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("Expiry worker started")
    while not stopping:
        try:
            result = expire_once()
            write_heartbeat(args.heartbeat_file, result)
            logger.info("Expiry batch: %s", json.dumps(result, sort_keys=True))
        except Exception:
            logger.exception("Expiry batch failed")
        for _ in range(args.interval_seconds):
            if stopping:
                break
            time.sleep(1)
    logger.info("Expiry worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
