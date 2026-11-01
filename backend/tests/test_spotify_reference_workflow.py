import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "spotify_reference.py"
SPEC = importlib.util.spec_from_file_location("spotify_reference", SCRIPT)
spotify_reference = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(spotify_reference)


def test_normalize_isrc_accepts_punctuation_and_rejects_non_isrc() -> None:
    assert spotify_reference.normalize_isrc("US-ABC-26-00001") == "USABC2600001"
    with pytest.raises(spotify_reference.SpotifyReferenceError):
        spotify_reference.normalize_isrc("not-an-isrc")


def test_manifest_rejects_sparse_or_interrupted_aria2_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = "fixture.parquet"
    monkeypatch.setitem(spotify_reference.FILES, relative, 3)
    fixture = tmp_path / relative
    fixture.write_bytes(b"abc")
    resume_state = Path(f"{fixture}.aria2")
    resume_state.write_bytes(b"in-progress")
    record = spotify_reference._file_record(tmp_path, relative)
    assert record["observedBytes"] == 3
    assert record["inProgress"] is True
    assert record["validSize"] is False
    resume_state.unlink()
    assert spotify_reference._file_record(tmp_path, relative)["validSize"] is True


def test_rights_signal_projection_excludes_audio_and_delivery_fields() -> None:
    columns = set(spotify_reference.RIGHTS_SIGNAL_COLUMNS)
    assert {"licensor", "artist_roles", "has_lyrics", "sha256_original"} <= columns
    assert "prefixed_ogg_packet" not in columns
    assert "filename" not in columns
    assert not any(column.startswith("file_id_") for column in columns)


