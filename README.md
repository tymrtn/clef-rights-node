# Clef Rights Node

> **Public alpha candidate.** The protocol and reference implementation are open for inspection and testing. Do not use this build as evidence of legal authority, partner acceptance, payment, or production readiness. Start with the [15-minute synthetic walkthrough](docs/QUICKSTART.md), then read the [claims and limits](docs/CLAIMS_AND_LIMITS.md).

Clef Rights Node gives labels, publishers, PROs, CMOs, collectives, and other rights administrators a self-hosted permissions desk for represented creators. It records who claimed authority over a musical work or recording, what use a requester proposed, who approved it, and exactly what the resulting receipt proves; independent artists and requester organizations can also run their own nodes.

The node does not turn a catalog lookup into ownership, infer missing rights, or file a claim merely because an API key is present. Authority requires evidence and a separate operator review. Every approval produces an Ed25519-signed receipt with the policy version, declared scope, decision, and transparency-chain entry.

Clef Rights Node is licensed under `AGPL-3.0-only`. Every staging or production deployment must declare `SOURCE_CODE_URL` for the corresponding source of its exact `SOURCE_CODE_REVISION`; the public node-information endpoint and every console surface disclose both. The operator remains responsible for making that URL complete and accurate, and the launch checklist requires an independent match against the deployed build.

**Future-release licensing:** the [proposed Clef Own-Node License and partner plan](docs/licensing/README.md) permit commercial administration of an organization's own and represented catalogs, with self-installation, Clef-assisted setup, or client-owned installation and support from a separately licensed partner. Hosted/OEM rights require a distinct agreement. The drafts await legal licensor identification, licensing authority review, and designation of covered releases; the current checkout and released alpha retain their AGPL terms. The first release's partner outreach is interest-only, with no paid enrollment or partner entitlement issued.

## Try the prepared demonstrations

With `.venv` and the frontend dependencies installed, run `.venv/bin/python scripts/run_local_preview.py` for a prepared request-to-receipt walkthrough on port `16482`. Run `.venv/bin/python scripts/run_federation_preview.py` for a label and publisher on separate local nodes, with connected catalog search and cross-node permission requests on port `16484`.

Both launchers retain private local state and exercise the real API with fictional catalogs. The [quickstart](docs/QUICKSTART.md) covers the walkthroughs; the [connected-catalog protocol](docs/foundation/CATALOG_FEDERATION.md) covers publication consent, cross-node requests, public terms, peer configuration and current operating limits.

## Run a local label node

You need Docker with Compose. The local stack includes PostgreSQL, the API, migrations, the web console, and supervised webhook and permission-expiry workers.

```bash
cp env.sample .env
docker compose up --build -d --wait
```

Check the database, API, web console, webhook worker, and expiry heartbeat before opening the console:

```bash
docker compose ps
curl --fail http://localhost:9247/health
curl --fail http://localhost:6482/ >/dev/null
```

