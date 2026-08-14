from __future__ import annotations

import datetime
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree as ET


MWL_PROFILE = "mwl-1.0.1"
MWL_NAMESPACE = "http://ddex.net/xml/mc-us-lic/101"
MWL_XSD_SHA256 = "ef13a0d0722398ecbb4d31ece64896b0122501d07e4fc7fa8e35df8853fea7ad"
MWL_AVS_XSD_SHA256 = "6abbaa8e32a4ad78215562c48d4f15a27412ace1ea0db6bedbf693f2fc79cbac"
XMLDSIG_XSD_SHA256 = "35cf8197da812c85e40d57891b35c94187569ed474a2dac813ce5090dafcd35c"
DPID_PATTERN = re.compile(r"^PADPIDA[A-Z0-9]{11}$")
DPID_CHARACTERS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ISO_DATE_PATTERN = re.compile(r"^[0-9]{4}(?:-[0-9]{2})?(?:-[0-9]{2})?$")

RIGHTS_TYPES = {
    "MechanicalRight",
    "PerformingRight",
    "PrintRight",
    "SynchronizationRight",
}
USE_TYPES = {
    "AsPerContract",
    "ConditionalDownload",
    "Dub",
    "DubForAdvertisement",
    "DubForLivePerformance",
    "DubForMovies",
    "DubForPublicPerformance",
    "DubForTV",
    "NonInteractiveStream",
    "OnDemandStream",
    "PermanentDownload",
    "Podcast",
    "PurchaseAsPhysicalProduct",
    "Stream",
    "TetheredDownload",
    "UserMakeAvailableLabelProvided",
    "UserMakeAvailableUserProvided",
    "Webcast",
}
DISTRIBUTION_CHANNEL_TYPES = {
    "AsPerContract",
    "Broadcast",
    "Cable",
    "Internet",
    "InternetAndMobile",
    "IPTV",
    "MobileTelephone",
    "Physical",
    "Satellite",
}
ROYALTY_RATE_CALCULATION_TYPES = {
    "ControlledCompositionRoyaltyRate",
    "MinimumStatutoryRoyaltyRate",
    "NegotiatedRoyaltyRate",
    "ReducedStatutoryRoyaltyRate",
    "StatutoryRoyaltyRate",
}
PERCENTAGE_TYPES = {
    "PercentageOfGrossRevenue",
    "PercentageOfNetRevenue",
    "PercentageOfNetSales",
    "PercentageOfPriceConsumerPaid",
    "PercentageOfStatutoryRoyaltyRate",
}
LICENSE_REJECTION_REASONS = {
    "DisagreementOverRoyalties",
    "DisagreementOverScopeOfLicense",
    "DuplicateLicenseRequestNumber",
    "LicenseBlocked",
    "LicenseExists",
    "LicenseNotNeeded",
    "ReferencedDocumentMissing",
}


class MWLExportError(ValueError):
    pass


class MWLSchemaValidationError(MWLExportError):
    pass


@dataclass(frozen=True)
class MWLTerms:
    work_title: str
    work_identifier: str
    territory: str = "US"
    iswc: str | None = None
    rights_type: str = "MechanicalRight"
    use_type: str = "AsPerContract"
    distribution_channel_type: str | None = "Internet"
    right_share_percentage: Decimal = Decimal("100")
    royalty_rate_calculation_type: str = "NegotiatedRoyaltyRate"
    royalty_percentage: Decimal = Decimal("100")
    percentage_type: str = "PercentageOfNetRevenue"
    term_start: str | None = None
    term_end: str | None = None


def _dpid_check_character(value_without_check: str) -> str:
    interim = 36
    for character in value_without_check:
        character_value = DPID_CHARACTERS.index(character)
        remainder = ((interim % 37) + character_value) % 36
        interim = (remainder or 36) * 2
    return DPID_CHARACTERS[(1 - (interim % 37)) % 36]


def validate_dpid(value: str, field: str) -> None:
    if not DPID_PATTERN.fullmatch(value):
        raise MWLExportError(
            f"{field} must use the 18-character DDEX message syntax without hyphens"
        )
    if _dpid_check_character(value[:-1]) != value[-1]:
        raise MWLExportError(f"{field} has an invalid DPID check character")


