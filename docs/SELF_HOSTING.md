# Self-Hosting

Local frontend development requires Node.js `^20.19.0` or `>=22.12.0`. CI and the production web image use Node 22.

## Required production configuration

- `APP_ENV=production`
- `DEMO_MODE=false`
- `MOCK_INTEGRATIONS=false`
- `ALLOW_DEV_IDENTITY_HEADERS=false`
- `ALLOW_DEV_MAGIC_LINKS=false`
- Durable `DATABASE_URL`
- Strong `RIGHTS_MAGIC_LINK_SECRET`
- Persistent `NODE_SIGNING_PRIVATE_KEY_B64`
- Immutable deployed release or commit in `SOURCE_CODE_REVISION`
- Public HTTPS `SOURCE_CODE_URL` containing the corresponding source for that exact revision
- Separate persistent `WEBHOOK_ENCRYPTION_KEY_B64`
- Stable `NODE_ID`
- Accurate `NODE_DEPLOYMENT_MODE`; reserve `public_sandbox` for synthetic public evaluation
- One or more `NODE_OPERATOR_EMAILS`
- A configured email provider for one-time magic-link delivery
- HTTPS termination and encrypted database storage

The application refuses production startup when these invariants are not met. It publishes the software license, source URL, and revision at `/v1/node/info`; the web console shows the same corresponding-source link before and after sign-in. Point the URL at an immutable release archive, tag, or commit that contains the complete source for the deployed build, including operator modifications, and keep it available for as long as that build is offered over the network.

Production imports never create tables from ORM metadata. The API compares the database's `alembic_version` with the repository migration head and refuses startup on an unversioned, stale, or divergent revision. Run `alembic upgrade head` as a release step; the reference API image does this before starting Uvicorn. CI also runs `alembic check` against SQLite and PostgreSQL so an at-head database cannot silently drift from the ORM metadata.

The web image serves the console and proxies same-origin `/api` requests to the API service. Keep that path same-origin in production unless you deliberately configure a narrow, non-wildcard CORS allowlist.

## Bring-your-own connectors

Each operator provides credentials through its deployment secret manager. Keys are never bundled with the source or shared with Clef.

### MLC

Set `MLC_ENABLED`, `MLC_USERNAME`, `MLC_PASSWORD`, and `MLC_AUTHORIZED_CAPABILITIES`. Declare only the capabilities your account and agreement authorize. Staging and production require an HTTPS `MLC_BASE_URL` without embedded credentials. Read results are returned as `observed`, with permission status `unknown`.

`MLC_CONNECT_TIMEOUT_SECONDS`, `MLC_READ_TIMEOUT_SECONDS`, `MLC_MAX_RETRIES`, and `MLC_MAX_RESPONSE_BYTES` bound connector failure behavior. The client honors `Retry-After`, retries transient POST-based searches, refreshes once after a 401, and reports reachability and its last verified timestamp through the capability endpoint. Keep the operator's MLC account in the deployment secret manager. Organization integrations receive only a Clef credential with `registry:read`; they never receive the MLC username or password.

### DDEX

For evaluation, run `make install-ddex-schemas`. It downloads the official DDEX MWL 1.0.1 archive and W3C XMLDSIG schema, verifies pinned digests, installs the files under `var/ddex/mwl-1.0.1`, and validates all three Clef MWL message profiles. Compose mounts that directory read-only at `/run/secrets/ddex`; set `DDEX_MWL_XSD_PATH=/run/secrets/ddex/us-works-licensing-choreography.xsd`.

