# Changelog

This project follows semantic versioning after its first tagged alpha. Until `1.0.0`, receipt, API, and deployment interfaces may change with documented migration notes.

## Unreleased

### Cross-node permission requests and public terms

- Added signed permission requests between configured nodes. The requester's node signs `clef.permission-request.v1`; the source node accepts only pinned peers, rechecks the publication, and decides under its own policy and reviewers. Its `clef.permission-status.v1` answers carry grant and lifecycle receipts, which the requesting node verifies against the source's pinned key. Identical redeliveries return the original record; a reused request ID with different terms is refused.
- Added **Request terms** and **Sent requests** to Connected catalogs, with the same content-category and AI-use declarations as a local request, and status refresh from the source.
- Added account-free public terms (`GET /v1/public/catalog/publications/{id}`) and a signed node descriptor (`GET /.well-known/clef-node`). The web image's nginx template now routes these and the peer-facing federation paths at the node origin; `make verify-deployment` checks the route.
- Added `nextPublicKey` peer pins and `NODE_NEXT_SIGNING_PUBLIC_KEY_B64` for key rotation without an outage, and `scripts/federation_peer.py` to produce a peer entry only after the peer's key ID matches the one verified out of band.
- **API change:** `POST /v1/receipts/verify` returns `valid: true` only when the signer is this node or a configured peer, and adds `signer`. A self-consistent receipt from an unknown key now returns `signatureValid: true` and `valid: false`.
- Hardened after an adversarial review: `peer-` organization slugs are reserved and a mismatched represented organization is refused; rate limits, timeouts and source conflicts leave requests retryable; the source rechecks a publication after locking its claim and row, closing a withdrawal race on PostgreSQL; retired keys (`retiredPublicKeys`, `NODE_RETIRED_SIGNING_PUBLIC_KEYS_B64`) keep pre-rotation receipts verifiable; peer enrollment derives the key ID from the key; status statements carry the newest receipts within the size budget and report omissions; refresh releases its database connection during the network call.
- Migration `0021_federated_requests` adds a peer-node request actor, inbound and outbound federated request records, and member-less requester organizations for peers. Populated federated records prevent destructive downgrade.
- Extended `scripts/run_federation_preview.py --verify` with a cross-node request, human approval, receipt verification, replay, impostor refusal, public terms and a withdrawn-entry refusal. Added `scripts/verify_hosted_federation.py` for the same proof against two HTTPS deployments.

### Discovery hardening

- Enforced a total peer transport deadline by closing the socket, so a peer that drips bytes cannot hold a worker; added per-peer capacity within a larger shared pool so one slow peer cannot starve searches of others.
- Moved buyer-search database and signing work off the event loop.
- Rejected multicast destinations, and invisible, bidirectional-override, private-use and unassigned characters in search queries.
- Published policy limits are whole numbers so signatures verify across JSON canonicalization implementations.
- Added tests for the eight-peer limit, query and result bounds, the candidate window, staging loopback refusal, future-dated and over-limit statements, duplicate entries, untrusted TLS certificates and cross-type signature reuse. Federation searches in tests now use a unique organization label, so absence checks cannot pass vacuously.

### Authority withdrawal and recoverable catalog review

- Added organization-controlled authority withdrawal with a private consequence preview, required reason, current-evidence check and safe retries. Withdrawn claims stop new permissions, pending approval and fresh federated publication; issued grants keep their receipts and separate lifecycle controls.
- Added **Refresh preview** to recover the original CSV after a catalog or managed-client change. Refresh preserves the source rows and audit history, and requires renewed conflict review and import confirmation.
- Bound catalog review to the current asset version and assignment. Serialized review, commit and assignment writes per organization, preventing concurrent changes from silently replacing the reviewed client.
- **API change:** catalog resolution, refresh and commit now require `expected_preview_digest`. Preview responses and resolution responses provide `previewDigest`; committed retries retain the accepted digest. Update API clients alongside the console.
- Migration `0020_catalog_review_basis` adds nullable review bindings without rewriting imported history. Pending imports created by earlier releases require a preview refresh. Populated review bindings prevent destructive downgrade.
- Added synchronous UI submission guards, retained commit payloads for retries, and ignored obsolete import-preview responses. Assignment changes require the current catalog version and a written reason.