def _validate_terms(terms: MWLTerms) -> None:
    if not terms.work_title.strip() or not terms.work_identifier.strip():
        raise MWLExportError("work title and identifier are required")
    if terms.territory != "US":
        raise MWLExportError("MWL 1.0.1 exports are limited to the US territory")
    if terms.rights_type not in RIGHTS_TYPES:
        raise MWLExportError(f"unsupported MWL rights type: {terms.rights_type}")
    if terms.use_type not in USE_TYPES:
        raise MWLExportError(f"unsupported MWL use type: {terms.use_type}")
    if terms.distribution_channel_type and terms.distribution_channel_type not in DISTRIBUTION_CHANNEL_TYPES:
        raise MWLExportError(
            f"unsupported MWL distribution channel: {terms.distribution_channel_type}"
        )
    if terms.royalty_rate_calculation_type not in ROYALTY_RATE_CALCULATION_TYPES:
        raise MWLExportError(
            f"unsupported MWL royalty calculation: {terms.royalty_rate_calculation_type}"
        )
    if terms.percentage_type not in PERCENTAGE_TYPES:
        raise MWLExportError(f"unsupported MWL percentage type: {terms.percentage_type}")
    for label, value in (
        ("right share percentage", terms.right_share_percentage),
        ("royalty percentage", terms.royalty_percentage),
    ):
        if value < 0 or value > 100:
            raise MWLExportError(f"{label} must be between 0 and 100")
    for label, value in (("term start", terms.term_start), ("term end", terms.term_end)):
        if value and not ISO_DATE_PATTERN.fullmatch(value):
            raise MWLExportError(f"{label} must use DDEX ISO date syntax")
    if terms.term_start and terms.term_end and terms.term_start > terms.term_end:
        raise MWLExportError("term start must not be after term end")


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _element(parent: ET.Element, name: str, text: str | None = None, **attributes: str) -> ET.Element:
    child = ET.SubElement(parent, name, attributes)
    if text is not None:
        child.text = text
    return child


def _root(message_type: Literal["LicenseRequestMessage", "LicenseMessage"]) -> ET.Element:
    ET.register_namespace("mwl", MWL_NAMESPACE)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    return ET.Element(
        f"{{{MWL_NAMESPACE}}}{message_type}",
        {
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": (
                f"{MWL_NAMESPACE} {MWL_NAMESPACE}/us-works-licensing-choreography.xsd"
            ),
            "LanguageAndScriptCode": "en",
        },
    )


def _message_header(
    root: ET.Element,
    *,
    message_id: str,
    sender_dpid: str,
    sender_name: str,
    recipient_dpid: str,
    recipient_name: str,
    created_at: datetime.datetime,
    is_test: bool,
) -> None:
    header = _element(root, "MessageHeader")
    _element(header, "MessageId", message_id)
    sender = _element(header, "MessageSender")
    _element(sender, "PartyId", sender_dpid)
    sender_party_name = _element(sender, "PartyName")
    _element(sender_party_name, "FullName", sender_name)
    recipient = _element(header, "MessageRecipient")
    _element(recipient, "PartyId", recipient_dpid)
    recipient_party_name = _element(recipient, "PartyName")
    _element(recipient_party_name, "FullName", recipient_name)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=datetime.timezone.utc)
    _element(header, "MessageCreatedDateTime", created_at.isoformat(timespec="seconds"))
    _element(header, "MessageControlType", "TestMessage" if is_test else "LiveMessage")


def _shared_lists(
    root: ET.Element,
    *,
    sender_dpid: str,
    rights_controller_identifier: str,
    rights_controller_name: str,
    terms: MWLTerms,
) -> None:
    party_list = _element(root, "PartyList")
    party = _element(party_list, "Party")
    party_id = _element(party, "PartyId")
    _element(party_id, "ProprietaryId", rights_controller_identifier, Namespace=sender_dpid)
    _element(party, "PartyReference", "P0001")
    party_name = _element(party, "PartyName")
    _element(party_name, "FullName", rights_controller_name)
    _element(party, "IsOrganization", "true")

    work_list = _element(root, "WorkList")
    work = _element(work_list, "MusicalWork")
    _element(work, "MusicalWorkReference", "W0001")
    work_id = _element(work, "MusicalWorkId")
    if terms.iswc:
        _element(work_id, "ISWC", terms.iswc)
    _element(work_id, "ProprietaryId", terms.work_identifier, Namespace=sender_dpid)
    title = _element(work, "Title")
    _element(title, "TitleText", terms.work_title)