Before production, accept the free DDEX Implementation Licence and apply for a DPID at [dpid.ddex.net](https://dpid.ddex.net/register). No DDEX membership is required. The registry exposes the DDEX party's name and street address to registry users; use the operating entity and an address approved for that disclosure. Then set `DDEX_ENABLED`, record licence confirmation, provide the sender DPID and name, select `DDEX_PROFILE=mwl-1.0.1`, and declare `permission_request_exchange` only after bilateral authorization. DDEX schemas are downloaded from their publishers and are not redistributed by this project.

The recipient's DPID, endpoint, authentication, acknowledgement semantics, and conformance cases come from the recipient's bilateral onboarding process. The MLC Public Search API credentials authorize catalog lookup only; they do not identify an MWL recipient or authorize message delivery.

`DDEX_LIVE_MESSAGES` defaults to false. Enable it only in production after partner conformance testing; otherwise every export is marked `TestMessage`. Generated, schema-valid XML and its digest are retained as an interchange audit artifact. Exchange parties can append observed transport or business acknowledgements through the console or `ddex:write` API; the payload, digest, evidence reference, actor, and idempotency key are retained without changing permission status. Protect database storage with operator-managed encryption at rest and retention controls.

Clef does not deliver to a partner transport automatically. Configure SFTP, AS2, API, or another agreed channel outside the node, then record its response. Do not interpret a recorded acknowledgement as legal acceptance unless the governing agreement independently gives it that effect.

MWL is US-specific and covers musical-work license requests and license grants or rejections. Clef receipt rights outside that standard—including master, adaptation, lyrics, voice, and likeness permissions—remain distinct and are never represented as DDEX rights.

Run `make verify-ddex` to download the pinned official schema archive and validate Clef's request, grant, and rejection profiles end to end.

### Other adapters

New adapters must implement the capability contract in `docs/foundation/ADAPTER_CONTRACT.md`, report configuration separately from authorization, and fail closed.

## Money movement, identity, and sanctions boundary

Clef is a settlement evidence ledger, not a bank, escrow service, payment processor, tax engine, sanctions-screening provider, or KYC vendor. A `payment_received` or `payout` entry records an external transaction reference and evidence identifier; it never initiates a transfer or proves that the operator completed legally required onboarding.

The deploying organization must select and contract with its own payment provider, verify each payee and beneficial owner, collect required tax information, apply sanctions and territory controls, handle withholding and reversals, and retain the governing records. Unmatched, disputed, blocked, or unverified amounts remain outside Clef in the operator's suspense or trust-account process and must not be entered as a completed payout.

Only append a payout after the external provider reports a final transaction identifier and the operator's compliance process permits the payment. Clef can then reconcile that evidence to deterministic beneficiary allocations; a `paid` receipt means the current Clef ledger balances, not that Clef independently performed KYC, screened sanctions, held funds, or moved money.

## Signing keys

The node uses an Ed25519 private key encoded as URL-safe base64. Generate it directly in the destination secret manager or another trusted offline environment. Never store it in `.env` files committed to source control.

Changing the key changes the node key identifier. Publish rotations as signed transparency records before retiring the prior key.

## Permission expiry scheduler

Run exactly one expiry worker per node. Docker Compose includes `expiry-worker`; other platforms should deploy the `expiry` process declared in `backend/Procfile`. It runs immediately at startup and then every `EXPIRY_WORKER_INTERVAL_SECONDS` (24 hours by default), examines active and disputed grants, and appends a signed `expiry` record effective at midnight following the final licensed day. Repeated runs are idempotent.

The worker writes a heartbeat after each successful batch, and the Compose health check fails when that heartbeat becomes stale. Alert on an unhealthy worker or repeated batch errors. `make expire-due` remains available for a supervised one-shot run. An absent or unhealthy expiry worker can leave ended grants displayed as approved, so do not scale this process to zero or run multiple unsupervised replicas.

## Webhook delivery worker

Run `python webhook_worker.py` continuously beside the API. The Docker Compose stack includes this process as `webhook-worker`; other platforms should deploy the `worker` process declared in `backend/Procfile`. Monitor worker restarts, the age of the oldest pending delivery, retry volume, and dead-letter count. `make deliver-webhooks` processes one supervised batch for diagnosis.

Generate `WEBHOOK_ENCRYPTION_KEY_B64` as 32 random bytes encoded with URL-safe base64 and store it separately from the Ed25519 signing key. Losing it makes endpoint signing secrets unreadable. Rotating it requires decrypting and re-encrypting endpoint records under controlled maintenance; rotating an individual endpoint secret is available in Operations and does not rotate the storage key.

Production accepts only HTTPS receivers, never follows redirects, and rejects DNS results in private, local, reserved, or otherwise non-public address ranges. Keep `WEBHOOK_ALLOW_PRIVATE_TARGETS=false`. Receiver applications should verify the signature against the exact request bytes, enforce the timestamp tolerance, deduplicate on `X-Clef-Delivery`, and return 2xx only after durable acceptance.

## Machine credentials and audit retention

Issue organization API credentials in **Operations** after the first human administrator signs in. Use one credential per integration, grant only the documented scopes, set a short expiry, and copy the secret directly into the integration's secret manager. The node returns the secret once and stores only its digest. Rotation means issuing a replacement, updating the client, confirming `lastUsedAt`, and revoking the old credential.

Bearer credentials are organization-bound. They do not inherit the creator's node role and cannot cross tenant boundaries. A machine decision or lifecycle event is attributed to the credential itself; the implementation never creates a synthetic user to satisfy an actor field.

`rn_audit_events`, catalog assets and assignments, permission review assignments, requester usage reports, authority compliance reviews, DDEX exchanges and acknowledgements, webhook events and attempts, and the settlement terms, beneficiary, entry, and reconciliation tables are append-only. Alembic installs database triggers that reject updates and deletes, while the application also rejects ORM mutation. Include these tables, mutable delivery state, encrypted endpoint secrets, and signed receipt records in encrypted backups. Establish a retention policy that preserves rights evidence, security investigations, privacy obligations, and litigation holds. Database superusers still control the database and must be limited and monitored outside Clef.

Migration `0013_ddex_acknowledgements` refuses to downgrade after an acknowledgement or machine-authored exchange exists because revision `0012` cannot preserve those actors and records. Restore into a compatible release instead of deleting or misattributing evidence to force a rollback.

Migration `0015_permission_administration` refuses to downgrade after any review assignment, usage report, compliance review, or non-empty license obligation exists. Revision `0014` has nowhere to preserve those records. Restore into a compatible release instead of deleting evidence to force a rollback.

The legacy `rc_api_tokens`, `rc_audit_log`, and synchronous `rc_webhooks` tables belong to explicit demo mode. Production routes use `rn_api_credentials`, `rn_audit_events`, and the `rn_webhook_*` outbox tables; do not expose the legacy endpoints.

## Launch gates

Before exposing a node publicly, complete `docs/LAUNCH_CHECKLIST.md`. Connector credentials alone do not authorize filing, delivery, licensing, or representation; operators must separately establish every partner capability they enable.

For the reference Railway topology, follow `docs/RAILWAY_DEPLOYMENT.md`. Keep staging founder-only until the exact deployed source can be offered to every network user and the public-launch gates are signed off.

After the founder completes one real catalog workflow, run `PILOT_MANIFEST=/private/path/pilot.json PILOT_REPORT=/private/path/report.json make verify-real-pilot`. The verifier is read-only and requires a short-lived authority credential with `catalog:read`, `rights:read`, `permissions:read`, and `settlements:read`; it never stores the credential or private authority document. Keep the resulting compact JSON with the release evidence, then revoke the credential.
