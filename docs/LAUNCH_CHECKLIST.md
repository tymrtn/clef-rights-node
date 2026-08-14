# Launch Checklist

## Automated gates

- `make test-local` passes.
- `make verify-ddex` passes against the pinned official MWL schemas.
- `make verify-deployment` passes for the API, web, webhook-worker, and expiry-worker Railway profiles.
- `make verify-workflow` passes label/client role separation, requester isolation, scoped machine credentials, cross-tenant rejection, derivative and AI permission scopes, named-reviewer enforcement, signed exact obligations, publication and compliance evidence, reserve/royalty/payment/payout reconciliation, signed grant/settlement/dispute/revocation verification, audit attribution, tamper rejection, and transparency-chain checks.
- Fresh SQLite and PostgreSQL databases migrate through the latest Alembic revision, survive downgrade/re-upgrade, and pass `alembic check` without ORM drift.
- Production startup rejects unversioned, stale, or divergent database schemas instead of creating missing tables.
- Production frontend build and production-dependency audit pass.
- API and web container images build; API health and web proxy smoke tests pass.
- Production startup rejects demo flags, wildcard CORS, ephemeral signing keys, and missing mail delivery.
- Production startup rejects a missing corresponding-source URL or development revision; `/v1/node/info` and the console identify the deployed AGPL source revision.
- Public-sandbox mode rejects live MLC, DDEX, MusicBrainz, OpenRouter, and Slack integrations; the console displays its synthetic non-production warning and immutable source revision.
- Anonymous sandbox access is rate-limited, uses generated `.invalid` identities, expires with the normal session TTL, accepts no guest email, and cannot be enabled in adopter modes.
- The signed expiry runner is idempotent; exactly one supervised worker is healthy and its success heartbeat is current.
- Overclaimed authority moves out of discovery, valid split ownership remains discoverable, and operator conflict resolution is access-controlled.
- Credential secrets are returned once, only digests persist, expiry and revocation fail closed, and database-level audit update/delete attempts are rejected.
- Review assignments, requester usage reports, and authority compliance reviews reject update/delete at the ORM and database layers; reviewer identity remains private from the requester.
- Catalog uploads require durable identifiers, preview cleanly, block unresolved rows, preserve corrections as versions, and never create authority.
- Webhook secrets remain encrypted, events and attempts reject update/delete, retries survive a worker restart, and private-network targets fail closed.
- DDEX credentials remain party- and scope-bound; exchange and acknowledgement records reject mutation; acknowledgement retries are idempotent and never change permission status.
- MLC lookups use bounded transport settings, refresh expired credentials once, remain organization-scoped for machines, and enter the audit trail only as observed registry reads.

## Operator gates

- The operator has accepted the free DDEX Implementation Licence, received its DPID from `dpid.ddex.net`, and kept the registry record current.
- `make install-ddex-schemas` succeeds, the schema directory is mounted read-only, and the production container reports the pinned MWL profile as configured.
- Durable Ed25519 signing key is generated, backed up, and protected in the deployment secret manager.
- `SOURCE_CODE_URL` resolves without authentication to the complete corresponding source for the immutable `SOURCE_CODE_REVISION` actually deployed.
- HTTPS, encrypted database storage, backups, restore tests, retention, logging, alerting, and incident contacts are configured.
- Node operator emails, organization memberships, and authority-review responsibilities are verified.
- The pilot label has named owners for the shared request queue, reassignment, exact license terms, publication-evidence review, and escalation into dispute or revocation.
- Machine credentials are inventoried by owner, integration, scope, expiry, rotation date, and revocation procedure; no integration shares a bearer secret.
- The separate webhook encryption key is backed up, worker lag and dead letters are monitored, receiver secrets are inventoried, and a receiver verifies timestamped signatures.
- Each adapter capability is enabled only after account, agreement, partner, conformance, and territorial authority are documented.
- Partner transport, delivery receipt capture, acknowledgement semantics, and escalation ownership are exercised against the bilateral DDEX operating agreement.
- Complete one real controlled settlement with immutable terms, external payment evidence, every beneficiary payout, zero reconciliation variance, and founder review before publishing any royalty-distribution claim.
- Confirm the external payment provider owns KYC, beneficial-owner, tax, sanctions, withholding, suspense, reversal, and money-movement duties; Clef records only final evidence.
- `make verify-real-pilot` returns `qualified: true` for that controlled catalog, and its short-lived read-only credential is immediately revoked.
- Terms, privacy, acceptable-use, takedown, dispute, sanctions, and data-processing policies receive qualified review.

## Founder acceptance

- Complete sign-in, organization setup, catalog preview/commit, client assignment, policy publication, authority claim, request, reviewer assignment, exact-obligation approval, receipt verification, publication report, compliance review, webhook test, and DDEX export in a production-like browser.
- Confirm rights limitations, provisional status, settlement evidence, signed reconciliation, auditability, and adapter boundaries are understandable without private explanation.
- Record explicit founder approval before public launch.
