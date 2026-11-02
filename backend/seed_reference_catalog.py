"""Publish this node's clearly labelled fictional reference catalog, as its operator.

Run where the node runs, for example inside its API container:

    python seed_reference_catalog.py label --operator-email ops@example.org

The address must be in NODE_OPERATOR_EMAILS. A ten-minute session for it exists
only during the run. The catalog goes through the node's own API in-process, so
import review, policy, authority evidence and publication consent all apply.
Rerunning keeps existing records and publication choices.
"""
import argparse
import datetime
import hashlib
import json
import secrets
import sys

from fastapi.testclient import TestClient

from reference_catalog import ApiClient, seed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("role", choices=["label", "publisher"])
    parser.add_argument("--operator-email", required=True)
    args = parser.parse_args(argv)
    import main as node
    from models import MagicSession, UserRecord

    email = args.operator_email.strip().lower()
    if email not in node.settings.NODE_OPERATOR_EMAILS:
        print("The address must be listed in NODE_OPERATOR_EMAILS on this node", file=sys.stderr)
        return 2
    raw = secrets.token_urlsafe(24)
    session_id = hashlib.sha256(raw.encode()).hexdigest()
    with node.SessionLocal() as db:
        user = db.query(UserRecord).filter_by(email=email).first()
        if not user:
            db.add(UserRecord(email=email, display_name=email.split("@")[0], role="admin"))
        elif user.role != "admin":
            user.role = "admin"
        db.add(MagicSession(id=session_id, email=email,
                            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=10)))
        db.commit()
    try:
        fixture = seed(ApiClient(TestClient(node.app), raw), args.role)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        with node.SessionLocal() as db:
            db.query(MagicSession).filter_by(id=session_id).delete()
            db.commit()
    print(json.dumps({"role": args.role, "organization": fixture["org"]["name"], "workKey": fixture["workKey"],
                      "publicationId": fixture["publication"]["id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
