from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


CAPABILITIES = {
    "catalog_lookup",
    "ownership_evidence_read",
    "work_registration_write",
    "claim_submission_write",
    "permission_request_exchange",
    "usage_reporting_write",
    "royalty_statement_read",
}


class UnsupportedCapability(RuntimeError):
    pass


@dataclass(frozen=True)
class CapabilityStatus:
    name: str
    configured: bool
    reachable: bool | None
    authorized: bool
    last_verified_at: str | None
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_capabilities(values: Iterable[str]) -> set[str]:
    normalized = {value.strip() for value in values if value.strip()}
    invalid = normalized - CAPABILITIES
    if invalid:
        raise RuntimeError(f"Unsupported adapter capabilities: {', '.join(sorted(invalid))}")
    return normalized
