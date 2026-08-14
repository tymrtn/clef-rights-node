from __future__ import annotations

from pathlib import Path

from .base import CAPABILITIES, CapabilityStatus, UnsupportedCapability, normalize_capabilities
from .ddex_mwl import MWL_PROFILE, MWLExportError, validate_dpid, validate_mwl_xml


class DDEXAdapter:
    name = "ddex"

    def __init__(
        self,
        *,
        enabled: bool,
        implementation_license_confirmed: bool,
        dpid: str | None,
        partner_dpid: str | None,
        sender_name: str | None,
        partner_name: str | None,
        profile: str | None,
        mwl_xsd_path: str | None,
        authorized_capabilities: set[str],
    ) -> None:
        self.enabled = enabled
        self.implementation_license_confirmed = implementation_license_confirmed
        self.dpid = dpid
        self.partner_dpid = partner_dpid
        self.sender_name = sender_name
        self.partner_name = partner_name
        self.profile = profile
        self.mwl_xsd_path = mwl_xsd_path
        self.authorized_capabilities = normalize_capabilities(authorized_capabilities)
        self.identity_error = None
        if dpid or partner_dpid:
            try:
                validate_dpid(dpid or "", "sender DPID")
                validate_dpid(partner_dpid or "", "partner DPID")
            except MWLExportError as error:
                self.identity_error = str(error)
        self.configured = bool(
            enabled
            and implementation_license_confirmed
            and dpid
            and partner_dpid
            and sender_name
            and partner_name
            and profile == MWL_PROFILE
            and mwl_xsd_path
            and Path(mwl_xsd_path).expanduser().is_file()
            and self.identity_error is None
        )

    def capabilities(self) -> list[CapabilityStatus]:
        result = []
        for name in sorted(CAPABILITIES):
            authorized = self.configured and name in self.authorized_capabilities
            result.append(
                CapabilityStatus(
                    name=name,
                    configured=self.configured,
                    reachable=None,
                    authorized=authorized,
                    last_verified_at=None,
                    detail=(
                        f"Configured for bilateral DDEX profile {self.profile}"
                        if self.configured
                        else (
                            self.identity_error
                            or "Requires licence confirmation, sender/partner identities, MWL 1.0.1 schema, and bilateral configuration"
                        )
                    ),
                )
            )
        return result

    def require(self, capability: str) -> None:
        if capability not in CAPABILITIES:
            raise UnsupportedCapability(f"Unknown capability: {capability}")
        if not self.configured or capability not in self.authorized_capabilities:
            raise UnsupportedCapability(f"DDEX capability is unavailable: {capability}")

    def validate_mwl(self, xml: bytes) -> None:
        self.require("permission_request_exchange")
        validate_mwl_xml(xml, self.mwl_xsd_path or "")