### Connected catalog discovery

- Added opt-in public catalog projections with an exact-field preview, authenticated administrator consent, paginated administration, withdrawal and fresh review after policy or authority changes. Migration `0019_catalog_federation` retains the consent record and refuses a destructive downgrade.
- Added live search across up to eight configured nodes, preserving each source's public fields, pinned Ed25519 proof, query nonce and expiry. Private agreements and evidence remain in the originating node's access controls.
- Bounded source statements and network responses by the same UTF-8 byte limit; long multibyte catalogs truncate explicitly. Peer connections pin validated public addresses, verify TLS hostnames and reject redirects. Timeouts retain bounded worker capacity and produce explicit partial results.
- Added **Connected catalogs** to enabled consoles, with recording/composition cards, artist-use conditions, individual source freshness, signed statement downloads and publication controls.
- Added a reproducible two-node local demonstration and verification mode exercising separate databases/signers, source withdrawal, blocked policies, renewed consent, failed peers and durable restart. The feature remains disabled until configured by an operator.

### Prepared catalog walkthrough

- Added `scripts/run_local_preview.py` for an isolated local API and console with durable example records and signing keys, port checks, process-group shutdown and restart verification. The preview supplies an empty `CLEF_ENV_FILE` instead of reading the repository's integration credentials.
- Prepared fictional managed clients alongside the catalog so the walkthrough can hand off to an assigned record in the full console.
- Added a guest-scoped public-sandbox example with a fictional recording/composition pairing, separate label and publisher policies, assigned reviews and two independent permission decisions.
- The four-step walkthrough uses the real catalog, authority, permission and receipt APIs. Broader requests exercise the live policy and territory checks; receipt verification compares the original with an altered copy.
- Added resumable preparation and a database lease for concurrent tabs/workers, preserving existing policy edits and decisions. Adopter environments cannot invoke synthetic preparation.
- Added accessible organization perspectives, phone layouts, authenticated receipt downloads, a full-console handoff and fresh-example sessions. Refined the entry copy around catalog administration and creator conditions.
- Applied compatible frontend development dependency security updates; the dependency audit now reports zero known vulnerabilities.

### Review and retry reliability

- Fixed the catalog assignment form to retain its displayed client until the user chooses another client or explicit unassignment. Client-only CSV changes now enter conflict review; omitting the client column preserves the existing assignment on a new version.
- Guarded privacy and walkthrough downgrades against dropping consent, retention, erasure or saved-example records. Updated release ordering and recovery instructions for migration `0018_sandbox_tour`.
- Enforced settlement party and role checks before serving idempotent entry retries or reporting existing terms. Unrelated users and machine credentials cannot retrieve a cached financial record.
- Retained exact financial requests and idempotency keys across uncertain responses, prevented duplicate clicks, and separated successful recording from refresh failures. Newly created settlements remain visible after their first entry.
- Cleared the legacy demo console's organization state on sign-out and ignored obsolete search and editor-save completions. Reconciliation receipts download through authenticated requests.
- Applied same-origin redirect protection to the real-pilot verifier. Reference reconciliation now stages data and its manifest together and preserves the preceding pair on publication failure.
- Required complete metadata comparisons and correctly attributed approval events in workflow verification; receipt summaries now retain the original receipt's transparency hash.
- Exercised the default Vite authentication/API proxy with a local backend, and added component tests for ambiguous writes, identity changes and overlapping requests.

### Permission safety and receipt privacy

- Enforced all declared content restrictions for standard and AI requests. Conditional uses require review; denied uses block approval. The console collects an explicit content declaration.
- Limited grants to the full territorial scope of the verified claim, with normalized country lists and overlap checking.
- Rechecked current authority and policy before human or machine approval and receipt issuance; blocked policies preserve the pending request without issuing a receipt.
- Required party authentication for every receipt download, including lifecycle and settlement records. Public verification accepts a supplied receipt; the public log exposes sequence and hashes only. The console and pilot verifier now retrieve receipts with credentials.
- Added 46 regression cases for these launch blockers and documented the receipt API upgrade in `docs/foundation/RECEIPT_PROTOCOL.md`.

