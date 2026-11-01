#!/usr/bin/env python3
"""Fetch and query the July 2025 Spotify catalog metadata snapshot.

This workflow treats the snapshot as observed identification metadata only. It
must never create an authority claim, permission, licence, or ISWC assertion.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import urlparse


DATASET_HANDLE = "lordpatil/spotify-metadata-by-annas-archive/versions/5"
DATASET_OWNER = "lordpatil"
DATASET_SLUG = "spotify-metadata-by-annas-archive"
DATASET_VERSION = 5
SOURCE_SNAPSHOT = "2025-07"
SOURCE_SNAPSHOT_SEMANTICS = "dataset_label_not_hard_cutoff"
SOURCE_LABEL_END_MS = 1_754_006_399_999
MLC_CANDIDATE_SCHEMA = "clef.isrc-iswc-candidate.v1"
SOURCE_URL = "https://annas-archive.org/blog/backing-up-spotify.html"
MIRROR_URL = "https://www.kaggle.com/datasets/lordpatil/spotify-metadata-by-annas-archive"
RIGHTS_SIGNALS_SOURCE = "spotify_clean_track_files_parquet/track_files.parquet"
RIGHTS_SIGNAL_COLUMNS = (
    "rowid",
    "track_id",
    "fetched_at",
    "session_country",
    "sha256_original",
    "sha256_with_embedded_meta",
    "status",
    "isrc_has_download",
    "track_popularity",
    "alternatives",
    "language_of_performance",
    "artist_roles",
    "has_lyrics",
    "licensor",
    "original_title",
    "version_title",
    "content_ratings",
    "filesize_bytes",
)

FILES: dict[str, int] = {
    # Identifier lookup files come first so an interrupted catalog fetch still
    # reaches a useful state as early as possible.
    "spotify_clean_parquet/tracks.parquet": 23_765_997_881,
    "spotify_clean_parquet/albums.parquet": 4_643_662_352,
    "spotify_clean_parquet/track_artists.parquet": 1_748_148_722,
    "spotify_clean_parquet/artists.parquet": 645_825_492,
    "spotify_clean_parquet/album_images.parquet": 2_566_082_417,
    "spotify_clean_parquet/artist_albums.parquet": 666_443_131,
    "spotify_clean_parquet/artist_genres.parquet": 9_965_980,
    "spotify_clean_parquet/artist_images.parquet": 430_591_073,
    "spotify_clean_parquet/available_markets.parquet": 6_146_773,
    "spotify_artist_redirects.json": 282_155,
}

SCOPES = {
    "identifiers": ("spotify_clean_parquet/tracks.parquet",),
    "lookup": (
        "spotify_clean_parquet/tracks.parquet",
        "spotify_clean_parquet/albums.parquet",
        "spotify_clean_parquet/track_artists.parquet",
        "spotify_clean_parquet/artists.parquet",
    ),
    "catalog": tuple(FILES),
}

EXPECTED_COLUMNS = {
    "spotify_clean_parquet/album_images.parquet": {
        "album_rowid", "width", "height", "url",
    },
    "spotify_clean_parquet/tracks.parquet": {
        "rowid", "id", "fetched_at", "name", "preview_url", "album_rowid",
        "track_number", "external_id_isrc", "popularity",
        "available_markets_rowid", "disc_number", "duration_ms", "explicit",
    },
    "spotify_clean_parquet/albums.parquet": {
        "rowid", "id", "fetched_at", "name", "album_type",
        "available_markets_rowid", "external_id_upc", "copyright_c",
        "copyright_p", "label", "popularity", "release_date",
        "release_date_precision", "total_tracks", "external_id_amgid",
    },
    "spotify_clean_parquet/track_artists.parquet": {"track_rowid", "artist_rowid"},
    "spotify_clean_parquet/artist_albums.parquet": {
        "artist_rowid", "album_rowid", "is_appears_on",
        "is_implicit_appears_on", "index_in_album",
    },
    "spotify_clean_parquet/artist_genres.parquet": {"artist_rowid", "genre"},
    "spotify_clean_parquet/artist_images.parquet": {
        "artist_rowid", "width", "height", "url",
    },
    "spotify_clean_parquet/artists.parquet": {
        "rowid", "id", "fetched_at", "name", "followers_total", "popularity",
    },
    "spotify_clean_parquet/available_markets.parquet": {
        "rowid", "available_markets",
    },
}


class SpotifyReferenceError(RuntimeError):
    pass


def normalize_isrc(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}\d{7}", normalized):
        raise SpotifyReferenceError(f"Invalid ISRC: {value!r}")
    return normalized


def _import_kaggle() -> tuple[Any, Any]:
    try:
        from kagglehub.clients import build_kaggle_client
        from kagglesdk.datasets.types.dataset_api_service import ApiDownloadDatasetRequest
    except ImportError as error:
        raise SpotifyReferenceError(
            "Fetch requires kagglehub; install scripts/requirements-spotify-reference.txt"
        ) from error
    return build_kaggle_client, ApiDownloadDatasetRequest


def _import_duckdb() -> Any:
    try:
        import duckdb
    except ImportError as error:
        raise SpotifyReferenceError(
            "Query and schema validation require duckdb; install scripts/requirements-spotify-reference.txt"
        ) from error
    return duckdb


def _import_mlc_client() -> tuple[Any, Any]:
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    try:
        from services.mlc_client import MLCClient, MLCClientError
    except ImportError as error:
        raise SpotifyReferenceError(
            "MLC reconciliation requires the backend requests dependency"
        ) from error
    return MLCClient, MLCClientError


def _bounded_environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise SpotifyReferenceError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise SpotifyReferenceError(f"{name} must be between {minimum} and {maximum}")
    return value


def _mlc_client_from_environment() -> tuple[Any, type[Exception], str]:
    mlc_client, mlc_error = _import_mlc_client()
    capabilities = {
        value.strip()
        for value in os.getenv("MLC_AUTHORIZED_CAPABILITIES", "").split(",")
        if value.strip()
    }
    if "catalog_lookup" not in capabilities:
        raise SpotifyReferenceError(
            "MLC_AUTHORIZED_CAPABILITIES must explicitly include catalog_lookup"
        )
    username = os.getenv("MLC_USERNAME", "").strip()
    password = os.getenv("MLC_PASSWORD", "")
    if not username or not password:
        raise SpotifyReferenceError("MLC_USERNAME and MLC_PASSWORD are required")
    base_url = os.getenv("MLC_BASE_URL", "https://public-api.themlc.com").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SpotifyReferenceError("MLC_BASE_URL must be a credential-free HTTPS origin")
    client = mlc_client(
        username,
        password,
        base_url,
        connect_timeout_seconds=_bounded_environment_int(
            "MLC_CONNECT_TIMEOUT_SECONDS", 5, 1, 30
        ),
        read_timeout_seconds=_bounded_environment_int(
            "MLC_READ_TIMEOUT_SECONDS", 20, 1, 120
        ),
        max_retries=_bounded_environment_int("MLC_MAX_RETRIES", 3, 0, 8),
        max_response_bytes=_bounded_environment_int(
            "MLC_MAX_RESPONSE_BYTES", 5_000_000, 1024, 50_000_000
        ),
    )
    return client, mlc_error, base_url


def _signed_download_url(path: str) -> str:
    build_kaggle_client, request_type = _import_kaggle()
    request = request_type()
    request.owner_slug = DATASET_OWNER
    request.dataset_slug = DATASET_SLUG
    request.dataset_version_number = DATASET_VERSION
    request.file_name = path
    with build_kaggle_client() as client:
        response = client.datasets.dataset_api_client.download_dataset(request)
        response.raise_for_status()
        return response.url


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _allocated_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    stat = path.stat()
    blocks = getattr(stat, "st_blocks", None)
    return stat.st_size if blocks is None else blocks * 512


def _file_record(root: Path, relative: str, *, include_hash: bool = False) -> dict[str, Any]:
    path = root / relative
    aria2_state = Path(f"{path}.aria2")
    expected = FILES[relative]
    record: dict[str, Any] = {
        "path": relative,
        "expectedBytes": expected,
        "present": path.is_file(),
        "observedBytes": path.stat().st_size if path.is_file() else None,
        "allocatedBytes": _allocated_bytes(path) if path.is_file() else None,
        "inProgress": aria2_state.exists(),
    }
    record["validSize"] = record["observedBytes"] == expected and not record["inProgress"]
    if include_hash and record["validSize"]:
        record["sha256"] = _sha256(path)
    return record


def _write_manifest(root: Path, scope: str, *, include_hash: bool = False) -> dict[str, Any]:
    selected = SCOPES[scope]
    records = [_file_record(root, relative, include_hash=include_hash) for relative in selected]
    manifest = {
        "schemaVersion": 1,
        "dataset": DATASET_HANDLE,
        "datasetVersion": DATASET_VERSION,
        "sourceSnapshot": SOURCE_SNAPSHOT,
        "sourceSnapshotSemantics": SOURCE_SNAPSHOT_SEMANTICS,
        "sourceUrl": SOURCE_URL,
        "mirrorUrl": MIRROR_URL,
        "scope": scope,
        "assertionType": "observed_catalog_metadata",
        "authorityStatus": "unverified",
        "iswcCoverage": "not_provided_by_source",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": records,
        "complete": all(record["validSize"] for record in records),
    }
    manifest_path = root / "spotify-reference-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _fetch_file(root: Path, relative: str, aria2c: str) -> None:
    destination = root / relative
    aria2_state = Path(f"{destination}.aria2")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        destination.is_file()
        and destination.stat().st_size == FILES[relative]
        and not aria2_state.exists()
    ):
        print(f"verified {relative}", flush=True)
        return
    print(f"fetching {relative}", flush=True)
    url = _signed_download_url(relative)
    completed = subprocess.run(
        [
            aria2c,
            "--continue=true",
            "--max-connection-per-server=8",
            "--split=8",
            "--min-split-size=8M",
            "--file-allocation=none",
            "--console-log-level=warn",
            "--show-console-readout=false",
            "--summary-interval=0",
            f"--dir={destination.parent}",
            f"--out={destination.name}",
            url,
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise SpotifyReferenceError(f"Download failed for {relative} with exit {completed.returncode}")
    observed = destination.stat().st_size
    if observed != FILES[relative] or aria2_state.exists():
        raise SpotifyReferenceError(
            f"Incomplete download for {relative}: expected {FILES[relative]}, observed {observed}, "
            f"resume state present={aria2_state.exists()}"
        )
    print(f"downloaded {relative}", flush=True)


def fetch(args: argparse.Namespace) -> int:
    if not args.acknowledge_source_risk:
        raise SpotifyReferenceError(
            "Refusing bulk fetch without --acknowledge-source-risk; public availability does not settle reuse rights"
        )
    aria2c = shutil.which("aria2c")
    if not aria2c:
        raise SpotifyReferenceError("aria2c is required for resumable bulk downloads")
    root = args.data_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected = SCOPES[args.scope]
    remaining = sum(
        max(0, FILES[relative] - _allocated_bytes(root / relative))
        for relative in selected
    )
    free = shutil.disk_usage(root).free
    if free < remaining + 5 * 1024**3:
        raise SpotifyReferenceError(
            f"Insufficient free space: need {remaining + 5 * 1024**3:,} bytes, have {free:,}"
        )
    parallel_files = max(1, min(args.parallel_files, 4))
    with ThreadPoolExecutor(max_workers=parallel_files) as executor:
        futures = {
            executor.submit(_fetch_file, root, relative, aria2c): relative
            for relative in selected
        }
        for future in as_completed(futures):
            future.result()
    manifest = _write_manifest(root, args.scope, include_hash=args.hash)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def validate(args: argparse.Namespace) -> int:
    root = args.data_dir.expanduser().resolve()
    manifest = _write_manifest(root, args.scope, include_hash=args.hash)
    if args.schema:
        duckdb = _import_duckdb()
        connection = duckdb.connect()
        schema_errors: list[dict[str, Any]] = []
        row_counts: dict[str, int] = {}
        for relative, expected in EXPECTED_COLUMNS.items():
            if relative not in SCOPES[args.scope]:
                continue
            path = root / relative
            if not path.is_file() or path.stat().st_size != FILES[relative]:
                continue
            rows = connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
            observed = {row[0] for row in rows}
            row_counts[relative] = connection.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(path)]
            ).fetchone()[0]
            if observed != expected:
                schema_errors.append(
                    {"path": relative, "missing": sorted(expected - observed), "unexpected": sorted(observed - expected)}
                )
        manifest["schemaErrors"] = schema_errors
        manifest["rowCounts"] = row_counts
        manifest["complete"] = manifest["complete"] and not schema_errors
        (root / "spotify-reference-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["complete"] else 1


def query(args: argparse.Namespace) -> int:
    root = args.data_dir.expanduser().resolve()
    required = SCOPES["lookup"]
    missing = [relative for relative in required if not (root / relative).is_file()]
    if missing:
        raise SpotifyReferenceError(f"Lookup files are missing: {', '.join(missing)}")
    isrc = normalize_isrc(args.isrc)
    duckdb = _import_duckdb()
    connection = duckdb.connect()
    rows = connection.execute(
        """
        WITH target_tracks AS (
          SELECT *
          FROM read_parquet(?)
          WHERE upper(regexp_replace(external_id_isrc, '[^A-Za-z0-9]', '', 'g')) = ?
        ), artists_by_track AS (
          SELECT ta.track_rowid,
                 list(a.name ORDER BY ta.artist_rowid) AS artist_names,
                 list(a.id ORDER BY ta.artist_rowid) AS spotify_artist_ids
          FROM read_parquet(?) ta
          JOIN read_parquet(?) a ON a.rowid = ta.artist_rowid
          JOIN target_tracks t ON t.rowid = ta.track_rowid
          GROUP BY ta.track_rowid
        )
        SELECT t.id AS spotify_track_id,
               t.external_id_isrc AS isrc,
               t.name AS title,
               ab.artist_names,
               ab.spotify_artist_ids,
               t.duration_ms,
               t.explicit,
               t.popularity AS track_popularity,
               t.track_number,
               t.disc_number,
               al.id AS spotify_album_id,
               al.name AS album_title,
               al.album_type,
               al.external_id_upc AS upc,
               al.label,
               al.release_date,
               al.release_date_precision,
               al.copyright_c,
               al.copyright_p,
               t.fetched_at
        FROM target_tracks t
        LEFT JOIN read_parquet(?) al ON al.rowid = t.album_rowid
        LEFT JOIN artists_by_track ab ON ab.track_rowid = t.rowid
        ORDER BY t.popularity DESC NULLS LAST, t.id
        """,
        [
            str(root / "spotify_clean_parquet/tracks.parquet"),
            isrc,
            str(root / "spotify_clean_parquet/track_artists.parquet"),
            str(root / "spotify_clean_parquet/artists.parquet"),
            str(root / "spotify_clean_parquet/albums.parquet"),
        ],
    ).fetchall()
    columns = [item[0] for item in connection.description]
    payload = {
        "query": {"isrc": isrc},
        "source": {
            "dataset": DATASET_HANDLE,
            "sourceSnapshot": SOURCE_SNAPSHOT,
            "sourceSnapshotSemantics": SOURCE_SNAPSHOT_SEMANTICS,
            "sourceUrl": SOURCE_URL,
            "mirrorUrl": MIRROR_URL,
        },
        "assertionType": "observed_catalog_metadata",
        "authorityStatus": "unverified",
        "iswc": None,
        "iswcStatus": "not_provided_by_source",
        "results": [dict(zip(columns, row)) for row in rows],
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def _replace_reference_result(output: Path, *, replace: bool, produce: Any) -> int:
    """Prepare data and metadata before touching the previous successful pair."""
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    if not replace and (output.exists() or manifest_path.exists()):
        raise SpotifyReferenceError("Output or manifest already exists; pass --replace to overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".clef-reference-", dir=output.parent))
    retain_recovery = False
    try:
        candidate = staging / output.name
        manifest = produce(candidate)
        candidate_manifest = staging / manifest_path.name
        candidate_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # Hard links retain the old files without copying potentially large datasets.
        backup = staging / "previous"
        backup.mkdir()
        previous_data = backup / output.name
        previous_manifest = backup / manifest_path.name
        had_data = output.exists()
        if not replace and (had_data or manifest_path.exists()):
            raise SpotifyReferenceError("Output appeared during generation; refusing to overwrite")
        if had_data:
            os.link(output, previous_data)
        if manifest_path.exists():
            os.link(manifest_path, previous_manifest)
        os.replace(candidate, output)
        try:
            os.replace(candidate_manifest, manifest_path)
        except OSError as error:
            try:
                if had_data:
                    os.replace(previous_data, output)
                else:
                    output.unlink()
            except OSError as recovery_error:
                retain_recovery = True
                raise SpotifyReferenceError(f"Publication failed; recover the previous files from {staging}") from recovery_error
            raise SpotifyReferenceError("Publication failed; previous output and manifest were preserved") from error
    finally:
        if not retain_recovery:
            shutil.rmtree(staging)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def match_catalog(args: argparse.Namespace) -> int:
    root = args.data_dir.expanduser().resolve()
    source = args.input_csv.expanduser().resolve()
    output = args.output_parquet.expanduser().resolve()
    if not source.is_file():
        raise SpotifyReferenceError(f"Input CSV does not exist: {source}")
    if output.suffix.lower() != ".parquet":
        raise SpotifyReferenceError("Matched catalog output must use a .parquet extension")
    if output.exists() and not args.replace:
        raise SpotifyReferenceError(f"Output already exists; pass --replace to overwrite: {output}")
    required = SCOPES["lookup"]
    missing = [relative for relative in required if not (root / relative).is_file()]
    if missing:
        raise SpotifyReferenceError(f"Lookup files are missing: {', '.join(missing)}")
    return _replace_reference_result(output, replace=args.replace, produce=lambda staged: _match_catalog_data(root, source, staged))


def _match_catalog_data(root: Path, source: Path, output: Path) -> dict[str, Any]:
    duckdb = _import_duckdb()
    with duckdb.connect() as connection:
        input_schema = connection.execute(
            "DESCRIBE SELECT * FROM read_csv_auto(?, header=true, all_varchar=true)",
            [str(source)],
        ).fetchall()
        if "isrc" not in {str(row[0]).lower() for row in input_schema}:
            raise SpotifyReferenceError("Input CSV must contain an isrc column")
        connection.execute(
            """
            COPY (
              WITH supplied AS (
                SELECT row_number() OVER () AS input_row_number,
                       source_row.isrc AS supplied_isrc,
                       upper(regexp_replace(source_row.isrc, '[^A-Za-z0-9]', '', 'g')) AS normalized_isrc,
                       to_json(source_row) AS input_record
                FROM read_csv_auto(?, header=true, all_varchar=true) AS source_row
              ), target_tracks AS (
                SELECT supplied.input_row_number,
                       supplied.supplied_isrc,
                       supplied.normalized_isrc,
                       supplied.input_record,
                       tracks.*
                FROM supplied
                JOIN read_parquet(?) tracks
                  ON upper(regexp_replace(tracks.external_id_isrc, '[^A-Za-z0-9]', '', 'g'))
                     = supplied.normalized_isrc
                WHERE regexp_matches(supplied.normalized_isrc, '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$')
              ), artists_by_track AS (
                SELECT ta.track_rowid,
                       list(a.name ORDER BY ta.artist_rowid) AS artist_names,
                       list(a.id ORDER BY ta.artist_rowid) AS spotify_artist_ids
                FROM read_parquet(?) ta
                JOIN read_parquet(?) a ON a.rowid = ta.artist_rowid
                JOIN (SELECT DISTINCT rowid FROM target_tracks) t ON t.rowid = ta.track_rowid
                GROUP BY ta.track_rowid
              )
              SELECT t.input_row_number,
                     t.supplied_isrc,
                     t.normalized_isrc AS isrc,
                     t.input_record,
                     t.id AS spotify_track_id,
                     t.name AS title,
                     ab.artist_names,
                     ab.spotify_artist_ids,
                     t.duration_ms,
                     t.explicit,
                     t.popularity AS track_popularity,
                     t.track_number,
                     t.disc_number,
                     al.id AS spotify_album_id,
                     al.name AS album_title,
                     al.album_type,
                     al.external_id_upc AS upc,
                     al.label,
                     al.release_date,
                     al.release_date_precision,
                     al.copyright_c,
                     al.copyright_p,
                     t.fetched_at,
                     'observed_catalog_metadata' AS assertion_type,
                     'unverified' AS authority_status,
                     NULL::VARCHAR AS iswc,
                     'not_provided_by_source' AS iswc_status
              FROM target_tracks t
              LEFT JOIN read_parquet(?) al ON al.rowid = t.album_rowid
              LEFT JOIN artists_by_track ab ON ab.track_rowid = t.rowid
              ORDER BY t.input_row_number, t.popularity DESC NULLS LAST, t.id
            ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
            """,
            [
                # DuckDB binds COPY's target parameter before parameters inside
                # the SELECT body, regardless of textual position.
                str(output),
                str(source),
                str(root / "spotify_clean_parquet/tracks.parquet"),
                str(root / "spotify_clean_parquet/track_artists.parquet"),
                str(root / "spotify_clean_parquet/artists.parquet"),
                str(root / "spotify_clean_parquet/albums.parquet"),
            ],
        )
        input_rows, valid_input_rows = connection.execute(
            """
            SELECT count(*),
                   count(*) FILTER (
                     WHERE regexp_matches(
                       upper(regexp_replace(isrc, '[^A-Za-z0-9]', '', 'g')),
                       '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$'
                     )
                   )
            FROM read_csv_auto(?, header=true, all_varchar=true)
            """,
            [str(source)],
        ).fetchone()
        matched_rows, matched_input_rows = connection.execute(
            "SELECT count(*), count(DISTINCT input_row_number) FROM read_parquet(?)",
            [str(output)],
        ).fetchone()
        manifest = {
            "schemaVersion": 1,
            "sourceDataset": DATASET_HANDLE,
            "sourceSnapshot": SOURCE_SNAPSHOT,
            "sourceSnapshotSemantics": SOURCE_SNAPSHOT_SEMANTICS,
            "inputSha256": _sha256(source),
            "outputFile": output.name,
            "inputRows": input_rows,
            "validInputRows": valid_input_rows,
            "invalidInputRows": input_rows - valid_input_rows,
            "matchedRows": matched_rows,
            "matchedInputRows": matched_input_rows,
            "unmatchedValidInputRows": valid_input_rows - matched_input_rows,
            "assertionType": "observed_catalog_metadata",
            "authorityStatus": "unverified",
            "iswcCoverage": "not_provided_by_source",
            "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        return manifest

def _spotify_candidate_rows(source: Path, max_isrcs: int) -> list[dict[str, Any]]:
    duckdb = _import_duckdb()
    connection = duckdb.connect()
    observed_columns = {
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(source)]
        ).fetchall()
    }
    required_columns = {
        "input_row_number",
        "isrc",
        "spotify_track_id",
        "title",
        "artist_names",
        "duration_ms",
        "album_title",
        "label",
        "release_date",
        "fetched_at",
    }
    missing = required_columns - observed_columns
    if missing:
        raise SpotifyReferenceError(
            "Spotify candidate file is missing columns: " + ", ".join(sorted(missing))
        )
    rows = connection.execute(
        """
        WITH ranked AS (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY isrc
                   ORDER BY track_popularity DESC NULLS LAST, spotify_track_id
                 ) AS candidate_rank
          FROM read_parquet(?)
          WHERE regexp_matches(isrc, '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$')
        )
        SELECT input_row_number, isrc, spotify_track_id, title, artist_names,
               duration_ms, album_title, label, release_date, fetched_at
        FROM ranked
        WHERE candidate_rank = 1
        ORDER BY input_row_number, isrc
        LIMIT ?
        """,
        [str(source), max_isrcs],
    ).fetchall()
    columns = [item[0] for item in connection.description]
    connection.close()
    return [dict(zip(columns, row)) for row in rows]


def _first_text(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _mlc_candidate_record(
    *,
    spotify: dict[str, Any],
    status: str,
    recording: dict[str, Any] | None = None,
    work: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    recording = recording or {}
    work = work or {}
    song_code = _first_text(
        work, "mlcSongCode", "mlcsongCode"
    ) or _first_text(recording, "mlcSongCode", "mlcsongCode")
    iswc = _first_text(work, "iswc")
    record: dict[str, Any] = {
        "schemaVersion": MLC_CANDIDATE_SCHEMA,
        "status": status,
        "candidate": {
            "isrc": spotify["isrc"],
            "mlcSongCode": song_code,
            "iswc": iswc,
        },
        "spotifyObservation": spotify,
        "mlcRecordingObservation": recording or None,
        "mlcWorkObservation": work or None,
        "assertionType": "observed_cross_registry_candidate",
        "authorityStatus": "unverified",
        "permissionStatus": "unknown",
        "reviewStatus": "pending" if iswc else "not_ready",
        "acceptedLinkWritten": False,
    }
    if error is not None:
        record["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    return record


def reconcile_mlc(args: argparse.Namespace) -> int:
    source = args.spotify_candidates.expanduser().resolve()
    output = args.output_jsonl.expanduser().resolve()
    if not source.is_file():
        raise SpotifyReferenceError(f"Spotify candidate file does not exist: {source}")
    if output.suffix.lower() not in {".jsonl", ".ndjson"}:
        raise SpotifyReferenceError("MLC candidate output must use .jsonl or .ndjson")
    if not 1 <= args.max_isrcs <= 1_000:
        raise SpotifyReferenceError("--max-isrcs must be between 1 and 1000")
    if not 1 <= args.max_consecutive_errors <= 20:
        raise SpotifyReferenceError("--max-consecutive-errors must be between 1 and 20")
    if not 0 <= args.delay_seconds <= 60:
        raise SpotifyReferenceError("--delay-seconds must be between 0 and 60")
    if output.exists() and not args.replace:
        raise SpotifyReferenceError(f"Output already exists; pass --replace to overwrite: {output}")

    spotify_rows = _spotify_candidate_rows(source, args.max_isrcs)
    plan = {
        "schemaVersion": 1,
        "sourceFile": str(source),
        "inputSha256": _sha256(source),
        "selectedUniqueIsrcs": len(spotify_rows),
        "maximumIsrcs": args.max_isrcs,
        "assertionType": "observed_cross_registry_candidate",
        "authorityStatus": "unverified",
        "permissionStatus": "unknown",
        "humanReviewRequired": True,
        "acceptedLinksWritten": 0,
        "liveExecution": bool(args.execute),
    }
    if not args.execute:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    if not args.acknowledge_observed_only:
        raise SpotifyReferenceError(
            "Refusing live MLC reconciliation without --acknowledge-observed-only"
        )

    client, mlc_error, base_url = _mlc_client_from_environment()
    output_rows: list[dict[str, Any]] = []
    recording_pairs: list[tuple[dict[str, Any], dict[str, Any], str | None]] = []
    api_errors = 0
    consecutive_errors = 0
    attempted_isrcs = 0
    stopped_early = False

    for index, spotify in enumerate(spotify_rows):
        attempted_isrcs += 1
        try:
            recordings = client.search_recordings(isrc=spotify["isrc"])
            consecutive_errors = 0
        except mlc_error as error:
            api_errors += 1
            consecutive_errors += 1
            output_rows.append(
                _mlc_candidate_record(
                    spotify=spotify,
                    status="recording_lookup_error",
                    error=error,
                )
            )
            if consecutive_errors >= args.max_consecutive_errors:
                stopped_early = index + 1 < len(spotify_rows)
                break
        else:
            if not recordings:
                output_rows.append(
                    _mlc_candidate_record(
                        spotify=spotify,
                        status="no_recording_match",
                    )
                )
            for recording in recordings:
                song_code = _first_text(recording, "mlcSongCode", "mlcsongCode")
                recording_pairs.append((spotify, recording, song_code))
        if args.delay_seconds and index + 1 < len(spotify_rows):
            time.sleep(args.delay_seconds)

    work_by_code: dict[str, list[dict[str, Any]]] = {}
    work_errors: dict[str, Exception] = {}
    song_codes = list(
        dict.fromkeys(
            song_code
            for _, _, song_code in recording_pairs
            if song_code is not None
        )
    )
    for start in range(0, len(song_codes), 100):
        chunk = song_codes[start : start + 100]
        try:
            works = client.get_works(chunk)
        except mlc_error as error:
            api_errors += 1
            for song_code in chunk:
                work_errors[song_code] = error
            continue
        for work in works:
            song_code = _first_text(work, "mlcSongCode", "mlcsongCode")
            if song_code:
                work_by_code.setdefault(song_code, []).append(work)

    for spotify, recording, song_code in recording_pairs:
        if song_code is None:
            output_rows.append(
                _mlc_candidate_record(
                    spotify=spotify,
                    recording=recording,
                    status="recording_without_work_link",
                )
            )
            continue
        if song_code in work_errors:
            output_rows.append(
                _mlc_candidate_record(
                    spotify=spotify,
                    recording=recording,
                    status="work_lookup_error",
                    error=work_errors[song_code],
                )
            )
            continue
        works = work_by_code.get(song_code, [])
        if not works:
            output_rows.append(
                _mlc_candidate_record(
                    spotify=spotify,
                    recording=recording,
                    status="work_not_found",
                )
            )
            continue
        for work in works:
            output_rows.append(
                _mlc_candidate_record(
                    spotify=spotify,
                    recording=recording,
                    work=work,
                    status=(
                        "candidate_pending_review"
                        if _first_text(work, "iswc")
                        else "work_without_iswc"
                    ),
                )
            )

    status_counts: dict[str, int] = {}
    for row in output_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    manifest = {
        **plan,
        "outputFile": output.name,
        "mlcBaseUrl": base_url,
        "attemptedIsrcs": attempted_isrcs,
        "recordingObservations": len(recording_pairs),
        "workCodesRequested": len(song_codes),
        "iswcCandidates": sum(
            1 for row in output_rows if row["candidate"]["iswc"] is not None
        ),
        "apiErrors": api_errors,
        "stoppedEarly": stopped_early,
        "statusCounts": status_counts,
        "complete": not api_errors and attempted_isrcs == len(spotify_rows),
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    def produce(staged_output: Path) -> dict[str, Any]:
        with staged_output.open("w", encoding="utf-8") as handle:
            for row in output_rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        return {**manifest, "outputSha256": _sha256(staged_output)}

    _replace_reference_result(output, replace=args.replace, produce=produce)
    return 0 if manifest["complete"] else 1


def fetch_rights_signals(args: argparse.Namespace) -> int:
    if not args.acknowledge_source_risk:
        raise SpotifyReferenceError(
            "Refusing rights-signal extraction without --acknowledge-source-risk"
        )
    output = args.output_parquet.expanduser().resolve()
    if output.suffix.lower() != ".parquet":
        raise SpotifyReferenceError("Rights-signal output must use a .parquet extension")
    if output.exists() and not args.replace:
        raise SpotifyReferenceError(f"Output already exists; pass --replace to overwrite: {output}")
    return _replace_reference_result(output, replace=args.replace, produce=_fetch_rights_signals_data)


def _fetch_rights_signals_data(output: Path) -> dict[str, Any]:
    source_url = _signed_download_url(RIGHTS_SIGNALS_SOURCE)
    duckdb = _import_duckdb()
    with duckdb.connect() as connection:
        projection = ", ".join(f'"{column}"' for column in RIGHTS_SIGNAL_COLUMNS)
        try:
            with tempfile.TemporaryDirectory(prefix=".clef-duckdb-", dir=output.parent) as temp_dir:
                connection.execute("SET memory_limit = '8GB'")
                connection.execute("SET threads = 4")
                connection.execute("SET preserve_insertion_order = false")
                connection.execute("SET temp_directory = ?", [temp_dir])
                connection.execute(
                    f"""
                    COPY (
                      SELECT {projection},
                             'observed_platform_signal' AS assertion_type,
                             'unverified' AS authority_status,
                             'unknown' AS permission_status
                      FROM read_parquet(?)
                    ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
                    """,
                    # DuckDB binds COPY's target parameter before parameters inside
                    # the SELECT body, regardless of textual position.
                    [str(output), source_url],
                )
        except Exception as error:
            output.unlink(missing_ok=True)
            raise SpotifyReferenceError("Rights-signal projection failed") from error
        coverage = _rights_signal_coverage(connection, output)
        manifest = {
            "schemaVersion": 1,
            "sourceDataset": DATASET_HANDLE,
            "sourceSnapshot": SOURCE_SNAPSHOT,
            "sourceSnapshotSemantics": SOURCE_SNAPSHOT_SEMANTICS,
            "sourceFile": RIGHTS_SIGNALS_SOURCE,
            "outputFile": output.name,
            "outputBytes": output.stat().st_size,
            "rowCount": coverage["rows"],
            "coverage": coverage,
            "columns": list(RIGHTS_SIGNAL_COLUMNS),
            "excludedBinaryColumns": ["prefixed_ogg_packet"],
            "assertionType": "observed_platform_signal",
            "authorityStatus": "unverified",
            "permissionStatus": "unknown",
            "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        return manifest

def _rights_signal_coverage(connection: Any, output: Path) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT count(*) AS rows,
               count(track_id) AS rows_with_track_id,
               count(licensor) AS rows_with_licensor,
               count(artist_roles) AS rows_with_artist_roles,
               count(language_of_performance) AS rows_with_language,
               count(*) FILTER (WHERE has_lyrics = 1) AS rows_with_lyrics,
               count(sha256_original) AS rows_with_original_hash,
               count(sha256_with_embedded_meta) AS rows_with_embedded_hash,
               min(fetched_at) AS min_fetched_at_ms,
               max(fetched_at) AS max_fetched_at_ms,
               count(*) FILTER (WHERE fetched_at > ?) AS rows_fetched_after_source_label,
               count(*) FILTER (
                 WHERE assertion_type IS DISTINCT FROM 'observed_platform_signal'
                    OR authority_status IS DISTINCT FROM 'unverified'
                    OR permission_status IS DISTINCT FROM 'unknown'
               ) AS invalid_semantic_rows
        FROM read_parquet(?)
        """,
        [SOURCE_LABEL_END_MS, str(output)],
    ).fetchone()
    names = (
        "rows",
        "rowsWithTrackId",
        "rowsWithLicensor",
        "rowsWithArtistRoles",
        "rowsWithLanguage",
        "rowsWithLyrics",
        "rowsWithOriginalHash",
        "rowsWithEmbeddedHash",
        "minFetchedAtMs",
        "maxFetchedAtMs",
        "rowsFetchedAfterSourceLabel",
        "invalidSemanticRows",
    )
    return dict(zip(names, row))


