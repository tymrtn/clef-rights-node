#!/usr/bin/env python3
"""Download official schemas, optionally install them, and validate MWL exports."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import sys
import tempfile
import urllib.request
import zipfile
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.adapters.ddex_mwl import (  # noqa: E402
    MWLTerms,
    build_license_decision,
    build_license_request,
    validate_mwl_xml,
)


DDEX_XSD_URL = "https://service.ddex.net/doc/PastStandards/MWL%201.0.1%20XSD.zip"
DDEX_XSD_ZIP_SHA256 = "f556adf0a4e4a7a9a60761782d576a474ccd86fcd06ab8cdb00b45c9ef890ace"
XMLDSIG_URL = "https://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd"
XMLDSIG_SHA256 = "35cf8197da812c85e40d57891b35c94187569ed474a2dac813ce5090dafcd35c"
SCHEMA_FILENAMES = (
    "us-works-licensing-choreography.xsd",
    "avs3.xsd",
    "xmldsig-core-schema.xsd",
)


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Clef-Rights-Node-Conformance/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _official_schemas() -> dict[str, bytes]:
    archive = _download(DDEX_XSD_URL)
    if hashlib.sha256(archive).hexdigest() != DDEX_XSD_ZIP_SHA256:
        raise RuntimeError("official DDEX MWL 1.0.1 schema archive digest changed")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        members = {
            Path(name).name: name
            for name in bundle.namelist()
            if name.endswith(".xsd")
        }
        schemas = {}
        for filename in SCHEMA_FILENAMES[:2]:
            if filename not in members:
                raise RuntimeError(f"official schema archive is missing {filename}")
            schemas[filename] = bundle.read(members[filename])
    xmldsig = _download(XMLDSIG_URL)
    if hashlib.sha256(xmldsig).hexdigest() != XMLDSIG_SHA256:
        raise RuntimeError("W3C XMLDSIG schema digest changed")
    schemas[SCHEMA_FILENAMES[2]] = xmldsig
    return schemas


def _write_schemas(schema_dir: Path, schemas: dict[str, bytes]) -> None:
    schema_dir.mkdir(parents=True, exist_ok=True)
    for filename in SCHEMA_FILENAMES:
        (schema_dir / filename).write_bytes(schemas[filename])


def _validate_profiles(schema_dir: Path) -> None:
    xsd_path = str(schema_dir / SCHEMA_FILENAMES[0])
    terms = MWLTerms(
        work_title="Example Work",
        work_identifier="MLC-WORK-123",
        territory="US",
        rights_type="MechanicalRight",
        use_type="UserMakeAvailableUserProvided",
        distribution_channel_type="Internet",
        right_share_percentage=Decimal("100"),
        royalty_rate_calculation_type="NegotiatedRoyaltyRate",
        royalty_percentage=Decimal("100"),
        percentage_type="PercentageOfNetRevenue",
        term_start="2026-08-01",
        term_end="2027-07-31",
    )
    common = {
        "sender_dpid": "PADPIDA0000000001O",
        "sender_name": "Clef Rights Node",
        "recipient_dpid": "PADPIDA0000000002M",
        "recipient_name": "DDEX Partner",
        "rights_controller_identifier": "org-1",
        "rights_controller_name": "Example Publisher",
        "rights_controller_role": "owner",
        "terms": terms,
        "created_at": datetime.datetime(2026, 7, 10, 12, 0, tzinfo=datetime.timezone.utc),
        "is_test": True,
    }
    messages = {
        "LicenseRequestMessage": build_license_request(
            **common,
            message_id="request-message-1",
            license_request_id="permission-1",
        ),
        "LicenseMessage grant": build_license_decision(
            **common,
            message_id="grant-message-1",
            license_request_id="permission-1",
            decision="approved",
            decision_id="receipt-1",
        ),
        "LicenseMessage rejection": build_license_decision(
            **common,
            message_id="rejection-message-1",
            license_request_id="permission-1",
            decision="rejected",
            decision_id="rejection-1",
            rejection_note="Outside current scope",
        ),
    }
    for label, message in messages.items():
        validate_mwl_xml(message, xsd_path)
        print(f"valid: {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--install-dir",
        type=Path,
        help="persist the verified schemas in this operator-controlled directory",
    )
    args = parser.parse_args()
    schemas = _official_schemas()
    if args.install_dir:
        schema_dir = args.install_dir.expanduser().resolve()
        _write_schemas(schema_dir, schemas)
        _validate_profiles(schema_dir)
        print(f"installed: {schema_dir}")
    else:
        with tempfile.TemporaryDirectory(prefix="clef-mwl-") as directory:
            schema_dir = Path(directory)
            _write_schemas(schema_dir, schemas)
            _validate_profiles(schema_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
