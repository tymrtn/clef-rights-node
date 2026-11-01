from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class HeartbeatSnapshot:
    status: str
    last_attempt_at: datetime.datetime
    last_success_at: datetime.datetime | None
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReadinessInputs:
    deployment_mode: str
    database_current: bool
    expected_database_heads: tuple[str, ...]
    current_database_heads: tuple[str, ...]
    source_code_url: str
    source_code_revision: str
    ephemeral_signing_key: bool
    notification_provider: str
    webhook_delivery_enabled: bool
    expiry_worker_interval_seconds: int
    webhook_worker_interval_seconds: int
    worker_heartbeats: Mapping[str, HeartbeatSnapshot] = field(default_factory=dict)
    demo_mode: bool = False
    mock_integrations: bool = False
    development_identity_headers: bool = False
    development_magic_links: bool = False
    mlc_enabled: bool = False
    mlc_configured: bool = False
    ddex_enabled: bool = False
    ddex_configured: bool = False
    musicbrainz_enabled: bool = False
    musicbrainz_configured: bool = False


def _check(
    key: str,
    status: str,
    summary: str,
    *,
    required: bool,
    remediation: str | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "key": key,
        "status": status,
        "required": required,
        "summary": summary,
        "remediation": remediation,
        "details": dict(details or {}),
    }


def _worker_check(
    *,
    key: str,
    label: str,
    required: bool,
    heartbeat: HeartbeatSnapshot | None,
    maximum_age_seconds: int,
    now: datetime.datetime,
) -> dict[str, object]:
    if not required:
        return _check(key, "disabled", f"{label} is not required in this configuration.", required=False)
    if heartbeat is None or heartbeat.last_success_at is None:
        return _check(
            key,
            "missing",
            f"{label} has not recorded a successful database heartbeat.",
            required=True,
            remediation="docs/RAILWAY_DEPLOYMENT.md#verify-the-deployment",
            details={"maximumAgeSeconds": maximum_age_seconds},
        )
    age_seconds = int((now - heartbeat.last_success_at).total_seconds())
    details = {
        "lastAttemptAt": heartbeat.last_attempt_at.replace(microsecond=0).isoformat() + "Z",
        "lastSuccessAt": heartbeat.last_success_at.replace(microsecond=0).isoformat() + "Z",
        "ageSeconds": age_seconds,
        "maximumAgeSeconds": maximum_age_seconds,
    }
    if heartbeat.status != "healthy":
        return _check(
            key,
            "blocked",
            f"{label} last reported an error.",
            required=True,
            remediation="docs/RAILWAY_DEPLOYMENT.md#verify-the-deployment",
            details=details,
        )
    if age_seconds < 0 or age_seconds > maximum_age_seconds:
        return _check(
            key,
            "stale",
            f"{label} heartbeat is outside its expected interval.",
            required=True,
            remediation="docs/RAILWAY_DEPLOYMENT.md#verify-the-deployment",
            details=details,
        )
    return _check(key, "ready", f"{label} is reporting successfully.", required=True, details=details)


def _adapter_check(
    *,
    key: str,
    label: str,
    enabled: bool,
    configured: bool,
    sandbox: bool,
) -> dict[str, object]:
    if sandbox and enabled:
        return _check(
            key,
            "blocked",
            f"{label} must remain disabled in a public sandbox.",
            required=True,
            remediation="docs/DEPLOYMENT_MATRIX.md#public-sandbox",
        )
    if not enabled:
        return _check(key, "disabled", f"{label} is disabled.", required=False)
    if not configured:
        return _check(
            key,
            "blocked",
            f"{label} is enabled but its non-secret configuration is incomplete.",
            required=True,
            remediation="docs/RAILWAY_DEPLOYMENT.md#optional-integrations",
        )
    return _check(key, "ready", f"{label} is configured; live authority remains capability-scoped.", required=True)