def _write_spotify_candidate_fixture(path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect()
    connection.execute(
        """
        COPY (
          SELECT 1::BIGINT AS input_row_number,
                 'USABC2600001'::VARCHAR AS isrc,
                 'spotify-track-1'::VARCHAR AS spotify_track_id,
                 'Fixture Track'::VARCHAR AS title,
                 ['Fixture Artist']::VARCHAR[] AS artist_names,
                 180000::BIGINT AS duration_ms,
                 'Fixture Album'::VARCHAR AS album_title,
                 'Fixture Label'::VARCHAR AS label,
                 '2026-01-01'::VARCHAR AS release_date,
                 1720000000::BIGINT AS fetched_at,
                 42::BIGINT AS track_popularity
        ) TO ? (FORMAT PARQUET)
        """,
        [str(path)],
    )
    connection.close()


def test_mlc_reconciliation_writes_review_candidates_without_accepting_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "spotify-candidates.parquet"
    output = tmp_path / "mlc-candidates.jsonl"
    _write_spotify_candidate_fixture(source)

    class FakeMLCError(RuntimeError):
        pass

    class FakeMLCClient:
        def search_recordings(self, *, isrc: str):
            assert isrc == "USABC2600001"
            return [
                {
                    "isrc": isrc,
                    "mlcSongCode": "WORK-1",
                    "artist": "Fixture Artist",
                    "title": "Fixture Track",
                }
            ]

        def get_works(self, mlc_song_codes: list[str]):
            assert mlc_song_codes == ["WORK-1"]
            return [
                {
                    "mlcSongCode": "WORK-1",
                    "iswc": "T1234567890",
                    "primaryTitle": "Fixture Work",
                }
            ]

    monkeypatch.setattr(
        spotify_reference,
        "_mlc_client_from_environment",
        lambda: (FakeMLCClient(), FakeMLCError, "https://public-api.themlc.com"),
    )
    result = spotify_reference.reconcile_mlc(
        SimpleNamespace(
            spotify_candidates=source,
            output_jsonl=output,
            max_isrcs=1,
            max_consecutive_errors=1,
            delay_seconds=0,
            execute=True,
            acknowledge_observed_only=True,
            replace=False,
        )
    )

    assert result == 0
    candidate = json.loads(output.read_text(encoding="utf-8").strip())
    assert candidate["status"] == "candidate_pending_review"
    assert candidate["candidate"] == {
        "isrc": "USABC2600001",
        "mlcSongCode": "WORK-1",
        "iswc": "T1234567890",
    }
    assert candidate["assertionType"] == "observed_cross_registry_candidate"
    assert candidate["authorityStatus"] == "unverified"
    assert candidate["permissionStatus"] == "unknown"
    assert candidate["reviewStatus"] == "pending"
    assert candidate["acceptedLinkWritten"] is False
    manifest = json.loads(
        output.with_suffix(".jsonl.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["iswcCandidates"] == 1
    assert manifest["complete"] is True


@pytest.mark.parametrize("failure", ["manifest_staging", "manifest_publication"])
def test_reconciliation_refresh_preserves_both_previous_files_on_failure(tmp_path, monkeypatch, failure):
    source = tmp_path / "synthetic.parquet"
    source.write_bytes(b"synthetic input")
    output = tmp_path / "candidates.jsonl"
    manifest = output.with_suffix(".jsonl.manifest.json")
    output.write_bytes(b'{"previous":"observation"}\n')
    manifest.write_bytes(b'{"previous":"manifest"}\n')
    old_pair = output.read_bytes(), manifest.read_bytes()
    monkeypatch.setattr(spotify_reference, "_spotify_candidate_rows", lambda *_: [{"isrc": "USABC2600001"}])
    fake_client = SimpleNamespace(search_recordings=lambda **_: [], get_works=lambda *_: [])
    monkeypatch.setattr(spotify_reference, "_mlc_client_from_environment", lambda: (fake_client, RuntimeError, "https://fixture.invalid"))
    write_text, replace = Path.write_text, spotify_reference.os.replace
    def fail_staging(path, *args, **kwargs):
        if path.name == manifest.name and path.parent != manifest.parent:
            raise OSError("synthetic staging failure")
        return write_text(path, *args, **kwargs)
    def fail_publication(src, dst):
        if Path(dst) == manifest:
            raise OSError("synthetic publication failure")
        return replace(src, dst)
    if failure == "manifest_staging": monkeypatch.setattr(Path, "write_text", fail_staging)
    else: monkeypatch.setattr(spotify_reference.os, "replace", fail_publication)
    with pytest.raises((OSError, spotify_reference.SpotifyReferenceError)):
        spotify_reference.reconcile_mlc(SimpleNamespace(
            spotify_candidates=source, output_jsonl=output, max_isrcs=1, max_consecutive_errors=1,
            delay_seconds=0, execute=True, acknowledge_observed_only=True, replace=True,
        ))
    assert (output.read_bytes(), manifest.read_bytes()) == old_pair
    assert list(tmp_path.glob(".clef-reference-*")) == []


def test_mlc_reconciliation_defaults_to_a_non_network_plan(tmp_path: Path) -> None:
    source = tmp_path / "spotify-candidates.parquet"
    output = tmp_path / "mlc-candidates.jsonl"
    _write_spotify_candidate_fixture(source)
    result = spotify_reference.reconcile_mlc(
        SimpleNamespace(
            spotify_candidates=source,
            output_jsonl=output,
            max_isrcs=1,
            max_consecutive_errors=1,
            delay_seconds=0,
            execute=False,
            acknowledge_observed_only=False,
            replace=False,
        )
    )
    assert result == 0
    assert output.exists() is False


def test_query_marks_spotify_rows_observed_and_never_supplies_iswc(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    parquet_root = tmp_path / "spotify_clean_parquet"
    parquet_root.mkdir()
    connection = duckdb.connect()
    connection.execute(
        """
        COPY (SELECT 1::BIGINT AS rowid, 'track-1'::VARCHAR AS id, 1720000000::BIGINT AS fetched_at,
                     'Fixture Track'::VARCHAR AS name, NULL::VARCHAR AS preview_url,
                     10::BIGINT AS album_rowid, 1::BIGINT AS track_number,
                     'USABC2600001'::VARCHAR AS external_id_isrc, 42::BIGINT AS popularity,
                     1::BIGINT AS available_markets_rowid, 1::BIGINT AS disc_number,
                     180000::BIGINT AS duration_ms, 0::BIGINT AS explicit)
        TO ? (FORMAT PARQUET)
        """,
        [str(parquet_root / "tracks.parquet")],
    )
    connection.execute(
        """
        COPY (SELECT 10::BIGINT AS rowid, 'album-1'::VARCHAR AS id,
                     1720000000::BIGINT AS fetched_at, 'Fixture Album'::VARCHAR AS name,
                     'album'::VARCHAR AS album_type, 1::BIGINT AS available_markets_rowid,
                     '123456789012'::VARCHAR AS external_id_upc, NULL::VARCHAR AS copyright_c,
                     NULL::VARCHAR AS copyright_p, 'Fixture Label'::VARCHAR AS label,
                     10::BIGINT AS popularity, '2026-01-01'::VARCHAR AS release_date,
                     'day'::VARCHAR AS release_date_precision, 1::BIGINT AS total_tracks,
                     NULL::VARCHAR AS external_id_amgid)
        TO ? (FORMAT PARQUET)
        """,
        [str(parquet_root / "albums.parquet")],
    )
    connection.execute(
        "COPY (SELECT 1::BIGINT AS track_rowid, 20::BIGINT AS artist_rowid) TO ? (FORMAT PARQUET)",
        [str(parquet_root / "track_artists.parquet")],
    )
    connection.execute(
        """
        COPY (SELECT 20::BIGINT AS rowid, 'artist-1'::VARCHAR AS id,
                     1720000000::BIGINT AS fetched_at, 'Fixture Artist'::VARCHAR AS name,
                     100::BIGINT AS followers_total, 20::BIGINT AS popularity)
        TO ? (FORMAT PARQUET)
        """,
        [str(parquet_root / "artists.parquet")],
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "query", "--data-dir", str(tmp_path), "--isrc", "US-ABC-26-00001"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["assertionType"] == "observed_catalog_metadata"
    assert payload["authorityStatus"] == "unverified"
    assert payload["iswc"] is None
    assert payload["iswcStatus"] == "not_provided_by_source"
    assert payload["results"][0]["title"] == "Fixture Track"
    assert payload["results"][0]["artist_names"] == ["Fixture Artist"]

    input_csv = tmp_path / "controlled-catalog.csv"
    input_csv.write_text("isrc,title\nUS-ABC-26-00001,Input Title\n", encoding="utf-8")
    output_parquet = tmp_path / "spotify-candidates.parquet"
    batch = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "match-catalog",
            "--data-dir",
            str(tmp_path),
            "--input-csv",
            str(input_csv),
            "--output-parquet",
            str(output_parquet),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert batch.returncode == 0, batch.stderr
    batch_manifest = json.loads(batch.stdout)
    assert batch_manifest["inputRows"] == 1
    assert batch_manifest["matchedInputRows"] == 1
    assert batch_manifest["unmatchedValidInputRows"] == 0
    assert batch_manifest["matchedRows"] == 1
    matched = connection.execute(
        "SELECT input_record, assertion_type, authority_status, iswc, iswc_status FROM read_parquet(?)",
        [str(output_parquet)],
    ).fetchone()
    assert matched == (
        '{"isrc":"US-ABC-26-00001","title":"Input Title"}',
        "observed_catalog_metadata",
        "unverified",
        None,
        "not_provided_by_source",
    )


def test_rights_signal_projection_preserves_only_observed_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    duckdb = pytest.importorskip("duckdb")
    source = tmp_path / "track-files.parquet"
    output = tmp_path / "rights-signals.parquet"
    connection = duckdb.connect()
    connection.execute(
        """
        COPY (
          SELECT 1::BIGINT AS rowid,
                 'track-1'::VARCHAR AS track_id,
                 1754092800000::BIGINT AS fetched_at,
                 'US'::VARCHAR AS session_country,
                 'original-hash'::VARCHAR AS sha256_original,
                 'embedded-hash'::VARCHAR AS sha256_with_embedded_meta,
                 'available'::VARCHAR AS status,
                 true::BOOLEAN AS isrc_has_download,
                 42::BIGINT AS track_popularity,
                 NULL::VARCHAR AS alternatives,
                 'en'::VARCHAR AS language_of_performance,
                 'primary'::VARCHAR AS artist_roles,
                 1::BIGINT AS has_lyrics,
                 'licensor-code'::VARCHAR AS licensor,
                 'Original Title'::VARCHAR AS original_title,
                 NULL::VARCHAR AS version_title,
                 NULL::VARCHAR AS content_ratings,
                 1234::BIGINT AS filesize_bytes,
                 'excluded-audio'::BLOB AS prefixed_ogg_packet,
                 'excluded-name'::VARCHAR AS filename
        ) TO ? (FORMAT PARQUET)
        """,
        [str(source)],
    )
    connection.close()
    monkeypatch.setattr(spotify_reference, "_signed_download_url", lambda _: str(source))
    result = spotify_reference.fetch_rights_signals(
        SimpleNamespace(
            acknowledge_source_risk=True,
            output_parquet=output,
            replace=False,
        )
    )
    assert result == 0
    manifest = json.loads(output.with_suffix(".parquet.manifest.json").read_text())
    assert manifest["sourceSnapshotSemantics"] == "dataset_label_not_hard_cutoff"
    assert manifest["assertionType"] == "observed_platform_signal"
    assert manifest["authorityStatus"] == "unverified"
    assert manifest["permissionStatus"] == "unknown"
    assert manifest["coverage"]["rows"] == 1
    assert manifest["coverage"]["rowsFetchedAfterSourceLabel"] == 1
    observed = duckdb.connect().execute(
        "SELECT assertion_type, authority_status, permission_status FROM read_parquet(?)",
        [str(output)],
    ).fetchone()
    assert observed == ("observed_platform_signal", "unverified", "unknown")
    columns = {
        row[0]
        for row in duckdb.connect().execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(output)]
        ).fetchall()
    }
    assert "prefixed_ogg_packet" not in columns
    assert "filename" not in columns


def _existing_output_pair(tmp_path: Path):
    output = tmp_path / "previous.parquet"
    manifest = output.with_suffix(".parquet.manifest.json")
    output.write_bytes(b"last successful artifact")
    manifest.write_bytes(b'{"generation":"previous"}\n')
    return output, manifest, output.read_bytes(), manifest.read_bytes()


@pytest.mark.parametrize("column", ["assertion_type", "authority_status", "permission_status"])
@pytest.mark.parametrize("bad_value", [None, "", "licensed"])
def test_rights_signal_validation_rejects_missing_or_changed_semantics(tmp_path, column, bad_value):
    _check_rights_signal_validation(tmp_path, column, bad_value)


def test_rights_signal_validation_accepts_intact_observed_labels(tmp_path):
    _check_rights_signal_validation(tmp_path, None, None)


def _check_rights_signal_validation(tmp_path, changed_column, changed_value):
    duckdb = pytest.importorskip("duckdb")
    output = tmp_path / "signals.parquet"
    labels = {"assertion_type": "observed_platform_signal", "authority_status": "unverified", "permission_status": "unknown"}
    modified = dict(labels)
    if changed_column:
        modified[changed_column] = changed_value
    projection = [
        f"NULL::{'BIGINT' if name in {'fetched_at', 'has_lyrics'} else 'VARCHAR'} AS {name}"
        for name in spotify_reference.RIGHTS_SIGNAL_COLUMNS
    ]
    with duckdb.connect() as connection:
        connection.execute(
            "COPY (SELECT " + ", ".join(projection) + ", semantic.* FROM "
            "(VALUES ($1::VARCHAR, $2::VARCHAR, $3::VARCHAR), ($4::VARCHAR, $5::VARCHAR, $6::VARCHAR)) "
            "AS semantic(assertion_type, authority_status, permission_status)) TO $7 (FORMAT PARQUET)",
            [*labels.values(), *modified.values(), str(output)],
        )
    original = output.read_bytes()
    sidecar = output.with_suffix(".parquet.manifest.json")
    sidecar.write_text('{"complete": true}')
    result = subprocess.run([sys.executable, str(SCRIPT), "validate-rights-signals", "--output-parquet", str(output)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == (1 if changed_column else 0), result.stderr
    report = json.loads(result.stdout)
    assert report["coverage"]["rows"] == 2
    assert report["coverage"]["invalidSemanticRows"] == (1 if changed_column else 0)
    assert report["complete"] is (changed_column is None)
    assert json.loads(sidecar.read_text())["complete"] is (changed_column is None)
    assert output.read_bytes() == original


@pytest.mark.parametrize("stage", ["url", "copy", "coverage"])
def test_failed_rights_signal_refresh_preserves_previous_pair(tmp_path, monkeypatch, stage):
    output, manifest, original, original_manifest = _existing_output_pair(tmp_path)
    def fail(*_args):
        raise spotify_reference.SpotifyReferenceError("injected source failure")
    if stage == "url":
        monkeypatch.setattr(spotify_reference, "_signed_download_url", fail)
    else:
        source = tmp_path / "malformed.parquet"
        source.write_bytes(b"invalid parquet")
        monkeypatch.setattr(spotify_reference, "_signed_download_url", lambda _: str(source))
        if stage == "coverage":
            class Connection:
                def __enter__(self): return self
                def __exit__(self, *_args): pass
                def execute(self, sql, args=None):
                    if "COPY (" in sql:
                        Path(args[0]).write_bytes(b"partial new artifact")
                    return self
            monkeypatch.setattr(spotify_reference, "_import_duckdb", lambda: SimpleNamespace(connect=Connection))
            monkeypatch.setattr(spotify_reference, "_rights_signal_coverage", fail)
    with pytest.raises(spotify_reference.SpotifyReferenceError):
        spotify_reference.fetch_rights_signals(SimpleNamespace(
            output_parquet=output, replace=True, acknowledge_source_risk=True,
        ))
    assert output.read_bytes() == original
    assert manifest.read_bytes() == original_manifest
    assert list(tmp_path.glob(".clef-reference-*")) == []


def test_failed_catalog_copy_preserves_previous_pair(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    output, manifest, original, original_manifest = _existing_output_pair(tmp_path)
    source = tmp_path / "catalog.csv"
    source.write_text("isrc\nUSABC2600001\n")
    for relative in spotify_reference.SCOPES["lookup"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"invalid parquet")
    with pytest.raises(duckdb.Error):
        spotify_reference.match_catalog(SimpleNamespace(data_dir=tmp_path, input_csv=source, output_parquet=output, replace=True))
    assert output.read_bytes() == original
    assert manifest.read_bytes() == original_manifest
    assert list(tmp_path.glob(".clef-reference-*")) == []


def test_manifest_publication_failure_restores_previous_data(tmp_path, monkeypatch):
    output, manifest, original, original_manifest = _existing_output_pair(tmp_path)
    replace = spotify_reference.os.replace
    def fail_manifest(source, destination):
        if Path(destination) == manifest:
            raise OSError("injected manifest publication failure")
        return replace(source, destination)
    monkeypatch.setattr(spotify_reference.os, "replace", fail_manifest)
    def produce(path):
        path.write_bytes(b"new data")
        return {"generation": "new"}
    with pytest.raises(spotify_reference.SpotifyReferenceError, match="preserved"):
        spotify_reference._replace_reference_result(output, replace=True, produce=produce)
    assert output.read_bytes() == original
    assert manifest.read_bytes() == original_manifest
    assert list(tmp_path.glob(".clef-reference-*")) == []


def test_successful_replacement_publishes_matching_manifest(tmp_path):
    output, manifest, _, _ = _existing_output_pair(tmp_path)
    def produce(path):
        path.write_bytes(b"new data")
        return {"generation": "new", "outputFile": path.name}
    assert spotify_reference._replace_reference_result(output, replace=True, produce=produce) == 0
    assert output.read_bytes() == b"new data"
    assert json.loads(manifest.read_text()) == {"generation": "new", "outputFile": output.name}
    assert list(tmp_path.glob(".clef-reference-*")) == []


def test_failed_rollback_retains_recovery_files(tmp_path, monkeypatch):
    output, manifest, original, original_manifest = _existing_output_pair(tmp_path)
    replace = spotify_reference.os.replace
    def fail_publication_and_rollback(source, destination):
        if Path(destination) == manifest or Path(source).parent.name == "previous":
            raise OSError("injected filesystem failure")
        return replace(source, destination)
    monkeypatch.setattr(spotify_reference.os, "replace", fail_publication_and_rollback)
    def produce(path):
        path.write_bytes(b"new data")
        return {"generation": "new"}
    with pytest.raises(spotify_reference.SpotifyReferenceError, match="recover the previous files"):
        spotify_reference._replace_reference_result(output, replace=True, produce=produce)
    recovery = list(tmp_path.glob(".clef-reference-*"))
    assert len(recovery) == 1
    assert (recovery[0] / "previous" / output.name).read_bytes() == original
    assert (recovery[0] / "previous" / manifest.name).read_bytes() == original_manifest
    assert manifest.read_bytes() == original_manifest
