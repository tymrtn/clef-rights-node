# Spotify reference metadata

Clef can use the Spotify metadata release labeled July 2025 as a private reference source for catalog identification and reconciliation. It is not imported into an organization's controlled catalog, and it never establishes ownership, authority, permission, licence status, or an ISWC.

## What the source contributes

- Spotify track, album, artist, label, release, UPC, duration, popularity, market, genre, image, and relationship metadata.
- ISRC observations attached to Spotify track records.
- Spotify identifiers and URLs that can help an operator investigate ambiguous matches.

The source does not contain ISWCs. An authorized lookup from The MLC can identify a candidate work and ISWC associated with an ISRC. Its publishing information has a U.S. administrative context, and its recording references originate with DSPs and are processed as received. A publisher repertoire system and documented rightsholder evidence support review of the relationship, controlled shares and territorial scope. Evidence of master ownership comes from the recording rightsholder.

Agreement between Spotify metadata and The MLC can reflect shared DSP inputs. Measure observed identifier coverage and discrepancies separately from independent accuracy or ownership verification. A no-match response describes this API lookup at this time; a missing ISWC, work-code conflict or title difference belongs in the review queue.

Every result must retain these semantics:

```json
{
  "assertionType": "observed_catalog_metadata",
  "authorityStatus": "unverified",
  "iswc": null,
  "iswcStatus": "not_provided_by_source"
}
```

## Source and reuse gate

The current workflow pins the Kaggle mirror of the Anna's Archive dataset labeled `2025-07` to version 5. That label is not a hard cutoff: the pinned mirror contains track and album fetch timestamps through 13 November 2025, including 40,729,111 track rows fetched after July. Public availability does not by itself settle database, contract, attribution, display, or redistribution rights. Before Clef redistributes this material, exposes it from a hosted service, or uses it in public marketing, an operator must document the approved use and any required Spotify links or attribution.

- Source description: <https://annas-archive.org/blog/backing-up-spotify.html>
- Pinned mirror: <https://www.kaggle.com/datasets/lordpatil/spotify-metadata-by-annas-archive>
- Spotify developer terms: <https://developer.spotify.com/terms>

The default deployment pattern is therefore a private, operator-controlled reference store. Do not commit the source files to Git, sync them through the repository, or copy them into an adopter's Railway database.

## Reproducible fetch

Install the isolated data dependencies:

```bash
python -m venv .venv-spotify-reference
.venv-spotify-reference/bin/pip install -r scripts/requirements-spotify-reference.txt
```

Fetch the nine core catalog tables and artist-redirect map into storage outside the repository:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py fetch \
  --data-dir /path/to/private/reference-data/spotify-2025-07 \
  --scope catalog \
  --acknowledge-source-risk
```

The catalog scope is approximately 34.5 GB and excludes audio files, playlists and user-linked data, shows, and audiobooks. Downloads resume after interruption. The workflow pins every expected file size and writes `spotify-reference-manifest.json` beside the data; schema validation adds table row counts to that manifest.

Validate file sizes and Parquet schemas:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py validate \
  --data-dir /path/to/private/reference-data/spotify-2025-07 \
  --scope catalog \
  --schema
```

Measure exact ISRC coverage and store it in the source manifest:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py isrc-statistics \
  --data-dir /path/to/private/reference-data/spotify-2025-07
```

This exact count may differ from a publisher's headline for the archive because the pinned mirror version, validity rules, punctuation normalization, and duplicate treatment are explicit here.

Hashing all files is optional and intentionally separate because it requires reading the entire snapshot:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py validate \
  --data-dir /path/to/private/reference-data/spotify-2025-07 \
  --scope catalog \
  --schema \
  --hash
```

## Inspect one ISRC

The lookup scope needs tracks, albums, track-to-artist links, and artists:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py query \
  --data-dir /path/to/private/reference-data/spotify-2025-07 \
  --isrc USABC2600001
```

The output is source-tagged JSON suitable for an operator review screen or a later reconciliation job. It must not be written directly into authority claims.

## Match a controlled catalog

For a label or publisher catalog, prepare a CSV containing an `isrc` column and run one batch match. The result preserves duplicate Spotify observations rather than silently choosing a winner:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py match-catalog \
  --data-dir /path/to/private/reference-data/spotify-2025-07 \
  --input-csv /path/to/controlled-catalog.csv \
  --output-parquet /path/to/review/spotify-candidates.parquet
```

The adjacent manifest binds the result to the input digest and source snapshot. Every output row remains `observed_catalog_metadata`, `unverified`, and explicitly without an ISWC; it is a candidate for review, not a catalog authority claim.

For `match-catalog` and `fetch-rights-signals`, `--replace` prepares and validates the new Parquet file and manifest in a temporary directory beside the destination. Source, query, validation, and manifest-preparation failures preserve the previous pair. Publication replaces each file individually; a manifest-publication error triggers restoration of the prior data file.