def validate_rights_signals(args: argparse.Namespace) -> int:
    output = args.output_parquet.expanduser().resolve()
    if not output.is_file():
        raise SpotifyReferenceError(f"Rights-signal file does not exist: {output}")
    duckdb = _import_duckdb()
    connection = duckdb.connect()
    observed_columns = {
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(output)]
        ).fetchall()
    }
    expected_columns = set(RIGHTS_SIGNAL_COLUMNS) | {
        "assertion_type",
        "authority_status",
        "permission_status",
    }
    coverage = _rights_signal_coverage(connection, output)
    schema_errors = {
        "missing": sorted(expected_columns - observed_columns),
        "unexpected": sorted(observed_columns - expected_columns),
    }
    complete = not schema_errors["missing"] and not schema_errors["unexpected"] and not coverage["invalidSemanticRows"]
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {
            "schemaVersion": 1,
            "sourceDataset": DATASET_HANDLE,
            "sourceSnapshot": SOURCE_SNAPSHOT,
            "sourceSnapshotSemantics": SOURCE_SNAPSHOT_SEMANTICS,
            "sourceFile": RIGHTS_SIGNALS_SOURCE,
            "outputFile": output.name,
        }
    )
    manifest.update(
        {
            "sourceSnapshotSemantics": SOURCE_SNAPSHOT_SEMANTICS,
            "outputBytes": output.stat().st_size,
            "rowCount": coverage["rows"],
            "coverage": coverage,
            "schemaErrors": schema_errors,
            "complete": complete,
            "validatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if complete else 1


def isrc_statistics(args: argparse.Namespace) -> int:
    root = args.data_dir.expanduser().resolve()
    tracks = root / "spotify_clean_parquet/tracks.parquet"
    tracks_state = Path(f"{tracks}.aria2")
    if (
        not tracks.is_file()
        or tracks.stat().st_size != FILES["spotify_clean_parquet/tracks.parquet"]
        or tracks_state.exists()
    ):
        raise SpotifyReferenceError("The complete validated track table is required")
    duckdb = _import_duckdb()
    with tempfile.TemporaryDirectory(prefix=".clef-isrc-stats-", dir=root) as temp_dir:
        connection = duckdb.connect()
        connection.execute("SET memory_limit = '8GB'")
        connection.execute("SET threads = 8")
        connection.execute("SET temp_directory = ?", [temp_dir])
        row = connection.execute(
            """
            WITH normalized AS (
              SELECT external_id_isrc,
                     upper(regexp_replace(external_id_isrc, '[^A-Za-z0-9]', '', 'g')) AS isrc
              FROM read_parquet(?)
            )
            SELECT count(*) AS total_rows,
                   count(external_id_isrc) AS rows_with_isrc,
                   count(*) FILTER (WHERE external_id_isrc IS NULL) AS rows_without_isrc,
                   count(*) FILTER (
                     WHERE external_id_isrc IS NOT NULL
                       AND regexp_matches(isrc, '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$')
                   ) AS rows_with_valid_normalized_isrc,
                   count(*) FILTER (
                     WHERE external_id_isrc IS NOT NULL
                       AND NOT regexp_matches(isrc, '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$')
                   ) AS invalid_isrc_rows,
                   count(DISTINCT external_id_isrc) FILTER (
                     WHERE external_id_isrc IS NOT NULL
                   ) AS exact_unique_observed_isrcs,
                   count(DISTINCT isrc) FILTER (
                     WHERE regexp_matches(isrc, '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$')
                   ) AS exact_unique_valid_normalized_isrcs,
                   count(DISTINCT isrc) FILTER (
                     WHERE external_id_isrc IS NOT NULL
                       AND NOT regexp_matches(isrc, '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$')
                   ) AS exact_unique_invalid_normalized_values
            FROM normalized
            """,
            [str(tracks)],
        ).fetchone()
        track_temporal = connection.execute(
            """
            SELECT min(fetched_at), max(fetched_at),
                   count(*) FILTER (WHERE fetched_at > ?)
            FROM read_parquet(?)
            """,
            [SOURCE_LABEL_END_MS, str(tracks)],
        ).fetchone()
        albums = root / "spotify_clean_parquet/albums.parquet"
        album_temporal = None
        if (
            albums.is_file()
            and albums.stat().st_size == FILES["spotify_clean_parquet/albums.parquet"]
            and not Path(f"{albums}.aria2").exists()
        ):
            album_temporal = connection.execute(
                """
                SELECT min(fetched_at), max(fetched_at),
                       count(*) FILTER (WHERE fetched_at > ?)
                FROM read_parquet(?)
                """,
                [SOURCE_LABEL_END_MS, str(albums)],
            ).fetchone()
        connection.close()
    names = (
        "totalRows",
        "rowsWithIsrc",
        "rowsWithoutIsrc",
        "rowsWithValidNormalizedIsrc",
        "invalidIsrcRows",
        "exactUniqueObservedIsrcs",
        "exactUniqueValidNormalizedIsrcs",
        "exactUniqueInvalidNormalizedValues",
    )
    statistics = dict(zip(names, row))
    statistics["duplicateValidNormalizedIsrcRows"] = (
        statistics["rowsWithValidNormalizedIsrc"]
        - statistics["exactUniqueValidNormalizedIsrcs"]
    )
    temporal_coverage = {
        "sourceLabel": SOURCE_SNAPSHOT,
        "sourceLabelSemantics": SOURCE_SNAPSHOT_SEMANTICS,
        "tracks": {
            "minFetchedAtMs": track_temporal[0],
            "maxFetchedAtMs": track_temporal[1],
            "rowsFetchedAfterSourceLabel": track_temporal[2],
        },
    }
    if album_temporal is not None:
        temporal_coverage["albums"] = {
            "minFetchedAtMs": album_temporal[0],
            "maxFetchedAtMs": album_temporal[1],
            "rowsFetchedAfterSourceLabel": album_temporal[2],
        }
    manifest_path = root / "spotify-reference-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = _write_manifest(root, "catalog")
    manifest["isrcStatistics"] = statistics
    manifest["sourceSnapshotSemantics"] = SOURCE_SNAPSHOT_SEMANTICS
    manifest["temporalCoverage"] = temporal_coverage
    manifest["statisticsGeneratedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(statistics, indent=2, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("fetch", "validate"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path, required=True)
        command.add_argument("--scope", choices=tuple(SCOPES), default="catalog")
        command.add_argument("--hash", action="store_true", help="SHA-256 every complete file")
        if name == "fetch":
            command.add_argument("--acknowledge-source-risk", action="store_true")
            command.add_argument(
                "--parallel-files",
                type=int,
                choices=range(1, 5),
                default=3,
                metavar="1-4",
                help="download this many source files concurrently (default: 3)",
            )
            command.set_defaults(func=fetch)
        else:
            command.add_argument("--schema", action="store_true")
            command.set_defaults(func=validate)
    lookup = commands.add_parser("query")
    lookup.add_argument("--data-dir", type=Path, required=True)
    lookup.add_argument("--isrc", required=True)
    lookup.set_defaults(func=query)
    batch = commands.add_parser("match-catalog")
    batch.add_argument("--data-dir", type=Path, required=True)
    batch.add_argument("--input-csv", type=Path, required=True)
    batch.add_argument("--output-parquet", type=Path, required=True)
    batch.add_argument("--replace", action="store_true")
    batch.set_defaults(func=match_catalog)
    reconciliation = commands.add_parser("reconcile-mlc")
    reconciliation.add_argument("--spotify-candidates", type=Path, required=True)
    reconciliation.add_argument("--output-jsonl", type=Path, required=True)
    reconciliation.add_argument("--max-isrcs", type=int, default=100)
    reconciliation.add_argument("--max-consecutive-errors", type=int, default=3)
    reconciliation.add_argument("--delay-seconds", type=float, default=1.0)
    reconciliation.add_argument("--execute", action="store_true")
    reconciliation.add_argument("--acknowledge-observed-only", action="store_true")
    reconciliation.add_argument("--replace", action="store_true")
    reconciliation.set_defaults(func=reconcile_mlc)
    signals = commands.add_parser("fetch-rights-signals")
    signals.add_argument("--output-parquet", type=Path, required=True)
    signals.add_argument("--acknowledge-source-risk", action="store_true")
    signals.add_argument("--replace", action="store_true")
    signals.set_defaults(func=fetch_rights_signals)
    signal_validation = commands.add_parser("validate-rights-signals")
    signal_validation.add_argument("--output-parquet", type=Path, required=True)
    signal_validation.set_defaults(func=validate_rights_signals)
    statistics = commands.add_parser("isrc-statistics")
    statistics.add_argument("--data-dir", type=Path, required=True)
    statistics.set_defaults(func=isrc_statistics)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except SpotifyReferenceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
