import datetime

from services.readiness import HeartbeatSnapshot, ReadinessInputs, evaluate_node_readiness


NOW = datetime.datetime(2026, 8, 14, 12, 0, 0)


def _inputs(**overrides) -> ReadinessInputs:
    values = {
        "deployment_mode": "adopter_production",
        "database_current": True,
        "expected_database_heads": ("0016_service_heartbeats",),
        "current_database_heads": ("0016_service_heartbeats",),
        "source_code_url": "https://github.com/example/clef-rights-node",
        "source_code_revision": "abc123",
        "ephemeral_signing_key": False,
        "notification_provider": "smtp",
        "webhook_delivery_enabled": True,
        "expiry_worker_interval_seconds": 3600,
        "webhook_worker_interval_seconds": 10,
        "worker_heartbeats": {
            "expiry_worker": HeartbeatSnapshot("healthy", NOW - datetime.timedelta(seconds=30), NOW - datetime.timedelta(seconds=30)),
            "webhook_worker": HeartbeatSnapshot("healthy", NOW - datetime.timedelta(seconds=5), NOW - datetime.timedelta(seconds=5)),
        },
    }
    values.update(overrides)
    return ReadinessInputs(**values)


def _by_key(result: dict[str, object]) -> dict[str, dict[str, object]]:
    return {row["key"]: row for row in result["checks"]}


def test_healthy_adopter_configuration_is_ready():
    result = evaluate_node_readiness(_inputs(), now=NOW)
    assert result["ready"] is True
    checks = _by_key(result)
    assert checks["database_migrations"]["status"] == "ready"
    assert checks["expiry_worker"]["status"] == "ready"
    assert checks["webhook_worker"]["status"] == "ready"
    assert checks["email_delivery"]["details"] == {"provider": "smtp"}


def test_missing_required_configuration_fails_closed():
    result = evaluate_node_readiness(
        _inputs(
            source_code_url="",
            source_code_revision="development",
            ephemeral_signing_key=True,
            notification_provider="disabled",
            worker_heartbeats={},
        ),
        now=NOW,
    )
    assert result["ready"] is False
    checks = _by_key(result)
    assert checks["corresponding_source"]["status"] == "missing"
    assert checks["receipt_signing_key"]["status"] == "missing"
    assert checks["email_delivery"]["status"] == "missing"
    assert checks["expiry_worker"]["status"] == "missing"


def test_stale_or_failed_worker_is_not_ready():
    stale = HeartbeatSnapshot(
        "healthy",
        NOW - datetime.timedelta(hours=3),
        NOW - datetime.timedelta(hours=3),
    )
    failed = HeartbeatSnapshot(
        "error",
        NOW - datetime.timedelta(seconds=2),
        NOW - datetime.timedelta(seconds=5),
    )
    result = evaluate_node_readiness(
        _inputs(worker_heartbeats={"expiry_worker": stale, "webhook_worker": failed}),
        now=NOW,
    )
    assert result["ready"] is False
    checks = _by_key(result)
    assert checks["expiry_worker"]["status"] == "stale"
    assert checks["webhook_worker"]["status"] == "blocked"


def test_public_sandbox_rejects_outbound_contradictions():
    result = evaluate_node_readiness(
        _inputs(
            deployment_mode="public_sandbox",
            notification_provider="mailgun",
            webhook_delivery_enabled=True,
            mlc_enabled=True,
            mlc_configured=True,
        ),
        now=NOW,
    )
    assert result["ready"] is False
    checks = _by_key(result)
    assert checks["email_delivery"]["status"] == "blocked"
    assert checks["webhook_delivery"]["status"] == "blocked"
    assert checks["mlc_adapter"]["status"] == "blocked"


def test_disabled_optional_local_services_do_not_block_evaluation():
    result = evaluate_node_readiness(
        _inputs(
            deployment_mode="local_evaluation",
            source_code_url="",
            source_code_revision="development",
            ephemeral_signing_key=True,
            notification_provider="disabled",
            webhook_delivery_enabled=False,
            worker_heartbeats={},
        ),
        now=NOW,
    )
    assert result["ready"] is True
    assert _by_key(result)["corresponding_source"]["status"] == "warning"