If filesystem errors prevent restoration, the command retains both previous files in the reported recovery directory's `previous/` subdirectory. An interrupted process can also leave a `.clef-parquet-*` staging directory. Stop concurrent refreshes and inspect those recovery artifacts before using or replacing the destination pair; the two file replacements are not a single filesystem transaction.

## Reconcile a controlled catalog with The MLC

Clef can use an authorized account for The MLC’s Public Search API to turn exact ISRC observations into reviewable ISRC-to-ISWC candidates. The bounded workflow follows The MLC's two-step API path: search recordings by ISRC, then resolve song codes returned by The MLC through the works endpoint.

Preview the batch without contacting The MLC:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py reconcile-mlc \
  --spotify-candidates /path/to/review/spotify-candidates.parquet \
  --output-jsonl /path/to/review/mlc-candidates.jsonl \
  --max-isrcs 100
```

After loading the credentials issued to the operator by The MLC and explicitly authorizing the `catalog_lookup` capability, run the lookup:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py reconcile-mlc \
  --spotify-candidates /path/to/review/spotify-candidates.parquet \
  --output-jsonl /path/to/review/mlc-candidates.jsonl \
  --max-isrcs 100 \
  --execute \
  --acknowledge-observed-only
```

The output remains `observed_cross_registry_candidate`, authority `unverified`, permission `unknown`, and human review `pending`. It never writes an accepted link into Clef. Public Search is suited to targeted catalog reconciliation; organizations needing a large repertoire feed should arrange The MLC Bulk Data Access and process its DDEX BWARM delivery rather than sending millions of Public Search requests.

- The MLC Public Search API: <https://public-api.themlc.com/api/doc>
- The MLC Bulk Data Access: <https://www.themlc.com/bulk-database-feed>

## Extract rights-relevant platform signals

The release's 52.9 GB track-file table also contains useful non-authoritative signals: Spotify's internal licensor code, artist roles, lyric availability, language, alternate track IDs, original and version titles, content ratings, and audio hashes. Clef can project only those columns directly from the remote Parquet source, excluding the binary packet and delivery-file fields:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py fetch-rights-signals \
  --output-parquet /path/to/private/reference-data/spotify-2025-07/derived/rights-signals.parquet \
  --acknowledge-source-risk
```

These values are `observed_platform_signal`, `unverified`, and permission `unknown`. Licensor codes and artist roles are leads for reconciliation; they are not declarations by the named party, evidence of control, or permission to use a recording or work. Audio hashes can support duplicate and provenance investigation without acquiring the corresponding audio.

Validate the projected schema, semantic labels, and field coverage:

```bash
.venv-spotify-reference/bin/python scripts/spotify_reference.py validate-rights-signals \
  --output-parquet /path/to/private/reference-data/spotify-2025-07/derived/rights-signals.parquet
```

Validation requires all three labels on every row: `observed_platform_signal`, `unverified`, and `unknown`. Missing values, empty strings, and changed labels count toward `invalidSemanticRows`, cause a failing exit status, and set the validation manifest's `complete` field to `false`. The Parquet data remains unchanged for investigation.

## Intended reconciliation path

1. Export the adopter's controlled recording ISRCs from its node.
2. Match those ISRCs against the private Spotify snapshot and preserve every duplicate or conflicting observation.
3. Use `reconcile-mlc` or another authorized workflow from The MLC or a publisher to identify candidate musical works and ISWCs.
4. Ask an operator to review title, artist, writer, duration, release, label, and territorial conflicts.
5. Store the accepted ISRC-to-ISWC relationship with separate source, actor, time, and evidence fields.
6. Keep Spotify observations recoverable as evidence, never as the authority for the accepted relationship.

This separation lets Clef improve catalog coverage without implying that a platform metadata match has resolved the underlying rights.

## Exploratory coverage and discrepancy analysis

Use `scripts/catalog_overlap_analysis.py sample --data-dir /path/to/snapshot --output-dir /path/to/run` to select 20 popular and 30 systematically spread ISRCs by a fixed rule. Match the emitted `sample.csv` with `spotify_reference.py match-catalog`, then run its bounded `reconcile-mlc` command and retain `mlc-candidates.jsonl` in the same run directory. `catalog_overlap_analysis.py summarize --run-dir /path/to/run` generates a per-ISRC `review.csv` and `summary.json` with cohort counts and source digests.

Each result is counted by distinct input ISRC. The analysis preserves Spotify variants, checks the returned recording ISRC, validates ISWC format and check digit, and flags multiple work codes, multiple ISWCs and differences in title/artist text. API errors and unattempted records remain separate from successful empty searches. HTTP 204 with an empty body is an observed no-result response; malformed HTTP 200 responses remain errors. A checksum validates an identifier’s structure, not its assignment.

These convenience cohorts diagnose the workflow; their rates describe only the selected records. A publishable study needs a declared sampling frame, U.S. availability/usage treatment, dated source snapshots, representative strata, uncertainty estimates and independent review of suspected errors with the relevant labels and publishers. For a large offline join, obtain The MLC’s Bulk Data Access subscription and its applicable reuse terms. Keep snapshot absence, unresolved identity and authority to license as distinct outcomes.
