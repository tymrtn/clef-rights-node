import importlib.util
import json
from pathlib import Path
import pytest

SPEC = importlib.util.spec_from_file_location("catalog_overlap_analysis", Path(__file__).resolve().parents[2] / "scripts/catalog_overlap_analysis.py")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_iswc_validates_checksum_and_normalizes_display_format():
    # Example identifier published by the ISWC International Agency.
    assert analysis.normalized_iswc("T-034.524.680-1") == "T0345246801"
    assert analysis.normalized_iswc("T0345246802") is None
    assert analysis.normalized_iswc("T123") is None
    assert analysis.normalized_iswc(None) is None


def test_overlap_excludes_wrong_or_missing_isrc_and_counts_unique_identifiers():
    sample = [{"isrc": "USABC2600001", "cohort": "popular", "selection_title": "Example"}]
    def observation(isrc, code="ONE", iswc="T0345246801"):
        return {"candidate": {"isrc": "USABC2600001", "mlcSongCode": code, "iswc": iswc}, "status": "candidate_pending_review", "mlcRecordingObservation": {"isrc": isrc, "title": "Example", "artist": "Artist"}, "mlcWorkObservation": {"mlcSongCode": code}}
    raw = [observation("USABC2600001"), observation("USABC2600001"), observation("GBABC2600001", "WRONG"), observation("", "MISSING")]
    rows = analysis.summarize_rows(sample, raw, [{"isrc": "USABC2600001", "title": "EXAMPLE", "artist_names": ["Artist"]}])
    assert rows[0]["mlc_work_codes"] == ["ONE"]
    assert rows[0]["valid_iswcs"] == ["T0345246801"]
    assert set(rows[0]["review_flags"]) == {"recording_isrc_missing", "recording_isrc_mismatch"}
    assert analysis.metrics(rows)["isrcsWithValidIswc"] == 1
    assert rows[0]["accepted_link_written"] is False


def test_no_match_errors_and_unattempted_are_different_outcomes():
    sample = [{"isrc": f"USABC260000{i}", "cohort": "systematic_spread", "selection_title": "Example"} for i in range(1, 4)]
    raw = [{"candidate": {"isrc": sample[0]["isrc"]}, "status": "no_recording_match"}, {"candidate": {"isrc": sample[1]["isrc"]}, "status": "recording_lookup_error", "error": {"type": "MLCTransportError"}}]
    rows = analysis.summarize_rows(sample, raw, [])
    assert analysis.metrics(rows)["noRecordingMatchIsrcs"] == 1
    assert analysis.metrics(rows)["isrcsWithApiErrors"] == 1
    assert rows[2]["review_flags"] == ["not_attempted_or_missing_output"]


def test_every_spotify_title_variant_can_corroborate_without_auto_acceptance():
    sample = [{"isrc": "USABC2600001", "cohort": "popular", "selection_title": "Different"}]
    raw = [{"candidate": {"isrc": "USABC2600001", "mlcSongCode": "ONE", "iswc": "T0345246802"}, "status": "candidate_pending_review", "mlcRecordingObservation": {"isrc": "USABC2600001", "title": "Matching", "artist": "Other artist"}, "mlcWorkObservation": {"mlcSongCode": "ONE"}}]
    spotify = [{"isrc": "USABC2600001", "title": title, "artist_names": ["Artist"]} for title in ["Different", "Matching"]]
    rows = analysis.summarize_rows(sample, raw, spotify)
    assert "recording_title_text_differs" not in rows[0]["review_flags"]
    assert "recording_artist_text_differs" in rows[0]["review_flags"]
    assert "invalid_iswc_format_or_checksum" in rows[0]["review_flags"]
    assert analysis.metrics(rows)["isrcsWithValidIswc"] == 0


def test_null_and_missing_display_fields_do_not_crash_variant_sort():
    sample = [{"isrc": "USABC2600001", "cohort": "popular", "selection_title": "Example"}]
    raw = [{"candidate": {"isrc": "USABC2600001", "mlcSongCode": "ONE"}, "status": "work_without_iswc", "mlcRecordingObservation": {"isrc": "USABC2600001", **fields}} for fields in [{}, {"title": None, "artist": None}, {"title": "Example", "artist": "Artist"}]]
    row = analysis.summarize_rows(sample, raw, [])[0]
    assert row["mlc_recording_titles"] == ["Example"]
    assert row["mlc_recording_artists"] == ["Artist"]


def test_sample_provenance_rejects_altered_rows_cohorts_and_linked_inputs(tmp_path):
    sample = [{"isrc": "USABC2600001", "cohort": "popular", "selection_title": "Example"}]
    p = tmp_path / "sample.csv"
    p.write_text("isrc,cohort,selection_title\nUSABC2600001,popular,Example\n")
    manifest = {"sampleSha256": analysis.digest(p), "selectedUniqueIsrcs": 1, "cohorts": {"popular": 1}}
    match = tmp_path / "spotify-candidates.parquet.manifest.json"
    match.write_text(json.dumps({"inputSha256": manifest["sampleSha256"]}))
    analysis.validate_sample(tmp_path, sample, manifest)
    with pytest.raises(ValueError, match="unique"):
        analysis.validate_sample(tmp_path, sample + sample, manifest)
    with pytest.raises(ValueError, match="cohort counts"):
        analysis.validate_sample(tmp_path, [{**sample[0], "cohort": "other"}], manifest)
    with pytest.raises(ValueError, match="digest mismatch"):
        analysis.validate_sample(tmp_path, sample, {**manifest, "sampleSha256": "other"})
    match.write_text(json.dumps({"inputSha256": "other"}))
    with pytest.raises(ValueError, match="match input differs"):
        analysis.validate_sample(tmp_path, sample, manifest)
    p.write_text(p.read_text() + "USABC2600001,popular,Example\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        analysis.validate_sample(tmp_path, sample, manifest)
