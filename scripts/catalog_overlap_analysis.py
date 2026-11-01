#!/usr/bin/env python3
"""Deterministic, private Spotify/The MLC overlap diagnostics; never grants rights.

sample -> spotify_reference.py match-catalog -> reconcile-mlc -> summarize.
No network or runtime AI here. Ambiguous records remain in the review CSV.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def normalized_text(value):
    return "".join(c for c in unicodedata.normalize("NFKC", str(value or "")).casefold() if c.isalnum())


def normalized_isrc(value):
    value = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    return value if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}\d{7}", value) else None


def normalized_iswc(value):
    """Validate the ISO 15707 T + nine digits + check digit identifier."""
    value = re.sub(r"[.\s-]", "", str(value or "")).upper()
    if not re.fullmatch(r"T\d{10}", value):
        return None
    check = (10 - (1 + sum(i * int(n) for i, n in enumerate(value[1:10], 1))) % 10) % 10
    return value if check == int(value[-1]) else None


def sample(args):
    import duckdb
    if not (1 <= args.popular <= 50 and 1 <= args.spread <= 50):
        raise ValueError("Each cohort must contain 1–50 ISRCs")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / "sample.csv"
    if target.exists():
        raise ValueError("Sample already exists; use a new output directory")
    root = args.data_dir.resolve()
    manifest_path = root / "spotify-reference-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    tracks = root / "spotify_clean_parquet/tracks.parquet"
    source_record = next(r for r in manifest["files"] if r["path"] == "spotify_clean_parquet/tracks.parquet")
    if tracks.stat().st_size != source_record["observedBytes"]:
        raise ValueError("Track file size differs from the pinned manifest")
    with duckdb.connect(config={"memory_limit": "2GB", "threads": "4"}) as con:
        con.read_parquet(str(tracks)).project("rowid, name, popularity, upper(regexp_replace(external_id_isrc, '[^A-Za-z0-9]', '', 'g')) AS isrc").create_view("tracks")
        popular = con.execute("SELECT isrc, name, popularity FROM tracks WHERE regexp_full_match(isrc, '[A-Z]{2}[A-Z0-9]{3}[0-9]{7}') ORDER BY popularity DESC NULLS LAST, isrc, rowid LIMIT 2000").fetchall()
        spread = con.execute("SELECT isrc, name, popularity FROM tracks WHERE rowid % 4093 = 0 AND regexp_full_match(isrc, '[A-Z]{2}[A-Z0-9]{3}[0-9]{7}') ORDER BY md5('clef-overlap-v1:' || isrc), rowid LIMIT 2000").fetchall()
    rows, seen = [], set()
    for cohort, candidates, size in [("popular", popular, args.popular), ("systematic_spread", spread, args.spread)]:
        count = 0
        for isrc, title, popularity in candidates:
            if isrc in seen:
                continue
            seen.add(isrc)
            rows.append(dict(isrc=isrc, cohort=cohort, selection_title=title, selection_popularity=popularity))
            count += 1
            if count == size:
                break
        if count != size:
            raise ValueError(f"Insufficient distinct ISRCs for {cohort}: {count}")
    with target.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    record = {
        "schemaVersion": "clef.catalog-overlap-sample.v1", "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sourceManifest": str(manifest_path), "sourceManifestSha256": digest(manifest_path),
        "sourceDataset": manifest["dataset"], "trackSha256FromPriorManifest": source_record.get("sha256"),
        "trackHashRecomputed": False, "sampleSha256": digest(target), "selectedUniqueIsrcs": len(rows),
        "cohorts": dict(Counter(r["cohort"] for r in rows)),
        "method": "Popular: first distinct ISRCs among top 2000 rows ordered by popularity DESC, ISRC, rowid. Spread: rowid modulo 4093 equals zero, ordered by md5('clef-overlap-v1:' + normalized ISRC), rowid; exclude already selected ISRCs.",
        "scope": "Exploratory convenience sample from a historical snapshot; no population coverage/accuracy estimate or represented catalog claim.",
    }
    write_json(output / "sample.manifest.json", record)
    print(json.dumps(record, indent=2))


def summarize_rows(sample_rows, observations, spotify_rows):
    grouped, spotify = defaultdict(list), defaultdict(list)
    for row in observations:
        grouped[row["candidate"]["isrc"]].append(row)
    for row in spotify_rows:
        spotify[row["isrc"]].append(row)
    result = []
    for item in sample_rows:
        isrc = item["isrc"]
        rows = grouped[isrc]
        exact = [r for r in rows if normalized_isrc((r.get("mlcRecordingObservation") or {}).get("isrc")) == isrc]
        missing_returned = [r for r in rows if r.get("mlcRecordingObservation") and not (r["mlcRecordingObservation"].get("isrc") or "").strip()]
        wrong_returned = [r for r in rows if r.get("mlcRecordingObservation") and r not in exact and r not in missing_returned]
        works = sorted({r["candidate"]["mlcSongCode"] for r in exact if r["candidate"].get("mlcSongCode")})
        valid_iswcs = sorted({n for r in exact if (n := normalized_iswc(r["candidate"].get("iswc")))})
        bad_iswcs = sorted({r["candidate"]["iswc"] for r in exact if r["candidate"].get("iswc") and not normalized_iswc(r["candidate"]["iswc"])})
        titles = {normalized_text(r.get("title")) for r in spotify[isrc] if normalized_text(r.get("title"))}
        mlc_titles = {normalized_text(r["mlcRecordingObservation"].get("title")) for r in exact if normalized_text(r["mlcRecordingObservation"].get("title"))}
        artists = {normalized_text(a) for r in spotify[isrc] for a in (r.get("artist_names") or []) if normalized_text(a)}
        mlc_artists = {normalized_text(r["mlcRecordingObservation"].get("artist")) for r in exact if normalized_text(r["mlcRecordingObservation"].get("artist"))}
        errors = sorted({r["status"] for r in rows if r.get("error") or r["status"].endswith("_error")})
        flags = []
        if not rows:
            flags.append("not_attempted_or_missing_output")
        if missing_returned:
            flags.append("recording_isrc_missing")
        if wrong_returned:
            flags.append("recording_isrc_mismatch")
        if len(works) > 1:
            flags.append("multiple_work_codes")
        if len(valid_iswcs) > 1:
            flags.append("multiple_iswcs")
        if bad_iswcs:
            flags.append("invalid_iswc_format_or_checksum")
        if titles and mlc_titles and not titles.intersection(mlc_titles):
            flags.append("recording_title_text_differs")
        if artists and mlc_artists and not artists.intersection(mlc_artists):
            flags.append("recording_artist_text_differs")
        if any(not r.get("mlcWorkObservation") for r in exact if r["candidate"].get("mlcSongCode")):
            flags.append("work_unresolved")
        if len(titles) > 1:
            flags.append("spotify_title_variants")
        if errors:
            flags.append("api_error")
        result.append({
            "isrc": isrc, "cohort": item["cohort"], "title": item["selection_title"],
            "spotify_observations": len(spotify[isrc]), "exact_isrc_observed": bool(exact),
            "mlc_work_codes": works, "valid_iswcs": valid_iswcs, "invalid_iswcs": bad_iswcs,
            "mlc_recording_titles": sorted({r["mlcRecordingObservation"].get("title") for r in exact if isinstance(r["mlcRecordingObservation"].get("title"), str)}),
            "mlc_recording_artists": sorted({r["mlcRecordingObservation"].get("artist") for r in exact if isinstance(r["mlcRecordingObservation"].get("artist"), str)}),
            "status_counts": dict(Counter(r["status"] for r in rows)), "review_flags": flags,
            "authority_status": "unverified", "permission_status": "unknown", "accepted_link_written": False,
        })
    return result


def metrics(rows):
    return {
        "sampleIsrcs": len(rows),
        "exactRecordingMatchIsrcs": sum(r["exact_isrc_observed"] for r in rows),
        "isrcsWithWorkCode": sum(bool(r["mlc_work_codes"]) for r in rows),
        "isrcsWithValidIswc": sum(bool(r["valid_iswcs"]) for r in rows),
        "isrcsWithMultipleWorkCodes": sum(len(r["mlc_work_codes"]) > 1 for r in rows),
        "isrcsWithMultipleIswcs": sum(len(r["valid_iswcs"]) > 1 for r in rows),
        "noRecordingMatchIsrcs": sum("no_recording_match" in r["status_counts"] for r in rows),
        "isrcsWithApiErrors": sum("api_error" in r["review_flags"] for r in rows),
        "isrcsWithReviewFlags": sum(bool(r["review_flags"]) for r in rows),
        "flagCounts": dict(Counter(flag for r in rows for flag in r["review_flags"])),
    }


def validate_sample(run, selected, manifest):
    if digest(run / "sample.csv") != manifest["sampleSha256"]:
        raise ValueError("Sample digest mismatch")
    matched_manifest = json.loads((run / "spotify-candidates.parquet.manifest.json").read_text())
    if matched_manifest["inputSha256"] != manifest["sampleSha256"]:
        raise ValueError("Spotify match input differs from the selected sample")
    identifiers = [normalized_isrc(r["isrc"]) for r in selected]
    if None in identifiers or len(set(identifiers)) != len(selected):
        raise ValueError("Sample ISRCs must be valid and unique")
    if len(selected) != manifest["selectedUniqueIsrcs"] or dict(Counter(r["cohort"] for r in selected)) != manifest["cohorts"]:
        raise ValueError("Sample cohort counts differ from the manifest")


def summarize(args):
    import duckdb
    run = args.run_dir.resolve()
    with (run / "sample.csv").open() as f:
        selected = list(csv.DictReader(f))
    sample_manifest = json.loads((run / "sample.manifest.json").read_text())
    validate_sample(run, selected, sample_manifest)
    raw = [json.loads(line) for line in (run / "mlc-candidates.jsonl").read_text().splitlines() if line.strip()]
    manifest = json.loads((run / "mlc-candidates.jsonl.manifest.json").read_text())
    if digest(run / "mlc-candidates.jsonl") != manifest["outputSha256"]:
        raise ValueError("Reconciliation output digest mismatch")
    if digest(run / "spotify-candidates.parquet") != manifest["inputSha256"]:
        raise ValueError("Reconciliation input digest mismatch")
    with duckdb.connect() as con:
        cur = con.execute("SELECT isrc, title, artist_names FROM read_parquet(?)", [str(run / "spotify-candidates.parquet")])
        names = [d[0] for d in cur.description]
        spotify_rows = [dict(zip(names, row)) for row in cur.fetchall()]
    rows = summarize_rows(selected, raw, spotify_rows)
    result = {
        "schemaVersion": "clef.catalog-overlap-report.v1", "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "claimLedger": {
            "centralClaim": "Exact ISRC lookup can surface reviewable work/ISWC candidates and catalog discrepancies; this run measures observed overlap.",
            "strongestEvidence": "Retained per-ISRC API observations, validated identifier checksums, source hashes, and all matched Spotify variants.",
            "scopeAndLimits": "50 or fewer records per cohort, convenience selection from historical Spotify metadata. DSP origins can overlap; neither dataset is independent ground truth for master ownership. The MLC publishing data has a US administrative context; permissions require evidence from represented parties for each right and territory.",
            "falsifier": "A candidate lacks the requested ISRC in the returned recording, a retrievable linked work, or a valid ISWC; a metric fails recomputation from the retained observations.",
            "whyItMatters": "Shows what a rights team can reconcile now and which records need follow-up before accepting a link.",
        },
        "sample": sample_manifest,
        "apiComplete": manifest["complete"], "apiErrors": manifest["apiErrors"],
        "totals": metrics(rows), "cohorts": {c: metrics([r for r in rows if r["cohort"] == c]) for c in sorted({r["cohort"] for r in rows})},
        "acceptedLinksWritten": 0, "rawObservationSha256": digest(run / "mlc-candidates.jsonl"),
        "interpretation": [
            "No-match means no result in these API responses, not absence of rights or absence from all of The MLC's records.",
            "Multiple work codes/ISWCs are review leads, not proven registry errors; medleys, splits and data variants need investigation.",
            "Title and artist comparison uses Unicode-normalized alphanumeric text against every Spotify variant. Formatting, guest artists and aliases can explain differences.",
            "Rates apply only to these two selected cohorts; shared DSP inputs prevent an independent accuracy claim.",
        ],
    }
    with (run / "review.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in rows)
    write_json(run / "summary.json", result)
    print(json.dumps({k: result[k] for k in ["apiComplete", "apiErrors", "totals", "cohorts"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("sample")
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--popular", type=int, default=20)
    p.add_argument("--spread", type=int, default=30)
    p.set_defaults(func=sample)
    p = commands.add_parser("summarize")
    p.add_argument("--run-dir", type=Path, required=True)
    p.set_defaults(func=summarize)
    args = parser.parse_args()
    args.func(args)
