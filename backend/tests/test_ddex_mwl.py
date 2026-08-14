import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from services.adapters.ddex_mwl import (
    MWLExportError,
    MWLTerms,
    build_license_decision,
    build_license_request,
)


def _terms(**overrides):
    values = {
        "work_title": "Example Work",
        "work_identifier": "MLC-WORK-123",
        "territory": "US",
        "rights_type": "MechanicalRight",
        "use_type": "UserMakeAvailableUserProvided",
        "distribution_channel_type": "Internet",
        "right_share_percentage": Decimal("100"),
        "royalty_rate_calculation_type": "NegotiatedRoyaltyRate",
        "royalty_percentage": Decimal("100"),
        "percentage_type": "PercentageOfNetRevenue",
        "term_start": "2026-08-01",
        "term_end": "2027-07-31",
    }
    values.update(overrides)
    return MWLTerms(**values)


def _common():
    return {
        "sender_dpid": "PADPIDA0000000001O",
        "sender_name": "Clef Rights Node",
        "recipient_dpid": "PADPIDA0000000002M",
        "recipient_name": "DDEX Partner",
        "rights_controller_identifier": "org-1",
        "rights_controller_name": "Example Publisher",
        "rights_controller_role": "owner",
        "terms": _terms(),
        "created_at": datetime.datetime(2026, 7, 10, 12, 0, tzinfo=datetime.timezone.utc),
        "is_test": True,
    }


def test_mwl_request_contains_explicit_scope_and_terms():
    xml = build_license_request(
        **_common(),
        message_id="message-1",
        license_request_id="permission-1",
    )
    root = ET.fromstring(xml)
    assert root.tag == "{http://ddex.net/xml/mc-us-lic/101}LicenseRequestMessage"
    assert root.findtext("MessagePurpose") == "LicenseRequest"
    assert root.findtext("RightShareList/RightShare/TerritoryCode") == "US"
    assert root.findtext("RightShareList/RightShare/RightsType") == "MechanicalRight"
    assert root.findtext("ConditionList/Condition/Usage/UseType") == "UserMakeAvailableUserProvided"
    assert root.findtext("ConditionList/Condition/RateValidity/EndDate") == "2027-07-31"


@pytest.mark.parametrize("decision, expected", [("approved", "License"), ("rejected", "LicenseRejection")])
def test_mwl_decision_supports_grants_and_rejections(decision, expected):
    xml = build_license_decision(
        **_common(),
        message_id=f"message-{decision}",
        license_request_id="permission-1",
        decision=decision,
        decision_id=f"decision-{decision}",
    )
    root = ET.fromstring(xml)
    assert root.find(f"LicenseList/{expected}") is not None


def test_mwl_never_silently_maps_non_us_or_unknown_rights():
    with pytest.raises(MWLExportError, match="limited to the US"):
        build_license_request(
            **{**_common(), "terms": _terms(territory="Worldwide")},
            message_id="message-1",
            license_request_id="permission-1",
        )
    with pytest.raises(MWLExportError, match="unsupported MWL rights type"):
        build_license_request(
            **{**_common(), "terms": _terms(rights_type="AdaptationRight")},
            message_id="message-2",
            license_request_id="permission-2",
        )


@pytest.mark.parametrize(
    "dpid, error",
    [
        ("PA-DPIDA-0000000001-O", "18-character"),
        ("PADPIDA0000000001A", "check character"),
        ("PADPIDATOOSHORT", "18-character"),
    ],
)
def test_mwl_rejects_nonconforming_dpids(dpid, error):
    with pytest.raises(MWLExportError, match=error):
        build_license_request(
            **{**_common(), "sender_dpid": dpid},
            message_id="message-invalid-dpid",
            license_request_id="permission-invalid-dpid",
        )
