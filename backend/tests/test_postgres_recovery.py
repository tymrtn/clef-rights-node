import copy
import importlib.util
from pathlib import Path
import subprocess

import pytest
from psycopg2.extensions import parse_dsn


SPEC = importlib.util.spec_from_file_location(
    "postgres_recovery", Path(__file__).resolve().parents[2] / "scripts/verify_postgres_recovery.py")
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


@pytest.mark.parametrize("value", ["", "sqlite:///private.db", "postgresql://localhost", "invalid-secret"])
def test_invalid_source_never_exposes_input(value):
    with pytest.raises(recovery.RecoveryFailure) as caught:
        recovery.source_dsn(value)
    assert "invalid-secret" not in str(caught.value)


def test_postgres_url_keeps_ssl_and_escaped_password():
    params = parse_dsn(recovery.source_dsn(
        "postgresql+psycopg2://operator:fixture%40b%2Fc@localhost:5432/rights?sslmode=require"))
    assert params["password"] == "fixture@b/c"
    assert params["sslmode"] == "require"
    assert params["dbname"] == "rights"


@pytest.mark.parametrize("section", ["tables", "sequences", "definitions"])
def test_restore_rejects_lost_rows_sequence_state_or_schema(section):
    source = {"tables": {"public.rn_audit_events": {"rows": 2, "sha256": "original"}},
              "sequences": {"public.event_id_seq": [3, True]},
              "definitions": {"triggers": {"count": 1, "sha256": "original"}}}
    restored = copy.deepcopy(source)
    assert recovery.compare(source, restored) == []
    restored[section] = {}
    assert recovery.compare(source, restored) == [section]


def test_database_tools_do_not_inherit_a_remote_pg_target(monkeypatch):
    for key in ("PGHOST", "PGSERVICE", "PGDATABASE", "PGOPTIONS", "PGPASSWORD"):
        monkeypatch.setenv(key, "private-production-value")
    assert not any(key.startswith("PG") for key in recovery.clean_environment())


def test_dump_receives_database_name_and_password_separately():
    env = recovery.connection_environment(recovery.source_dsn(
        "postgresql://operator:fixture%40b%2Fc@localhost:5432/rights?sslmode=require"))
    assert env["PGDATABASE"] == "rights"
    assert env["PGPASSWORD"] == "fixture@b/c"
    assert env["PGSSLMODE"] == "require"


def test_constraint_cast_rewrite_preserves_values_and_other_expressions():
    source = "CHECK (((status)::text = ANY ((ARRAY['accepted'::character varying, 'rejected'::character varying])::text[])))"
    restored = "CHECK (((status)::text = ANY (ARRAY[('accepted'::character varying)::text, ('rejected'::character varying)::text])))"
    assert recovery.canonical_constraint(source) == restored
    assert recovery.canonical_constraint(restored) == restored
    assert recovery.canonical_constraint(source.replace("rejected", "error")) != restored
    other = "CHECK ((amount > 0))"
    assert recovery.canonical_constraint(other) == other


def test_subprocess_failure_redacts_database_records(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr="private-row private-password")
    monkeypatch.setattr(recovery.subprocess, "run", fail)
    with pytest.raises(recovery.RecoveryFailure) as caught:
        recovery.run_tool(Path("pg_restore"), "private-password")
    assert "private" not in str(caught.value)