def _right_share_list(
    root: ET.Element,
    *,
    terms: MWLTerms,
    rights_controller_role: Literal["owner", "agent"],
) -> None:
    share_list = _element(root, "RightShareList")
    share = _element(share_list, "RightShare")
    _element(share, "RightShareReference", "S0001")
    _element(share, "RightShareType", "LicensingShare")
    _element(share, "RightShareWorkReference", "W0001")
    _element(share, "TerritoryCode", terms.territory)
    _element(share, "RightsType", terms.rights_type)
    if rights_controller_role == "owner":
        controller = _element(share, "RightsController", IsOwner="true")
    elif rights_controller_role == "agent":
        controller = _element(share, "RightsController", IsAgent="true")
    else:
        raise MWLExportError("rights controller role must be owner or agent")
    _element(controller, "RightsControllerPartyReference", "P0001")
    if terms.term_start or terms.term_end:
        validity = _element(share, "ValidityPeriod")
        if terms.term_start:
            _element(validity, "StartDate", terms.term_start)
        if terms.term_end:
            _element(validity, "EndDate", terms.term_end)
    _element(share, "RightSharePercentage", _decimal_text(terms.right_share_percentage))


def _condition_list(root: ET.Element, *, terms: MWLTerms) -> None:
    condition_list = _element(root, "ConditionList")
    condition = _element(condition_list, "Condition")
    _element(condition, "LicenseConditionReference", "E0001")
    _element(condition, "RightsType", terms.rights_type)
    usage = _element(condition, "Usage")
    _element(usage, "UseType", terms.use_type)
    if terms.distribution_channel_type:
        _element(usage, "DistributionChannelType", terms.distribution_channel_type)
    royalty = _element(condition, "RoyaltyRate")
    _element(royalty, "RoyaltyRateCalculationType", terms.royalty_rate_calculation_type)
    _element(
        royalty,
        "PercentageRate",
        _decimal_text(terms.royalty_percentage),
        PercentageType=terms.percentage_type,
    )
    if terms.term_start or terms.term_end:
        validity = _element(condition, "RateValidity")
        if terms.term_start:
            _element(validity, "StartDate", terms.term_start)
        if terms.term_end:
            _element(validity, "EndDate", terms.term_end)


def _serialize(root: ET.Element) -> bytes:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_license_request(
    *,
    sender_dpid: str,
    sender_name: str,
    recipient_dpid: str,
    recipient_name: str,
    rights_controller_identifier: str,
    rights_controller_name: str,
    rights_controller_role: Literal["owner", "agent"],
    message_id: str,
    license_request_id: str,
    terms: MWLTerms,
    created_at: datetime.datetime,
    is_test: bool,
) -> bytes:
    validate_dpid(sender_dpid, "sender DPID")
    validate_dpid(recipient_dpid, "recipient DPID")
    _validate_terms(terms)
    root = _root("LicenseRequestMessage")
    _message_header(
        root,
        message_id=message_id,
        sender_dpid=sender_dpid,
        sender_name=sender_name,
        recipient_dpid=recipient_dpid,
        recipient_name=recipient_name,
        created_at=created_at,
        is_test=is_test,
    )
    _element(root, "MessagePurpose", "LicenseRequest")
    _shared_lists(
        root,
        sender_dpid=sender_dpid,
        rights_controller_identifier=rights_controller_identifier,
        rights_controller_name=rights_controller_name,
        terms=terms,
    )
    _right_share_list(root, terms=terms, rights_controller_role=rights_controller_role)
    _condition_list(root, terms=terms)
    request_list = _element(root, "LicenseRequestList")
    request = _element(request_list, "LicenseRequest")
    _element(request, "LicenseRequestId", license_request_id, Namespace=sender_dpid)
    _element(request, "RequestRightShareReference", "S0001")
    _element(request, "RequestConditionReference", "E0001")
    return _serialize(root)


