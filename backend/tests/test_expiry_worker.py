import json

from expiry_worker import heartbeat_is_fresh, write_heartbeat


def test_expiry_worker_heartbeat_records_success_and_stales_closed(tmp_path):
    path = tmp_path / "expiry-heartbeat.json"
    write_heartbeat(
        path,
        {
            "asOf": "2026-07-13",
            "expiredCount": 1,
            "receipts": ["receipt-1"],
        },
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["asOf"] == "2026-07-13"
    assert payload["expiredCount"] == 1
    assert payload["receipts"] == ["receipt-1"]
    assert payload["lastSuccessAt"].endswith("+00:00")

    modified = path.stat().st_mtime
    assert heartbeat_is_fresh(path, maximum_age_seconds=60, now=modified + 59)
    assert not heartbeat_is_fresh(path, maximum_age_seconds=60, now=modified + 61)
    assert not heartbeat_is_fresh(
        tmp_path / "missing.json",
        maximum_age_seconds=60,
        now=modified,
    )