### Administration and deployment

- Added an operator readiness panel covering migrations, signing identity, source revision, email delivery, optional adapters, and fresh worker heartbeats stored in PostgreSQL.
- Added portable SMTP delivery alongside Mailgun, with encrypted SMTP transport required for adopter staging and production. Sign-in links have unique identities even when issued within the same second.
- Preserved separate label, publisher, requester, and node-operator workflows. Authority submission now asks for the actual evidence source and leaves controlled share unspecified until entered; every field has a persistent label.
- Added web security headers across pages and assets and enough proxy upload capacity for the documented 10 MiB catalog file plus its multipart envelope.
- Added an adopter-owned Railway template specification and reproduction checks, plus a logical PostgreSQL backup/restore comparison tool.

### Catalog reconciliation and verification

- Added an optional private Spotify-reference workflow for matching controlled ISRC catalogs and preparing reviewable MLC reconciliation candidates. Its manifests keep observed metadata separate from authority records.
- Hardened reference-file replacement, receipt-to-permission comparison, credential scanning, deployment configuration inspection, verifier transport, and malformed-report handling.
- Required full Git commit hashes for staging and production source declarations. Release verification compares the public source archive's files and modes with the named commit.
- Added a single `make verify-alpha` gate and a PostgreSQL version of the synthetic rightsholder workflow, including scoped AI permissions, exact credit obligations, signed receipts, and settlement evidence.

### Upgrade from 0.1.0-alpha.1

1. Preserve a recoverable database backup and the existing signing and webhook-encryption keys. Keep the previous application revision and its deployment configuration available for rollback.
2. Publish the complete source for the new revision, then set `SOURCE_CODE_REVISION` to its full Git commit hash and `SOURCE_CODE_URL` to the matching public commit page or archive. A tag or abbreviated hash now fails staging and production startup.
3. Select the email provider explicitly: `smtp` or `mailgun` for adopters, and `disabled` for the synthetic public sandbox. Use the provider settings in the [Railway runbook](docs/RAILWAY_DEPLOYMENT.md).
4. Run `alembic upgrade head` before starting the new API and workers. This applies `0016_service_heartbeats`, `0017_receipt_privacy` and `0018_sandbox_tour` in order, adding worker heartbeats, receipt disclosure settings, private-evidence commitments, reviewed erasure records and guest walkthrough state. Preserve the original signed receipt payloads through migration.
5. Deploy the API, webhook worker, expiry worker, and web console from the same revision. Check operator readiness, web headers, sign-in, and public-source verification using the [release sequence](docs/RAILWAY_DEPLOYMENT.md#release-sequence).

This candidate retains AGPL-3.0-only. The proposed own-node license remains a separately identified draft. Publication, adopter reproduction, real controlled-catalog acceptance, retained-backup recovery, and partner exchange must each be evidenced in their actual deployment; local synthetic tests establish the software behavior they exercise.

## 0.1.0-alpha.1 — 2026-08-13

- Prepared the public-alpha documentation, governance, deployment, review, and verification package.
- Added a granular AI-use policy, evidence-backed authority workflow, signed permission lifecycle, publication compliance records, and external-settlement evidence ledger.
- Added a fail-closed public-sandbox profile with persistent synthetic-data and source-revision disclosure plus rate-limited, anonymous short-lived access that collects no guest identity.
- Added synthetic workflow, official DDEX fixture, deployment-configuration, backend, frontend, clean-install, and release-evidence gates.

### Known limits

- The Railway topology is provisional and is not a verified one-click template.
- Clef records payment and payout evidence but does not hold funds, move money, perform KYC, or guarantee collection.
- MLC and DDEX integrations require operator credentials, authority, licences, counterparties, and bilateral acceptance that Clef does not supply.
- No real catalog or legal authority has qualified the public alpha; synthetic verification does not establish ownership, permission, payment, or legal validity.