def build_license_decision(
    *,
    sender_dpid: str,
    sender_name: str,
    recipient_dpid: str,
    recipient_name: str,
    rights_controller_identifier: str,
    rights_controller_name: str,
    rights_controller_role: Literal["owner", "agent"],
    message_id: str,
    license_request_id: str,
    decision: Literal["approved", "rejected"],
    decision_id: str,
    terms: MWLTerms,
    created_at: datetime.datetime,
    is_test: bool,
    rejection_reason: str = "DisagreementOverScopeOfLicense",
    rejection_note: str | None = None,
) -> bytes:
    validate_dpid(sender_dpid, "sender DPID")
    validate_dpid(recipient_dpid, "recipient DPID")
    _validate_terms(terms)
    if decision not in {"approved", "rejected"}:
        raise MWLExportError("decision must be approved or rejected")
    if decision == "rejected" and rejection_reason not in LICENSE_REJECTION_REASONS:
        raise MWLExportError(f"unsupported MWL rejection reason: {rejection_reason}")
    root = _root("LicenseMessage")
    _message_header(
        root,
        message_id=message_id,
        sender_dpid=sender_dpid,
        sender_name=sender_name,
        recipient_dpid=recipient_dpid,
        recipient_name=recipient_name,
        created_at=created_at,
        is_test=is_test,
    )
    _element(root, "MessagePurpose", "License")
    _shared_lists(
        root,
        sender_dpid=sender_dpid,
        rights_controller_identifier=rights_controller_identifier,
        rights_controller_name=rights_controller_name,
        terms=terms,
    )
    _right_share_list(root, terms=terms, rights_controller_role=rights_controller_role)
    license_list = _element(root, "LicenseList")
    if decision == "approved":
        license_node = _element(license_list, "License")
        license_id = _element(license_node, "LicenseId")
        _element(license_id, "ProprietaryId", decision_id, Namespace=sender_dpid)
        _element(license_node, "LicenseRequestId", license_request_id, Namespace=sender_dpid)
        _element(license_node, "LicenseRightShareReference", "S0001")
    else:
        rejection = _element(license_list, "LicenseRejection")
        _element(rejection, "LicenseRejectionId", decision_id, Namespace=sender_dpid)
        _element(rejection, "LicenseRequestId", license_request_id, Namespace=sender_dpid)
        _element(rejection, "LicenseRejectionReason", rejection_reason)
        if rejection_note:
            _element(rejection, "AdditionalInformation", rejection_note)
    return _serialize(root)


def validate_mwl_xml(xml: bytes, xsd_path: str) -> None:
    """Validate against operator-supplied official MWL 1.0.1 schemas."""
    try:
        from lxml import etree
    except ImportError as error:  # pragma: no cover - packaging guard
        raise MWLSchemaValidationError("lxml is required for DDEX schema validation") from error

    schema_path = Path(xsd_path).expanduser().resolve()
    if not schema_path.is_file():
        raise MWLSchemaValidationError("DDEX MWL XSD path does not exist")
    if hashlib.sha256(schema_path.read_bytes()).hexdigest() != MWL_XSD_SHA256:
        raise MWLSchemaValidationError("DDEX MWL XSD does not match the pinned 1.0.1 schema")
    avs_path = schema_path.parent / "avs3.xsd"
    signature_path = schema_path.parent / "xmldsig-core-schema.xsd"
    if not avs_path.is_file():
        raise MWLSchemaValidationError("DDEX avs3.xsd must be installed beside the MWL schema")
    if hashlib.sha256(avs_path.read_bytes()).hexdigest() != MWL_AVS_XSD_SHA256:
        raise MWLSchemaValidationError("DDEX allowed-value schema does not match MWL 1.0.1")
    if not signature_path.is_file():
        raise MWLSchemaValidationError("W3C XMLDSIG schema must be installed beside the MWL schema")
    if hashlib.sha256(signature_path.read_bytes()).hexdigest() != XMLDSIG_XSD_SHA256:
        raise MWLSchemaValidationError("W3C XMLDSIG schema does not match the pinned revision")

    class LocalSignatureResolver(etree.Resolver):
        def resolve(self, url, public_id, context):  # type: ignore[no-untyped-def]
            if url.endswith("xmldsig-core-schema.xsd"):
                return self.resolve_filename(str(signature_path), context)
            return None

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    parser.resolvers.add(LocalSignatureResolver())
    try:
        schema = etree.XMLSchema(etree.parse(str(schema_path), parser))
        document = etree.fromstring(xml, parser)
        schema.assertValid(document)
    except (etree.XMLSyntaxError, etree.DocumentInvalid, etree.XMLSchemaParseError) as error:
        raise MWLSchemaValidationError(f"DDEX MWL schema validation failed: {error}") from error
