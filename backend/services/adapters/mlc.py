from __future__ import annotations

from services.mlc_client import MLCClient

from .base import CAPABILITIES, CapabilityStatus, UnsupportedCapability, normalize_capabilities


class MLCAdapter:
    name = "mlc"

    def __init__(
        self,
        *,
        enabled: bool,
        username: str | None,
        password: str | None,
        base_url: str,
        authorized_capabilities: set[str],
        connect_timeout_seconds: int = 5,
        read_timeout_seconds: int = 20,
        max_retries: int = 3,
        max_response_bytes: int = 5_000_000,
    ) -> None:
        self.enabled = enabled
        self.username = username
        self.password = password
        self.base_url = base_url
        self.authorized_capabilities = normalize_capabilities(authorized_capabilities)
        self.configured = bool(enabled and username and password)
        self.client = (
            MLCClient(
                username,
                password,
                base_url,
                connect_timeout_seconds=connect_timeout_seconds,
                read_timeout_seconds=read_timeout_seconds,
                max_retries=max_retries,
                max_response_bytes=max_response_bytes,
            )
            if self.configured
            else None
        )

    def capabilities(self) -> list[CapabilityStatus]:
        result = []
        for name in sorted(CAPABILITIES):
            authorized = self.configured and name in self.authorized_capabilities
            if name in {"catalog_lookup", "ownership_evidence_read"}:
                detail = "MLC musical-work metadata capability"
            else:
                detail = "Requires explicit MLC account authority and connector implementation"
            result.append(
                CapabilityStatus(
                    name=name,
                    configured=self.configured,
                    reachable=self.client.reachable if self.client else None,
                    authorized=authorized,
                    last_verified_at=self.client.last_verified_at if self.client else None,
                    detail=detail,
                )
            )
        return result

    def require(self, capability: str) -> MLCClient:
        if capability not in CAPABILITIES:
            raise UnsupportedCapability(f"Unknown capability: {capability}")
        if not self.configured or capability not in self.authorized_capabilities or not self.client:
            raise UnsupportedCapability(f"MLC capability is unavailable: {capability}")
        return self.client
