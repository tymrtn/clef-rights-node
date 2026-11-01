#!/usr/bin/env python3
"""Exercise a logical PostgreSQL backup in a disposable, socket-only local server."""

from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import make_url


class RecoveryFailure(RuntimeError):
    pass


def source_dsn(value: str) -> str:
    try:
        url = make_url(value)
        if url.drivername not in {"postgresql", "postgresql+psycopg2"} or not url.database:
            raise ValueError()
        params = url.translate_connect_args(username="user")
        params["dbname"] = params.pop("database")
        params.update(url.query)
        params["connect_timeout"] = 10
        return psycopg2.extensions.make_dsn(**params)
    except Exception:
        raise RecoveryFailure("Supply an explicit PostgreSQL database URL through the named environment variable") from None


def clean_environment() -> dict[str, str]:
    # Never let inherited PGHOST/PGSERVICE/PGOPTIONS direct local tools elsewhere.
    return {key: value for key, value in os.environ.items() if not key.startswith("PG")}


def connection_environment(dsn: str) -> dict[str, str]:
    # PGDATABASE is a database name, not a DSN. Credentials stay out of argv.
    names = {"dbname": "PGDATABASE", "user": "PGUSER", "password": "PGPASSWORD",
             "host": "PGHOST", "hostaddr": "PGHOSTADDR", "port": "PGPORT",
             "connect_timeout": "PGCONNECT_TIMEOUT", "sslmode": "PGSSLMODE",
             "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY", "sslrootcert": "PGSSLROOTCERT",
             "sslcrl": "PGSSLCRL", "sslcrldir": "PGSSLCRLDIR", "options": "PGOPTIONS",
             "application_name": "PGAPPNAME", "channel_binding": "PGCHANNELBINDING",
             "target_session_attrs": "PGTARGETSESSIONATTRS"}
    values = psycopg2.extensions.parse_dsn(dsn)
    if values.keys() - names.keys():
        raise RecoveryFailure("The database URL uses a connection option this recovery tool does not support")
    return dict(clean_environment(), **{names[key]: value for key, value in values.items()})


def run_tool(binary: Path, *args: str, env: dict | None = None, timeout: int = 1800) -> str:
    try:
        result = subprocess.run([str(binary), *args], env=env or clean_environment(),
                                check=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        # PostgreSQL errors may contain rows, SQL, connection strings or credentials.
        raise RecoveryFailure(f"{binary.name} failed; check local PostgreSQL compatibility, access and disk capacity") from None


@contextmanager
def isolated_postgres(pg_bin: Path):
    # Private short socket path also works under macOS's UNIX socket path limit.
    root = Path(tempfile.mkdtemp(prefix="clef-restore-", dir="/tmp"))
    stopped = True
    try:
        data = root / "data"
        run_tool(pg_bin / "initdb", "-D", str(data), "-U", "clef_recovery",
                 "-A", "trust", "--no-locale", "--encoding=UTF8")
        try:
            run_tool(pg_bin / "pg_ctl", "-D", str(data), "-l", str(root / "server.log"),
                     "-o", f"-h '' -k {root} -p 55471", "-w", "start", timeout=60)
            yield root, psycopg2.extensions.make_dsn(
                dbname="postgres", user="clef_recovery", host=str(root), port=55471, connect_timeout=10)
        finally:
            # This directory belongs only to this invocation; never stop an operator server.
            if (data / "postmaster.pid").exists():
                stopped = False
                try:
                    run_tool(pg_bin / "pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop", timeout=60)
                    stopped = True
                except RecoveryFailure:
                    raise RecoveryFailure(f"Local recovery server could not stop; inspect and remove {root} after stopping it") from None
    finally:
        if stopped:
            shutil.rmtree(root)


def canonical_constraint(definition: str) -> str:
    # PostgreSQL reparses pg_dump CHECK expressions, pushing an array's text cast
    # onto its varchar literals. Normalize only this precise, equivalent rewrite.
    literal = r"'(?:[^']|'')*'::character varying"
    pattern = r"\(ARRAY\[((?:" + literal + r")(?:, " + literal + r")*)\]\)::text\[\]"
    return re.sub(pattern, lambda match: "ARRAY[" + ", ".join(
        f"({value})::text" for value in re.findall(literal, match[1])) + "]", definition)


def fingerprint(connection) -> dict:
    """Read rows in deterministic order, retaining hashes and counts rather than records."""
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL search_path TO pg_catalog")
        cursor.execute("SET LOCAL TIME ZONE 'UTC'")
        cursor.execute("SET LOCAL DateStyle TO 'ISO, YMD'")
        cursor.execute("SET LOCAL extra_float_digits TO 3")
        cursor.execute("""SELECT n.nspname, c.relname, c.relkind FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
              AND c.relkind IN ('r','p','S') ORDER BY 1,2""")
        relations = cursor.fetchall()
    if ("public", "alembic_version", "r") not in relations:
        raise RecoveryFailure("The source must contain a migrated Clef database")
    tables, sequences = {}, {}
    for schema, name, kind in relations:
        identifier = sql.Identifier(schema, name)
        if kind == "S":
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("SELECT last_value, is_called FROM {}").format(identifier))
                sequences[f"{schema}.{name}"] = list(cursor.fetchone())
            continue
        digest, count = hashlib.sha256(), 0
        with connection.cursor(name="clef_recovery_rows") as cursor:
            cursor.execute(sql.SQL('SELECT row_to_json(t)::text FROM ONLY {} t '
                                   'ORDER BY row_to_json(t)::text COLLATE "C"').format(identifier))
            for (row,) in cursor:
                value = row.encode("utf-8")
                digest.update(len(value).to_bytes(8, "big"))
                digest.update(value)
                count += 1
        tables[f"{schema}.{name}"] = {"rows": count, "sha256": digest.hexdigest()}
    # Inspect application definitions too: equal rows alone would miss lost audit triggers.
    definitions = {}
    queries = {
        "columns": """SELECT table_schema, table_name, column_name, ordinal_position,
            data_type, udt_name, is_nullable, column_default, is_identity, identity_generation,
            character_maximum_length, numeric_precision, numeric_scale, datetime_precision,
            collation_name, is_generated, generation_expression
            FROM information_schema.columns WHERE table_schema !~ '^pg_'
            AND table_schema <> 'information_schema' ORDER BY 1,2,4""",
        "constraints": """SELECT n.nspname,c.relname,k.conname,pg_get_constraintdef(k.oid)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname !~ '^pg_'
            AND n.nspname <> 'information_schema' ORDER BY 1,2,3""",
        "triggers": """SELECT n.nspname,c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid)
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal
            AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema' ORDER BY 1,2,3""",
        "functions": """SELECT n.nspname,p.proname,pg_get_functiondef(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
            AND p.prokind IN ('f','p') ORDER BY 1,2,3""",
        "indexes": """SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes
            WHERE schemaname !~ '^pg_' AND schemaname <> 'information_schema' ORDER BY 1,2,3""",
        "sequenceSettings": """SELECT schemaname,sequencename,data_type::text,start_value,
            min_value,max_value,increment_by,cycle,cache_size FROM pg_sequences
            WHERE schemaname !~ '^pg_' AND schemaname <> 'information_schema' ORDER BY 1,2""",
    }
    with connection.cursor() as cursor:
        for key, query in queries.items():
            cursor.execute(query)
            rows = cursor.fetchall()
            if key == "constraints":
                rows = [(*row[:3], canonical_constraint(row[3])) for row in rows]
            definitions[key] = {"count": len(rows), "sha256": hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}
    return {"tables": tables, "sequences": sequences, "definitions": definitions}