def evaluate_node_readiness(
    inputs: ReadinessInputs,
    *,
    now: datetime.datetime | None = None,
) -> dict[str, object]:
    """Calculate mode-aware readiness without probing partners or exposing secrets."""

    checked_at = now or datetime.datetime.utcnow()
    sandbox = inputs.deployment_mode == "public_sandbox"
    adopter = inputs.deployment_mode in {"adopter_staging", "adopter_production"}
    operational = sandbox or adopter
    checks: list[dict[str, object]] = []

    checks.append(
        _check(
            "database_migrations",
            "ready" if inputs.database_current else "blocked",
            "Database revision matches the published migration head."
            if inputs.database_current
            else "Database revision does not match the published migration head.",
            required=True,
            remediation=None if inputs.database_current else "docs/RAILWAY_DEPLOYMENT.md#run-database-migrations",
            details={
                "expectedHeads": list(inputs.expected_database_heads),
                "currentHeads": list(inputs.current_database_heads),
            },
        )
    )

    source_configured = bool(inputs.source_code_url) and inputs.source_code_revision != "development"
    source_required = operational
    checks.append(
        _check(
            "corresponding_source",
            "ready" if source_configured else ("missing" if source_required else "warning"),
            "Corresponding source and deployed revision are identified."
            if source_configured
            else "Corresponding source metadata is not configured.",
            required=source_required,
            remediation=None if source_configured else "docs/RAILWAY_DEPLOYMENT.md#identify-the-deployed-source",
            details={"configured": source_configured, "revision": inputs.source_code_revision},
        )
    )

    signing_required = operational
    durable_signing = not inputs.ephemeral_signing_key
    checks.append(
        _check(
            "receipt_signing_key",
            "ready" if durable_signing else ("missing" if signing_required else "warning"),
            "Receipt signing identity is durable."
            if durable_signing
            else "Receipt signing identity is ephemeral and changes on restart.",
            required=signing_required,
            remediation=None if durable_signing else "docs/RAILWAY_DEPLOYMENT.md#generate-adopter-held-secrets",
        )
    )

    unsafe_runtime = any(
        (
            inputs.demo_mode,
            inputs.mock_integrations,
            inputs.development_identity_headers,
            inputs.development_magic_links,
        )
    )
    checks.append(
        _check(
            "runtime_safety",
            "blocked" if adopter and unsafe_runtime else "ready",
            "Development and mock identity paths are disabled."
            if not unsafe_runtime
            else (
                "Development or mock identity paths are enabled in an adopter deployment."
                if adopter
                else "Development or mock identity paths are intentionally enabled for this mode."
            ),
            required=adopter,
            remediation="docs/RAILWAY_DEPLOYMENT.md#configure-runtime-safety" if adopter and unsafe_runtime else None,
        )
    )

    if sandbox:
        notification_status = "blocked" if inputs.notification_provider != "disabled" else "disabled"
        notification_summary = (
            "Email delivery must remain disabled in a public sandbox."
            if notification_status == "blocked"
            else "Email delivery is disabled for the public sandbox."
        )
        notification_required = notification_status == "blocked"
    elif adopter:
        notification_status = "ready" if inputs.notification_provider in {"mailgun", "smtp"} else "missing"
        notification_summary = (
            f"Portable email delivery is configured through {inputs.notification_provider}."
            if notification_status == "ready"
            else "Adopter email delivery is not configured."
        )
        notification_required = True
    else:
        notification_status = "ready" if inputs.notification_provider in {"mailgun", "smtp"} else "disabled"
        notification_summary = (
            f"Email delivery is configured through {inputs.notification_provider}."
            if notification_status == "ready"
            else "Email delivery is disabled for local evaluation."
        )
        notification_required = False
    checks.append(
        _check(
            "email_delivery",
            notification_status,
            notification_summary,
            required=notification_required,
            remediation="docs/RAILWAY_DEPLOYMENT.md#configure-email" if notification_status in {"missing", "blocked"} else None,
            details={"provider": inputs.notification_provider},
        )
    )

    if sandbox and inputs.webhook_delivery_enabled:
        checks.append(
            _check(
                "webhook_delivery",
                "blocked",
                "Outbound webhook delivery must remain disabled in a public sandbox.",
                required=True,
                remediation="docs/DEPLOYMENT_MATRIX.md#public-sandbox",
            )
        )
    elif not inputs.webhook_delivery_enabled:
        checks.append(_check("webhook_delivery", "disabled", "Outbound webhook delivery is disabled.", required=False))
    else:
        checks.append(_check("webhook_delivery", "ready", "Outbound webhook delivery is enabled.", required=True))

    expiry_max_age = max(inputs.expiry_worker_interval_seconds * 2 + 60, 300)
    webhook_max_age = max(inputs.webhook_worker_interval_seconds * 3 + 30, 60)
    checks.append(
        _worker_check(
            key="expiry_worker",
            label="Permission expiry worker",
            required=operational,
            heartbeat=inputs.worker_heartbeats.get("expiry_worker"),
            maximum_age_seconds=expiry_max_age,
            now=checked_at,
        )
    )
    checks.append(
        _worker_check(
            key="webhook_worker",
            label="Webhook delivery worker",
            required=inputs.webhook_delivery_enabled and not sandbox,
            heartbeat=inputs.worker_heartbeats.get("webhook_worker"),
            maximum_age_seconds=webhook_max_age,
            now=checked_at,
        )
    )

    checks.extend(
        (
            _adapter_check(key="mlc_adapter", label="MLC adapter", enabled=inputs.mlc_enabled, configured=inputs.mlc_configured, sandbox=sandbox),
            _adapter_check(key="ddex_adapter", label="DDEX adapter", enabled=inputs.ddex_enabled, configured=inputs.ddex_configured, sandbox=sandbox),
            _adapter_check(key="musicbrainz_adapter", label="MusicBrainz adapter", enabled=inputs.musicbrainz_enabled, configured=inputs.musicbrainz_configured, sandbox=sandbox),
        )
    )

    ready = all(check["status"] == "ready" for check in checks if check["required"])
    return {
        "ready": ready,
        "deploymentMode": inputs.deployment_mode,
        "checkedAt": checked_at.replace(microsecond=0).isoformat() + "Z",
        "checks": checks,
    }
