#!/usr/bin/env python3
"""Append signed expiry records for grants whose declared term has ended."""

from __future__ import annotations

import argparse
import datetime
import json

from main import SessionLocal, expire_due_permissions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        help="Evaluate grants as of YYYY-MM-DD; defaults to the node's current date",
    )
    args = parser.parse_args()
    try:
        as_of = datetime.date.fromisoformat(args.as_of) if args.as_of else datetime.date.today()
    except ValueError as error:
        parser.error(f"invalid --as-of date: {error}")

    db = SessionLocal()
    try:
        receipts = expire_due_permissions(
            db,
            as_of=as_of,
            actor={"type": "node_scheduler", "asOf": as_of.isoformat()},
        )
        print(
            json.dumps(
                {
                    "asOf": as_of.isoformat(),
                    "expiredCount": len(receipts),
                    "receipts": [row.id for row in receipts],
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
