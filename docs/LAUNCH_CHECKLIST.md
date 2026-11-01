# Launch Checklist

Choose the launch scope before applying the gates below.

- **Public synthetic demonstration:** use fictional catalogs, isolated guest sessions and disabled external data and delivery providers. Pass the automated gates, publish the exact corresponding source, complete the hosted walkthrough and obtain founder acceptance.
- **Organization installation:** add the operator gates for identity, authority review, privacy, recovery and the integrations that organization enables. A clean installation in an independent account is the evidence for a repeatable setup claim.
- **Controlled licensing pilot:** add a rightsholder's reviewed catalog, authorized reviewers and real use evidence. Apply the settlement gate before making a royalty-distribution claim.

## Automated gates

- `make verify-alpha` reproduces every local alpha gate with one command.
- `make verify-public` passes across every public Git blob and current non-ignored file, rejecting private artifacts, credentials, personal correspondence, private keys, and blobs larger than 5 MiB without echoing matched values.
- `make test-local` passes, including `backend/tests/test_permission_safety.py`: every denied content category, territorial containment, policy and authority changes during pending review, and party-only receipt downloads.
- Deploy the API and matching console together; validate private grant, lifecycle and settlement receipt access, plus public verification of a supplied receipt.
- `make verify-ddex` passes against the pinned official MWL schemas.
- `make verify-deployment` passes for the API, web, webhook-worker, and expiry-worker Railway profiles.
- `make verify-workflow` passes label/client role separation, requester isolation, scoped machine credentials, cross-tenant rejection, derivative and AI permission scopes, named-reviewer enforcement, signed exact obligations, publication and compliance evidence, reserve/royalty/payment/payout reconciliation, signed grant/settlement/dispute/revocation verification, audit attribution, tamper rejection, and transparency-chain checks.
- Fresh SQLite and PostgreSQL databases migrate through the latest Alembic revision, survive downgrade/re-upgrade, and pass `alembic check` without ORM drift.
- Production startup rejects unversioned, stale, or divergent database schemas instead of creating missing tables.
- Production frontend build and production-dependency audit pass. The backend installs `requirements.lock` with package hashes enforced; the CI dependency-audit job checks that complete resolved set with `pip-audit`. Run `uvx --from pip-audit==2.10.1 pip-audit --require-hashes --disable-pip -r backend/requirements.lock` before freezing a candidate.
- API and web container images build. Run `scripts/verify_container_preview.py --api-image <local-api-image> --web-image <local-web-image>` against those images for a disposable synthetic check through nginx: guest preparation, separate approvals, five scope rejections, private receipt downloads, signature verification, tamper rejection and resume. The verifier requires a local Docker daemon; the API has an internal network and the web port binds only to loopback. Record the tested image IDs and architecture. The proof checks that every installed Python package, including base-image packaging tools, matches the audited lock.
- Review container base versions and their operating-system packages separately from Python/npm dependencies. The web runtime is pinned to the nginx 1.30.5 multi-platform image digest, reviewed against [the stable release notes](https://nginx.org/en/CHANGES-1.30) on 18 September 2026. Refresh that review at release time; record the actual nginx version and image digest with the container proof. A clean Python audit covers the Python package inventory only.
- The API image pins Python 3.11 on Alpine, applies available base-system updates and installs hash-verified binary wheels. Dependency compatibility is checked during its build; the package installer is then removed, keeping its vendored tools out of the runtime. Add dependencies through the reviewed requirements and rebuild the image. Scan the resulting image, retain all findings and distinguish available fixes from advisory applicability; keep the compiler and PostgreSQL development headers out of the runtime. Validate PostgreSQL workflows inside this image as well as the disposable SQLite tour, because its native libraries differ from a host development environment.
- Frontend tests pass with both the local root API path and the shipped `/api` prefix. The production web build uses `/api`.
- The web proxy preserves security headers on pages and assets, accepts the documented 10 MiB catalog file plus multipart overhead, and retains the API's authenticated upload and file-size checks.
- Production startup rejects demo flags, wildcard CORS, ephemeral signing keys, and missing mail delivery.
- Production startup rejects a missing corresponding-source URL or development revision; `/v1/node/info` and the console identify the deployed AGPL source revision.
- Production source declarations use a full Git commit hash, and release verification matches the public archive's file contents and modes against that commit in the clean source checkout.
- Public-sandbox mode rejects live MLC, DDEX, MusicBrainz, OpenRouter, and Slack integrations; the console displays its synthetic non-production warning and immutable source revision.
- Anonymous sandbox access is rate-limited, uses generated `.invalid` identities, expires with the normal session TTL, accepts no guest email, and cannot be enabled in adopter modes.
- The signed expiry runner is idempotent; exactly one supervised worker is healthy and its success heartbeat is current.
- Overclaimed authority moves out of discovery, valid split ownership remains discoverable, and operator conflict resolution is access-controlled.
- Credential secrets are returned once, only digests persist, expiry and revocation fail closed, and database-level audit update/delete attempts are rejected.
- Review assignments, requester usage reports, and authority compliance reviews reject update/delete at the ORM and database layers; reviewer identity remains private from the requester.
- Catalog uploads require durable identifiers, preview cleanly, block unresolved rows and preserve corrections as versions. Refreshing an import rechecks the current catalog and client assignments; resolution and commit require the current `expected_preview_digest`. Test stale previews, lost responses and exact retries.
- Authority withdrawal shows affected requests before confirmation, records a private reason, removes fresh discovery results and blocks later approvals. Run `scripts/verify_authority_concurrency.py` against disposable SQLite and PostgreSQL databases to test an overlapping approval and withdrawal.
- The prepared walkthrough creates separate recording and composition requests, survives reloads and retains changes to the example policies.
- For a federation demonstration, run `scripts/run_federation_preview.py --verify` with a fresh state directory. Test both independent nodes, signed query-bound results, limited public fields, withdrawal, changed publication consent, expiry and an unavailable peer.
- Webhook secrets remain encrypted, events and attempts reject update/delete, retries survive a worker restart, and private-network targets fail closed.
- DDEX credentials remain party- and scope-bound; exchange and acknowledgement records reject mutation; acknowledgement retries are idempotent and never change permission status.
- MLC lookups use bounded transport settings, refresh expired credentials once, remain organization-scoped for machines, and enter the audit trail only as observed registry reads.

## Operator gates

- Durable Ed25519 signing key is generated, backed up, and protected in the deployment secret manager.
- `SOURCE_CODE_URL` resolves without authentication to the complete corresponding source for the immutable `SOURCE_CODE_REVISION` actually deployed.
- HTTPS, encrypted database storage, backups, restore tests, retention, logging, alerting, and incident contacts are configured.
- The operator runs `scripts/verify_postgres_recovery.py` for a logical database restore comparison, then separately exercises retained-backup retrieval, database roles, secret recovery, and restored application readiness as described in `docs/SELF_HOSTING.md`.
- Node operator emails, organization memberships, and authority-review responsibilities are verified.
- The pilot label has named owners for the shared request queue, reassignment, exact license terms, publication-evidence review, and escalation into dispute or revocation.
- Machine credentials are inventoried by owner, integration, scope, expiry, rotation date, and revocation procedure; no integration shares a bearer secret.
- The separate webhook encryption key is backed up, worker lag and dead letters are monitored, receiver secrets are inventoried, and a receiver verifies timestamped signatures.
- Each enabled adapter has an identified account owner, documented permitted use and tested credentials. Operators can start with their own catalog metadata and enable The MLC or other reference sources as their access permits.
- For federated discovery, configure each participating HTTPS origin and verified signing key. The catalog administrator reviews the public field preview before publication; private agreements, people and commercial details retain party-scoped access.

## Integration and pilot gates, when applicable

- For DDEX implementation, the operator has accepted the free DDEX Implementation Licence, received its DPID from `dpid.ddex.net`, and kept the registry record current.
- For DDEX export, `make install-ddex-schemas` succeeds, the schema directory is mounted read-only, and the production container reports the pinned MWL profile as configured.
- For future live DDEX exchange, exercise partner transport, delivery receipts, acknowledgement semantics and escalation ownership against a bilateral operating agreement before enabling that capability.
- Complete one real controlled settlement with immutable terms, external payment evidence, every beneficiary payout, zero reconciliation variance, and founder review before publishing any royalty-distribution claim.
- Confirm the external payment provider owns KYC, beneficial-owner, tax, sanctions, withholding, suspense, reversal, and money-movement duties; Clef records only final evidence.
- `make verify-real-pilot` returns `qualified: true` for that controlled catalog, and its short-lived read-only credential is immediately revoked.

## Freeze the review candidate

With [uv](https://docs.astral.sh/uv/) available for the isolated audit tool, run `.venv/bin/python scripts/prepare_launch_review.py --output /private/path/to/new-review-directory` after finishing both repositories. It checks the source for private artifacts, runs the node, dependency-audit and website gates, rejects source changes during verification and writes a deterministic archive with file hashes, working-source fingerprints and private build logs. Failed checks produce a clearly marked failure record and logs. Keep each candidate in its own directory.

The bundle is a local review artifact. After approval, commit and publish its reviewed source, build each service from the adopted commit, and follow [Railway deployment and recovery](RAILWAY_DEPLOYMENT.md). Match the hosted sandbox, website claims and walkthrough video to that release.

## Founder acceptance

- For the public demo, follow the homepage into a fresh guest session: inspect the linked recording and composition, the creator's conditions, both requests and approvals, the signed receipt and a rejected altered copy. Check desktop, mobile and keyboard use.
- For organization installation, complete sign-in, setup, catalog preview/commit, client assignment, policy publication, authority review, request assignment, exact-obligation approval, receipt verification, publication report and compliance review. Exercise webhook delivery and DDEX export only when included in the installation.
- Confirm terms, privacy, retention, data-processing, takedown and dispute procedures for the intended deployment.
- Confirm rights limitations, provisional status, settlement evidence, signed reconciliation, auditability, and adapter boundaries are understandable without private explanation.
- Record explicit founder approval before public launch.
