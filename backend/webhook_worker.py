#!/usr/bin/env python3
"""Deliver due Rights Node webhooks from the durable database outbox."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import time

from main import SessionLocal, settings, webhook_secret_box
from services.webhook_outbox import process_due_webhooks


logger = logging.getLogger("clef.webhook_worker")
stopping = False


def _stop(*_args) -> None:
    global stopping
    stopping = True


def deliver_once(limit: int) -> dict[str, int]:
    db = SessionLocal()
    try:
        return process_due_webhooks(
            db,
            secret_box=webhook_secret_box,
            allow_private_targets=settings.WEBHOOK_ALLOW_PRIVATE_TARGETS,
            max_attempts=settings.WEBHOOK_MAX_ATTEMPTS,
            request_timeout_seconds=settings.WEBHOOK_REQUEST_TIMEOUT_SECONDS,
            limit=limit,
        )
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one due batch and exit")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    if args.once:
        print(json.dumps(deliver_once(args.limit), sort_keys=True))
        return 0
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("Webhook worker started")
    while not stopping:
        try:
            result = deliver_once(args.limit)
            if result["selected"]:
                logger.info("Webhook delivery batch: %s", json.dumps(result, sort_keys=True))
        except Exception:
            logger.exception("Webhook delivery batch failed")
        for _ in range(settings.WEBHOOK_WORKER_INTERVAL_SECONDS):
            if stopping:
                break
            time.sleep(1)
    logger.info("Webhook worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