def compare(source: dict, restored: dict) -> list[str]:
    return [section for section in ("tables", "sequences", "definitions") if source[section] != restored[section]]


def mismatched_objects(source: dict, restored: dict) -> dict:
    return {section: sorted(key for key in source[section].keys() | restored[section].keys()
                            if source[section].get(key) != restored[section].get(key))
            for section in compare(source, restored)}


def verify(dsn: str, pg_bin: Path) -> dict:
    version = run_tool(pg_bin / "pg_dump", "--version")
    match = re.search(r"PostgreSQL\) (\d+)", version)
    if not match:
        raise RecoveryFailure("Could not identify the PostgreSQL tool version")
    with closing(psycopg2.connect(dsn)) as source:
        source.set_session(readonly=True, isolation_level="REPEATABLE READ")
        if source.server_version // 10000 != int(match[1]):
            raise RecoveryFailure("Use local PostgreSQL tools matching the source server's major version")
        with source.cursor() as cursor:
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot = cursor.fetchone()[0]
        before = fingerprint(source)
        with isolated_postgres(pg_bin) as (root, target_dsn):
            archive = root / "database.dump"
            dump_env = connection_environment(dsn)
            run_tool(pg_bin / "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                     "--snapshot", snapshot, "--file", str(archive), env=dump_env)
            run_tool(pg_bin / "pg_restore", "--no-owner", "--no-privileges", "--exit-on-error",
                     "--single-transaction", "--dbname", "postgres", str(archive),
                     env=connection_environment(target_dsn))
            with closing(psycopg2.connect(target_dsn)) as restored:
                after = fingerprint(restored)
            differences = compare(before, after)
            report = {"schemaVersion": "clef.postgres-recovery.v1", "ok": not differences,
                      "checkedAt": datetime.now(timezone.utc).isoformat(),
                      "postgresMajor": int(match[1]), "archiveBytes": archive.stat().st_size,
                      "sourceReadOnly": True, "restoreTarget": "disposable_local_socket",
                      "mismatchedSections": differences,
                      "mismatchedObjects": mismatched_objects(before, after), "evidence": before}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url-env", required=True)
    parser.add_argument("--pg-bin-dir", type=Path, required=True)
    parser.add_argument("--writes-paused", action="store_true", required=True,
                        help="Confirm API/worker/import writes are paused for sequence-state comparison")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = verify(source_dsn(os.environ.get(args.source_url_env, "")), args.pg_bin_dir)
    except (RecoveryFailure, psycopg2.Error) as error:
        report = {"schemaVersion": "clef.postgres-recovery.v1", "ok": False,
                  "error": str(error) if isinstance(error, RecoveryFailure) else
                  "Database verification failed; check access, schema compatibility and available disk space"}
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        # Avoid overwriting prior evidence and restrict even hash-only reports to the operator.
        with args.output.open("x", encoding="utf-8") as handle:
            os.chmod(args.output, 0o600)
            handle.write(rendered)
    print(rendered, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