- Console: [http://localhost:6482](http://localhost:6482)
- OpenAPI: [http://localhost:9247/docs](http://localhost:9247/docs)
- PostgreSQL: `localhost:5446`

Set `CONSOLE_PORT` in `.env` before startup to bind the console elsewhere; the rest of the walkthrough uses the default `6482`.

`env.sample` enables local development links. Enter an email in the console, choose **Open development sign-in link**, and the server will create a short-lived session. No email is sent. Staging and production refuse to start while `ALLOW_DEV_MAGIC_LINKS=true`.

To stop the stack without deleting its database:

```bash
docker compose down
```

To discard the local database and repeat onboarding from zero:

```bash
docker compose down -v
```

## Prepare one label pilot

Start with one client and one composition or recording whose identifiers and authority evidence are already understood. Before opening the setup wizard, assemble:

- separate email addresses for the label administrator, a rights manager, the independent node operator, and a requester;
- the client's stable reference from the label's contract or royalty system;
- an ISWC or a song code from The MLC for a composition, or an ISRC for a recording;
- the contract or registry reference, controlled share, territory, and SHA-256 fingerprint of any private evidence;
- the intended-use policy, including AI source material, model environment, duration, retention, attribution, watermark, and review limits;
- proposed license dates and, if settlement will be tested, exact currency, minimum, royalty basis, and beneficiary splits.

The MLC credentials are optional for a local pilot. DDEX credentials and schema files are needed only when testing MWL exchange. Clef never needs the private contract file itself; keep that file in the label's document system and record its location and fingerprint in the authority claim.

For catalog cleanup, Clef also includes an optional workflow for matching a label's ISRCs against the public Spotify metadata release while keeping every result unverified. The source has no ISWCs and establishes no rights; see [Spotify reference metadata](docs/SPOTIFY_REFERENCE_DATA.md) for the private-storage, matching, and The MLC reconciliation path.

## Walk through the label workflow

### Permission safety and receipt access

Requesters select all applicable content categories and confirm their declaration. Published content restrictions apply alongside the intended use and AI scope. The requested territory must fit the verified authority; the node rechecks the current policy and authority before signing a grant.

Receipt downloads require requester or authority organization access. The console handles authenticated JSON downloads, while independent verification of a supplied receipt and the public hash chain remain available. See the [receipt protocol](docs/foundation/RECEIPT_PROTOCOL.md#access-and-public-transparency) for API scopes, public-log fields and upgrade notes.

An organization owner or administrator sets publication and retention, exports the organization's records, and runs scoped erasure in **Operations → Data privacy**. See [Data privacy](docs/DATA_PRIVACY.md) for the published field set, the approval path, and the operator procedure covering copies this node keeps elsewhere.

### 1. Create the label

Sign in with the label administrator's address. The setup wizard asks for:

1. The label name and a node-local slug.
2. Organization type, default territory, and the rights the label expects to administer.
3. An AI baseline: review every AI request, or block all AI use until a work policy changes it.

Selecting an organization type or right is an operating default, not proof that the organization controls it. A label, publisher, PRO, CMO, collective, administrator, or artist must evidence composition, master, lyrics, performance, voice, and likeness authority separately.

### 2. Add staff

Open **Team**. An organization owner or administrator can add:

- **Rights manager**: may publish policies, submit authority evidence, receive assigned cases, decide requests, and review publication evidence.
- **Member**: may inspect records and submit outbound requests, but cannot publish policies or make rights decisions.
- **Organization administrator**: may manage members and rights workflows.

The added person signs in at the same console with the exact email entered by the administrator. Adding a member does not send an invitation email and does not make that person a node operator.

### 3. Import and assign the client catalog

Open **Catalog** before publishing policies. Create each managed client with a stable reference from the label's contract, royalty, or repertoire system. The reference is node-local and case-normalized; it is safer than matching artists by display name.

Download the CSV template. It accepts these columns:

```text
item_type,title,artist,iswc,isrc,mlc_song_code,territory,client_reference,source_reference
```

A work requires an ISWC or a song code from The MLC. A recording requires an ISRC. Titles are never promoted to identifiers. `client_reference` must match a managed client created in the node. Files are limited to 10 MB and 10,000 rows.

When an imported record already exists, a changed `client_reference` requires explicit conflict resolution, even if its music metadata is identical. A blank cell in that column requests unassignment; omitting the column preserves the current client. Resolving the row creates a new catalog version and retains the earlier assignment history. Use **Append a client assignment** for a direct administration change to an existing version.

Uploading creates a preview, not catalog records. The preview classifies each row as ready, invalid, duplicated within the file, duplicated against the current catalog, or conflicting with the current catalog. Correct invalid source rows and upload again. For a catalog conflict, record why the row should be skipped or preserved as the next immutable version. Exact-file replays return the existing batch.

Commit requires a separate confirmation. Imported assets and client-assignment events are append-only. A later correction creates version 2 while version 1 remains inspectable. Reassigning a work to another client requires a reason and appends assignment history.

Every imported asset is labeled `catalog_metadata` with `authorityStatus: unverified`. Importing a label schedule, a result from The MLC, or a distributor export does not publish a policy, create an authority claim, or authorize a license. CSV intake is working; CWR intake is not part of the production `/v1` workflow yet.

### 4. Publish one work policy

Open **Policies** and select an imported catalog asset; Clef fills its title, artist, and durable work key. You may instead use the configured lookup from The MLC or enter a registry-backed namespace such as `mlc:123456789`, `iswc:T1234567890`, or `isrc:USABC2600001`. Manual `internal:` keys remain possible through the policy API, but they should be treated as provisional identifiers and replaced before external exchange.

For each use, choose `blocked`, `requires_approval`, or `allowed`. AI policy v2 separately records:

- training, fine-tuning, licensed grounding, embeddings, stem extraction, transformation, lyric use, and synthetic voice;
- full mixes, stems, isolated vocals, lyrics, composition data, and reference embeddings;
- private, shared-commercial, and public or open-weight model environments;
- source duration, output duration, lyric input, source retention, and embedding retention limits;
- receipt, watermark, attribution, similarity-review, and deletion-attestation requirements.

Publishing creates immutable version 1. Editing the policy later creates version 2; an approval receipt always identifies the version it evaluated.

The policy editor operates on one work at a time after catalog intake. This keeps catalog metadata, policy decisions, and evidence-backed authority as three distinct records.

### 5. Submit authority evidence

Open **Authority**, select the published policy, choose the right and territory, then enter the registry or contract reference and controlled share. Private contracts remain in the label's document system; an optional `https://`/`urn:` location and SHA-256 fingerprint identify the exact artifact presented for review without uploading it to Clef. The claim begins as `self_asserted`.

The node operator is deliberately separate from the label. Sign in with an address listed in `NODE_OPERATOR_EMAILS`; an operator with no organization goes directly to the evidence-review queue. The operator records what was checked before verifying or rejecting the claim. Verification records that review. It does not create ownership or cure defects in the evidence.

When verification collides with an already verified claim for the same work, right, and overlapping territory, Clef compares the declared controlled shares. Compatible splits totaling 100% or less may coexist. Exclusive claims, missing or invalid shares, and totals above 100% move both claims to `disputed` and open an operator conflict. The operator must record evidence before retaining either claim, accepting a compatible split, or rejecting both. Disputed claims disappear from requester discovery until resolved.

For composition evidence from The MLC, retain its song code and reported U.S. publishing information. The operator supplies supporting evidence of controlled shares and territorial authority when making a claim.

### 6. Register the requester

The producer, agency, developer, or AI company signs in separately and chooses **Requester / producer** during setup. A requester organization declares no catalog authority and cannot publish rights policies or approve claims.

After the label's claim is verified, it appears in the requester's authority directory without the label's private evidence record.

### 7. Request a bounded use

Open **Request permission**. Every request requires:

- a verified authority claim;
- intended use and territory;
- explicit start and end dates in `YYYY-MM-DD` form;
- for AI use, source assets, model environment, durations, lyric volume, and retention periods;
- acceptance of every safeguard required by the published policy.

The API rejects a blocked operation, an out-of-policy numerical limit, an unaccepted safeguard, or a missing term. A request that needs human approval enters both ledgers: outbound for the requester and inbound for the label.

### 8. Decide and verify

The label opens **Permission ledger**. The decision card shows the project, term, source material, model environment, durations, retention, accepted controls, and policy-evaluation trace. A label owner, administrator, or rights manager may assign the pending case to a named rights administrator and record why. Once assigned, no other person or machine credential may decide or review that case until the assignment is cleared. Requesters see that routing occurred, but not the employee's identity or the label's routing note.

Before approval, the reviewer records a decision note and any exact license obligations:

- the credit line as it must appear;
- whether a backlink is required and its exact HTTPS URL;
- required placements, such as the release description, metadata, on-screen credit, liner notes, or a credits page;
- exact metadata fields and values;
- whether publication evidence is required, its deadline after publication, and its frequency.

An AI policy that requires attribution cannot be approved with a vague instruction such as “credit the artist.” The reviewer must supply the exact credit text and at least one placement. Required attribution also requires publication reporting, with a 30-day deadline unless the reviewer chooses another period. Requests created without a term before the current validation gate remain visible but cannot be approved.

Approval issues a receipt containing:

- requester and verified authority organizations;
- work key, right type, territory, term, and declared use;
- AI inputs, model scope, limits, safeguards, and submitted provenance;
- exact credit, backlink, metadata, placement, and publication-reporting obligations;
- authority evidence reference and operator verification note;
- the complete policy snapshot, version, and hash;
- decision actor, timestamp, and note;
- Ed25519 public key, signature, payload hash, and transparency-chain linkage.

Choose **Verify signed receipt** in the ledger. The console independently checks the payload hash, signature, and transparency entry. **Raw receipt JSON** exposes the portable artifact for another verifier.

### 9. Report and review publication evidence

After publication, the requester opens the approved outbound permission and records the public HTTPS URL, publication time, platform, credit actually displayed, backlink, delivered metadata, and an evidence reference such as an archive digest or platform record ID. Clef rejects future timestamps and uses the signed term to reject publications outside the licensed dates.

The ledger compares the requester's declaration with the signed credit, backlink, metadata, and reporting deadline. These comparisons are labeled `comparison_only`: they do not prove what a platform displayed. The assigned rights administrator inspects the cited evidence and appends a `compliant`, `noncompliant`, or `inconclusive` review with a concrete note.

Usage reports and reviews are append-only. Neither a self-report nor an authority review changes the grant automatically. If the evidence supports a dispute, revocation, or correction, an authorized party must create that separate signed lifecycle record. This separation prevents a missing backlink or late report from silently rewriting a valid license.

### 10. Dispute, revoke, correct, or expire a grant

Expand **Dispute, revoke, or correct this grant** in the permission ledger. Either party may open a dispute. Only a rights manager for the verified authority, or that organization's explicitly scoped machine credential, may revoke the grant or mark it corrected. A correction must identify a distinct, active replacement grant receipt for the same work, authority organization, and right.

The original receipt is never rewritten. Each status change creates a separately verifiable `clef.permission-status-receipt.v1` record containing the actor, reason, previous and resulting status, prior receipt hash, and any replacement receipt hash. These records extend the same public transparency chain as grant receipts.

The reference Compose deployment runs one supervised `expiry-worker`. It evaluates declared end dates immediately at startup and daily thereafter, appends one signed expiry record after each term ends, and exposes a heartbeat-based health check. Other platforms should run the `expiry` process declared in `backend/Procfile`; deploy exactly one replica per node. `make expire-due` remains the supervised one-shot command, and the node-operator API exposes the same process at `POST /v1/operator/permission-requests/expire-due`.

### 11. Settle the permission

The verified authority can define one immutable settlement for a pending or approved permission. Record currency in exact minor units, the minimum commitment, whether that minimum recoups against royalties, the royalty rate and basis, and beneficiaries whose shares total exactly 10,000 basis points. The UI and API require an explicit final-terms confirmation; correcting those terms requires a replacement permission rather than rewriting the ledger.

Settlement terms and reserves are `provisional`; neither grants permission. After the signed grant exists:

1. The requester may append a reserve. This records an earmark, not a transfer.
2. The authority calculates each non-overlapping royalty period from an evidenced revenue statement. Clef uses integer half-up rounding.
3. The authority records externally received payments and each beneficiary payout with transaction references and evidence identifiers.
4. The authority reconciles the current ledger. Clef records `paid` only when the positive obligation, received payment, total payouts, and every deterministic beneficiary allocation match exactly. Every reconciliation produces a portable Ed25519 receipt in the permission transparency chain.

Financial history is append-only. Mistakes are corrected with reserve releases, royalty adjustments, payment reversals, or payout reversals. A later entry makes an older reconciliation stale and returns the current assertion to `provisional` until a new reconciliation balances.

Clef records and audits external financial evidence; it does not hold funds or initiate bank transfers. Include a label or administrator commission as an explicit beneficiary if the agreement permits one. Do not omit it from a supposedly complete split.

### 12. Connect the label's own systems

Open **Operations** as an organization owner or administrator. Issue a separate credential for each catalog, clearance, or licensing system, choose only the scopes it needs, and set an expiry between one and 365 days. The bearer secret appears once. Clef stores its SHA-256 digest and visible prefix, never the secret itself.

Available scopes are:

- `directory:read` for the sanitized verified-authority directory;
- `registry:read` for organization-attributed catalog searches through The MLC;
- `rights:read` for this organization's policies;
- `permissions:read` for permission records involving this organization;
- `permissions:request` for creating requests as this organization;
- `permissions:decide` for decisions by this rights-holding organization;
- `permissions:assign` for routing a pending case to a named authority-organization reviewer or returning it to the shared queue;
- `permissions:lifecycle` for party disputes and authority-controlled revocation or correction;
- `compliance:report` for a requester to append publication, credit, backlink, metadata, and evidence declarations after a signed grant;
- `compliance:review` for a decision-capable authority to append a compliance finding without changing permission status;
- `settlements:read` for financial records involving this organization;
- `settlements:write` for authority terms, royalty/payment/payout evidence, or requester reserves;
- `settlements:reconcile` for a rights authority to record a balanced or provisional reconciliation;
- `catalog:read` for managed clients, staged imports, and catalog versions;
- `catalog:write` for clients, previews, conflict resolution, commits, and assignment history;
- `ddex:read` for retained exchanges and acknowledgement evidence involving this organization;
- `ddex:write` for party-authorized MWL export and append-only partner acknowledgement evidence;
- `webhooks:read` for endpoints, subscriptions, delivery state, and attempt history;
- `webhooks:write` for endpoint creation, secret rotation, test events, disablement, and manual retries;
- `audit:read` for this organization's append-only audit events.

Send the secret as a bearer credential:

```bash
curl --fail http://localhost:9247/v1/directory/authority-claims \
  -H "Authorization: Bearer $CLEF_API_TOKEN"
```

A credential is fixed to one organization. It cannot read another tenant, act for an organization that is not a party, bypass authority verification, or perform an unlisted scope. Machine-created permission, lifecycle, settlement, catalog, webhook, DDEX exchange, and acknowledgement records retain the credential ID and organization. Signed permission and settlement receipts also name the machine actor. Revocation takes effect on the next request.

The organization audit trail records successful state changes by people, machine credentials, policies, schedulers, and node operators. Node operators see the cross-organization trail in their own console. These v1 records are protected against update and deletion at both the application and database layers.

### 13. Connect outbound events

Open **Operations → Outbound webhooks** as an organization owner or administrator. Enter the receiver URL and select individual events or the wildcard. Clef generates a signing secret once, stores it as AES-GCM ciphertext, and shows only its final four characters afterward. Copy the plaintext directly into the receiver's secret manager.

The business change and its delivery outbox commit in the same database transaction. The `webhook-worker` service later sends canonical JSON with `X-Clef-Delivery`, `X-Clef-Event`, `X-Clef-Timestamp`, and `X-Clef-Signature`. The signature is HMAC-SHA256 over `<timestamp>.<raw-body>` and uses the `v1=<hex>` form. Receivers should reject stale timestamps and compare signatures in constant time.

Transient network errors, HTTP 408, 425, 429, and 5xx responses retry with bounded backoff. Other HTTP failures move directly to the dead-letter state. Every attempt is append-only. Operations shows pending, retrying, successful, and dead-lettered records; a manual retry appends another attempt.

Redirects are not followed. Hostnames are resolved at delivery time, and private, local, reserved, or otherwise non-public addresses fail closed. Production requires HTTPS and a separate `WEBHOOK_ENCRYPTION_KEY_B64`. Secret rotation affects the next attempt, so update the receiver before rotating.

## The MLC and DDEX connectors

Operators supply their own credentials and partner configuration through a deployment secret manager. Clef does not bundle keys or infer authorization from a populated environment variable.

### The MLC

Set:

```dotenv
MLC_ENABLED=true
MLC_USERNAME=...
MLC_PASSWORD=...
MLC_AUTHORIZED_CAPABILITIES=catalog_lookup,ownership_evidence_read
```

The adapter returns results as `observed`, permission status as `unknown`, and a `sourceScope` describing The MLC’s U.S. publishing context and DSP-supplied recording metadata. Master ownership, master shares and authority for each right and territory come from separately reviewed rightsholder evidence. The MLC API connection supports catalog identification and publishing review.

The console uses the organization-scoped lookup route. A machine credential needs `registry:read` and can query only on behalf of its own organization. Each successful lookup appends an audit record containing the query fields, query digest, result count, and machine or human actor; raw search values are not copied into the audit trail. The client reuses short-lived tokens, refreshes once after a 401, applies bounded retries to transient failures, and rejects oversized or malformed responses.

### DDEX MWL 1.0.1

The identifier is a **DPID** (DDEX Party Identifier), not an SPID. DDEX permits evaluation and test implementation without membership. Before commercial production exchange, the node operator must accept the free DDEX Implementation Licence and apply for a DPID at [dpid.ddex.net](https://dpid.ddex.net/register). Prepare the operating entity's full name and address plus administrative, technical, and financial contacts; the same person may fill all three roles. DDEX emails the allocated DPID and registry credentials after submission. Registry users can see the entity name and street address, so use an approved corporate or registered-office address rather than a founder's home address. This is an identity and licence step; it does not establish a messaging relationship with The MLC or another recipient.

Install the exact MWL 1.0.1 schemas published by DDEX and the imported W3C XMLDSIG schema:

```bash
make install-ddex-schemas
```

The installer downloads the [official MWL 1.0.1 archive](https://service.ddex.net/doc/PastStandards/MWL%201.0.1%20XSD.zip), verifies the pinned archive and file digests, installs the three files under `var/ddex/mwl-1.0.1`, and validates Clef's request, grant, and rejection messages. Docker Compose mounts that directory read-only at `/run/secrets/ddex`. The downloaded schemas remain untracked because DDEX retains their copyright.

Set:

```dotenv
DDEX_ENABLED=true
DDEX_IMPLEMENTATION_LICENSE_CONFIRMED=true
DDEX_DPID=...
DDEX_PARTNER_DPID=...
DDEX_SENDER_NAME=...
DDEX_PARTNER_NAME=...
DDEX_PROFILE=mwl-1.0.1
DDEX_SCHEMA_DIR=./var/ddex/mwl-1.0.1
DDEX_MWL_XSD_PATH=/run/secrets/ddex/us-works-licensing-choreography.xsd
DDEX_LIVE_MESSAGES=false
DDEX_AUTHORIZED_CAPABILITIES=permission_request_exchange
```

`DDEX_DPID` is Clef's sender identity. Enter its 18-character message form without display hyphens, such as `PADPIDA3897722461G`; Clef validates the ISO 7064 check character. `DDEX_PARTNER_DPID` belongs to the specific recipient that has agreed to exchange MWL messages with Clef; it cannot be inferred from the MLC Public Search API account. The partner must also provide or approve the SFTP or web-service endpoint, authentication, acknowledgement semantics, and conformance cases. Keep `DDEX_LIVE_MESSAGES=false` until that bilateral test passes.

After configuring the connector, open an eligible composition permission in **Permission ledger → DDEX MWL exchange**. The requester can generate a license-request message; after approval or rejection, the authority can generate the decision. The console requires an explicit US musical-work-only confirmation, previews the schema-valid XML, retains its SHA-256 digest, and offers the portable XML file. Organization-bound credentials with `ddex:write` can perform the same party-specific exports; `ddex:read` retrieves retained evidence.

After a partner or transport responds, either exchange party may append the observed transport or business acknowledgement, partner message identifier, raw response, and external evidence reference. Clef retains the raw payload digest, actor, timestamp, and idempotency key. These records are immutable observations with `effectOnPermission: none`; even an `accepted` response does not itself grant permission or prove authority.

MWL export fails for Clef derivative-remix and AI scopes because those receipts contain rights and controls MWL cannot represent. Master, lyric, voice, likeness, and AI rights remain in the Clef receipt. The XML is an exchange artifact, not proof that a partner accepted or processed it.

Re-download the pinned schemas into a temporary directory and validate the request, grant, and rejection fixtures independently:

```bash
make verify-ddex
```

## Production configuration

Start from `env.sample`, store secrets outside the repository, and replace every example identity. Production requires:

```dotenv
APP_ENV=production
DEMO_MODE=false
MOCK_INTEGRATIONS=false
ALLOW_DEV_IDENTITY_HEADERS=false
ALLOW_DEV_MAGIC_LINKS=false
DATABASE_URL=postgresql+psycopg2://...
RIGHTS_MAGIC_LINK_SECRET=...
NODE_ID=urn:your-company:rights-node:production
NODE_DEPLOYMENT_MODE=adopter_production
NODE_SIGNING_PRIVATE_KEY_B64=...
SOURCE_CODE_URL=https://github.com/your-organization/clef-rights-node/tree/<full-git-commit-hash>
SOURCE_CODE_REVISION=<same-full-git-commit-hash>
WEBHOOK_ENCRYPTION_KEY_B64=...
NODE_OPERATOR_EMAILS=rights-ops@example.com
NOTIFICATION_PROVIDER=smtp
NOTIFICATION_FROM_EMAIL=Rights Desk <rights@example.com>
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_SECURITY=starttls
CONSOLE_BASE_URL=https://rights.example.com
CORS_ALLOW_ORIGINS=https://rights.example.com
```

SMTP is the portable default, but Mailgun remains supported with `NOTIFICATION_PROVIDER=mailgun`, `MAILGUN_API_KEY`, and `MAILGUN_DOMAIN`. The adopter supplies and controls every email credential; Clef ships none.

Generate `RIGHTS_MAGIC_LINK_SECRET` with a cryptographically secure secret generator. Generate the Ed25519 key in the destination secret manager or an offline environment; the value is a URL-safe base64 encoding of the raw 32-byte private key. Keep the same key across restarts. A missing key creates an ephemeral development identity, and production refuses it. Set `SOURCE_CODE_REVISION` from the full Git commit hash deployed, and make `SOURCE_CODE_URL` resolve to downloadable corresponding source for that same revision rather than a moving default branch.

Set `NODE_DEPLOYMENT_MODE` to `local_evaluation`, `public_sandbox`, `adopter_staging`, or `adopter_production`. Public-sandbox mode is fail-closed: startup rejects live integrations with The MLC, DDEX, MusicBrainz, OpenRouter, and Slack, while the console identifies the deployment as synthetic on every durable screen. `SANDBOX_GUEST_ACCESS=true` adds rate-limited, anonymous, short-lived sessions only in that mode; it never accepts an email address or creates an identity usable by another deployment.

Terminate HTTPS before the web service, encrypt PostgreSQL storage and backups, restrict database access, configure log retention, and test email delivery before inviting users. The application rejects production startup when the required security settings are absent.

Read [Self-Hosting](docs/SELF_HOSTING.md) before deployment and complete every item in the [Launch Checklist](docs/LAUNCH_CHECKLIST.md).

## Qualify the first real catalog pilot

The synthetic 30-gate verifier proves the software path; it cannot prove that an organization actually administers a catalog, that its private authority evidence is authentic, or that money moved. The first release therefore requires a separate read-only acceptance run against one completed real permission.

Copy [the pilot manifest template](fixtures/pilot_manifest.example.json) to a private working location. Enter the authority and requester organization IDs, approved permission ID, durable work key, managed-client reference, exact authority-evidence reference and SHA-256, and SHA-256 of the published URL. The optional local evidence-file path is read only to confirm its digest; neither the path nor document contents enter the report or node.

Issue a short-lived authority-organization API credential with only `catalog:read`, `rights:read`, `permissions:read`, and `settlements:read`. Inject it as `CLEF_PILOT_API_TOKEN` through the operator's secret manager, then run:

```bash
PILOT_MANIFEST=/private/path/pilot.json \
PILOT_REPORT=/private/path/pilot-acceptance.json \
make verify-real-pilot
```

The verifier never creates or changes a node record. It checks 12 independent chains: stable node identity, corresponding source, required adapter capabilities, managed catalog assignment, versioned policy, assigned human decision, exact obligations, signed authority receipt, requester/authority separation, publication and compliance evidence, balanced external payment, and signed reconciliation. It exits nonzero on any mismatch or unknown manifest field; `--synthetic-run` can test the machinery but can never produce `qualified: true`.

## Dependency updates

The container and CI install the complete Python dependency set from `backend/requirements.lock` with hashes enforced. Local development uses `.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock`. Keep `backend/requirements.txt` as the direct dependency input.

For an update, change the intended direct pins, then run `uv pip compile backend/requirements.txt --universal --python-version 3.11 --generate-hashes --output-file backend/requirements.lock`. Inspect the resolved changes and run `uvx --from pip-audit==2.10.1 pip-audit --require-hashes --disable-pip -r backend/requirements.lock`. Complete the application, PostgreSQL migration, receipt and container checks before adopting the new lock. CI reports newly published advisories so operators can schedule a reviewed update.

## Repeatable acceptance checks

Install `scripts/requirements-test-reference.txt` into the test environment to exercise the synthetic Spotify–The MLC reconciliation fixtures. CI installs this dependency explicitly; it requires no catalog download or partner credentials.

The same rightsholder verifier can exercise PostgreSQL. Provision a dedicated empty test database, place its `postgresql+psycopg2` URL in `CLEF_WORKFLOW_POSTGRES_URL`, then run:

```bash
.venv/bin/python scripts/verify_rightsholder_workflow.py --postgres-test-url-env CLEF_WORKFLOW_POSTGRES_URL
```

This command migrates the test database and leaves synthetic workflow records for inspection. It refuses databases containing user objects before running migrations. Use a fresh database for each run; the verifier does not delete existing data. The report identifies `databaseDialect`, and CI runs PostgreSQL workflow acceptance separately from fresh migration upgrade/downgrade checks. The default command continues to use a temporary SQLite database.

Run these after a code change or deployment configuration change:

```bash
make verify-alpha
```

That single command runs the backend suite, production frontend build, 30-gate synthetic rights-holder workflow, pinned DDEX fixtures, deployment-configuration checks, public-history privacy and credential scan, and patch-whitespace validation. `make verify-public` can run the repository scan independently; it examines every public Git blob plus the current non-ignored working tree and never prints matched secret values.

`make verify-workflow` creates and migrates a fresh temporary database, then tests four independent identities: label owner, client rights manager, node operator, and requester. Its 30 gates cover migration state, one-time authentication, organization-role separation, scoped and revocable machine credentials, cross-tenant rejection, previewed catalog import, client assignment, immutable catalog correction, policy publication, encrypted durable webhooks, evidence review, sanitized discovery, derivative and AI permission requests, named-reviewer routing, signed exact credit obligations, publication reporting, authority compliance review, database-trigger immutability, signed machine and human actions, reserve and royalty calculations, external payment and beneficiary payouts, paid reconciliation, audit records, tamper rejection, transparency linkage, and session revocation. It prints a small JSON evidence record and supports `--output PATH` when a CI job needs to retain it.

## What is and is not ready

Working now:

- authenticated organizations, requester-only organizations, and scoped team roles;
- preview-first CSV catalog import, managed-client assignment, exact-file idempotency, duplicate classification, explicit conflict resolution, and append-only catalog versions;
- versioned rights-policy v2 records and nuanced AI-use evaluation;
- evidence-backed authority review, controlled-share conflict detection, and recorded operator resolution;
- inbound and outbound permission ledgers with named administrative routing, mandatory license terms, and requester-safe routing disclosure;
- signed exact credit, backlink, placement, metadata, and publication-reporting obligations, plus append-only requester reports and authority compliance reviews;
- immutable Ed25519 grant, dispute, revocation, correction, and scheduled-expiry receipts with inline verification, tamper detection, and one transparency chain;
- organization-scoped API credentials with one-time secrets, explicit scopes, expiry, immediate revocation, durable machine actors, and console administration;
- append-only organization and node-operator audit views covering the production v1 rights workflow;
- AES-GCM-encrypted webhook endpoints, atomic delivery outbox, restart-safe worker, bounded retries, dead letters, append-only attempts, and browser administration;
- immutable settlement terms, reserves, royalty calculations, evidence-backed payments and beneficiary payouts, reversals, deterministic split allocation, and current-ledger reconciliation;
- hardened, organization-attributed lookup through The MLC with observed-only results and schema-validated DDEX MWL browser/machine export with append-only acknowledgement evidence;
- opt-in connected catalogs among configured, key-pinned peers: consented publication, signed search, account-free public terms, and permission requests that the source node decides and receipts (a working candidate with a two-node local proof).

Still required before a public production launch:

- bilateral DDEX partner conformance, production transport automation, and a production operating agreement;
- legal review of terms, privacy, evidence policy, retention, and the meaning of each offered permission.

Do not describe the node as an automated substitute for The MLC, a PRO, DDEX exchange, payment processing, or royalty filing. Clef currently records external settlement evidence; partner delivery and money movement are not implemented.

## Protocol documentation

- [Quickstart](docs/QUICKSTART.md)
- [Claims and limits](docs/CLAIMS_AND_LIMITS.md)
- [Deployment matrix](docs/DEPLOYMENT_MATRIX.md)
- [Public review packet](docs/REVIEW_PACKET.md)
- [Case-study protocol](docs/CASE_STUDY_PROTOCOL.md)
- [RFC process](docs/RFC_PROCESS.md)
- [Foundation spec](docs/foundation/FOUNDATION_SPEC.md)
- [Trust model](docs/foundation/TRUST_MODEL.md)
- [Receipt protocol](docs/foundation/RECEIPT_PROTOCOL.md)
- [Data privacy](docs/DATA_PRIVACY.md)
- [AI policy schema](docs/foundation/AI_POLICY_SCHEMA.md)
- [Adapter contract](docs/foundation/ADAPTER_CONTRACT.md)
- [Self-hosting](docs/SELF_HOSTING.md)
- [Launch checklist](docs/LAUNCH_CHECKLIST.md)

The inherited demo can still be evaluated with `env.demo.sample` and `VITE_DEMO_MODE=true`. Production images default to the authenticated Rights Node console; demo routes remain unavailable while `DEMO_MODE=false`.

## Participate in the alpha

- Operators: deploy a synthetic node and file a deployment report.
- Rights administrators: apply for the first controlled public case through Clef.pro after the application route is published.
- Protocol and security reviewers: use the review packet and report security defects privately.
- Implementers: propose compatibility changes through an RFC; report standards gaps without implying endorsement by a standards body.

The roadmap tracks product intent, not commitments. Any claim of approval or endorsement by The MLC, DDEX, a PRO, CMO, label, publisher, platform, or coalition requires a dated public statement.
