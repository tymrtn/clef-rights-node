# Railway Deployment

This topology keeps the project, database, domains, keys, email account, backups, and connector credentials in the adopting organization's Railway account. Public access remains gated by corresponding-source availability, legal review, and the operator checks in `LAUNCH_CHECKLIST.md`.

## Services

Create one Railway project with five services:

1. **Postgres** - Railway-managed PostgreSQL.
2. **api** - repository root directory `/backend`, config path `/backend/railway.json`.
3. **webhook-worker** - root `/backend`, config `/backend/railway.worker.json`, no public domain.
4. **expiry-worker** - root `/backend`, config `/backend/railway.expiry.json`, exactly one replica, no public domain.
5. **web** - root `/frontend`, config `/frontend/railway.json`, public HTTPS domain.

The API config runs `alembic upgrade head` as a pre-deploy gate, then the Docker image repeats the idempotent migration before startup. The workers share the API database but do not run migrations. The web service proxies same-origin `/api` requests to the API over Railway private networking.

## API and worker variables

Set these on the API and both workers unless a line says otherwise. A Railway template should generate the three core keys with the expressions in `deploy/railway/template-spec.json`; manual deployments may generate them locally with `scripts/bootstrap_env.py`.

```dotenv
APP_ENV=staging
DEMO_MODE=false
MOCK_INTEGRATIONS=false
ALLOW_DEV_IDENTITY_HEADERS=false
ALLOW_DEV_MAGIC_LINKS=false
DATABASE_URL=${{Postgres.DATABASE_URL}}
RIGHTS_MAGIC_LINK_SECRET=<secret-manager value>
NODE_ID=urn:clef:rights-node:${{RAILWAY_PROJECT_ID}}
NODE_DEPLOYMENT_MODE=adopter_staging
NODE_SIGNING_PRIVATE_KEY_B64=<persistent Ed25519 private key>
SOURCE_CODE_REVISION=<publisher-bound full Git commit hash>
SOURCE_CODE_URL=<publisher-bound HTTPS corresponding-source URL naming that revision>
WEBHOOK_ENCRYPTION_KEY_B64=<separate persistent 32-byte key>
NODE_OPERATOR_EMAILS=<operator email>
AUTH_SIGNUP_MODE=operator_only
NOTIFICATION_PROVIDER=smtp
NOTIFICATION_FROM_EMAIL=Rights Desk <rights@<adopter-domain>>
SMTP_HOST=<adopter mail server>
SMTP_PORT=587
SMTP_USERNAME=<adopter-entered sealed value>
SMTP_PASSWORD=<adopter-entered sealed value>
SMTP_SECURITY=starttls
CONSOLE_BASE_URL=https://<web-domain>
CORS_ALLOW_ORIGINS=https://<web-domain>
STRUCTURED_LOGGING=true
WEBHOOK_ALLOW_PRIVATE_TARGETS=false
```

SMTP is the portable default. An adopter may instead set `NOTIFICATION_PROVIDER=mailgun`, `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, and `NOTIFICATION_FROM_EMAIL`; remove the SMTP values in that case. Public-sandbox deployments set `NOTIFICATION_PROVIDER=disabled`, while adopter staging and production fail startup without a complete provider.

Only the API needs a public or private service endpoint. The web service should be the sole public application domain. Keep the staging source repository private only while access is restricted to the founder; make the exact corresponding source available to every network user before inviting anyone else.

## Web variables

```dotenv
PORT=8080
API_UPSTREAM=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}
VITE_API_BASE=/api
VITE_DEMO_MODE=false
```

`API_UPSTREAM` is consumed at container startup, so the same web image can move between staging and production without rebuilding against a public API URL.

## Federation variables

Federation is optional. To join configured peers, set these on the API service and keep the rest of the federation section of `env.sample` at its defaults:

```dotenv
FEDERATION_ENABLED=true
FEDERATION_PUBLIC_ORIGIN=https://<web-domain>
FEDERATION_PEERS_JSON=[...entries printed by scripts/federation_peer.py...]
```

The web image routes the peer-facing paths (`/v1/federation/catalog/search`, `/v1/federation/inbound/`, `/v1/public/catalog/`, `/.well-known/clef-node`) to the API, so the public web domain is the federation origin. Restart the API after changing peers.

## Connectors

Start the pilot with `DDEX_ENABLED=false` and `DDEX_LIVE_MESSAGES=false`. Enable test MWL export only after the operating entity accepts the free DDEX Implementation Licence, obtains its DPID, installs the pinned official schemas into the deployment image or a controlled read-only mount, and configures a willing counterparty's DPID and test profile.

MLC credentials belong only in Railway's secret store. Enable `catalog_lookup` and `ownership_evidence_read` only if the account permits them; the results remain observed evidence and never create authority or permission.

## Release sequence

1. Run `make verify` and review the [upgrade notes](../CHANGELOG.md). Preserve a recoverable database backup, the persistent signing/encryption keys, and the previous release configuration before migrating.
2. After release approval, commit the reviewed package and publish its corresponding source. Use the full commit hash for `SOURCE_CODE_REVISION` and an exact matching source URL for `SOURCE_CODE_URL` in the API and workers. Build the console from the same commit.
3. Pause application writes and outbound workers for the maintenance window. Apply `alembic upgrade head` using the candidate image, then run `alembic current` and `alembic check`. This candidate requires `0021_federated_requests`, following the receipt-privacy, prepared-walkthrough, federation and catalog-review migrations. Catalog API clients must send `expected_preview_digest` for resolution, refresh and commit; see QUICKSTART.md. Start the matching API, workers, then web. Keep the API and workers off public networking. Federation remains disabled until the operator configures HTTPS peer origins, verifies their signing keys and reviews publication consent; see [connected catalogs](foundation/CATALOG_FEDERATION.md#configuration).
4. Confirm `/health`, `/v1/node/info`, magic-link delivery, database migration head, database-backed worker heartbeats, and signed node identity. Sign in as a configured operator and open **Operator review → Deployment readiness**; every required check must be green.
5. Run `scripts/verify_release.py --api-url <api-origin> --source-dir <clean-checkout> --expected-revision <revision> --require-clean --require-source-reachable`. The declared source URL must resolve publicly and name the full Git commit hash. The verifier compares the public archive with every tracked file and file mode in that local commit, and includes the archive digest in its JSON report.
6. Complete the browser acceptance flow in `LAUNCH_CHECKLIST.md` with one controlled catalog.
7. Back up PostgreSQL and both persistent signing/encryption keys. Exercise portable logical-dump recovery in an isolated staging project, and rerun the read-only real-pilot verifier there. Exercise Railway volume-snapshot recovery separately as described below.

For the public synthetic demonstration, complete the prepared walkthrough as a fresh guest: inspect both catalog records and managed clients, approve recording and composition uses separately, verify both receipts, reject an altered copy, reload, then start a fresh example. Confirm a blocked or expanded request is explained accurately. This sandbox check uses fictional authority; the real-pilot gate belongs to the separately controlled adopter workflow.

Publish the matching marketing release after the sandbox passes. In `clef-pro-landing`, run `npm run build` to regenerate the partner PDF, test the intake queue and validate claims, links and directory routes. Bind the public evidence links and proof manifest to the released revision whose results they report; working-tree test totals belong in the local review until that revision is published. Keep automated partner delivery disabled until the configured sender and a native, allowlisted form event have passed the controlled delivery demonstration in that repository's `docs/PARTNER_OPERATIONS.md`.

For a recorded gate, place the short-lived operator session in `CLEF_OPERATOR_SESSION_ID` and run `scripts/verify_deployment.py ... --require-readiness`. The value is read from the environment, never a command-line argument or report.

### Backup and rollback preparation

Before the upgrade, inspect **Postgres → Backups**. Record a completed backup's timestamp and confirm a retention schedule appropriate to the operator's recovery targets. Check point-in-time recovery separately; a running database or a mounted volume does not establish either backup capability. Keep key recovery evidence in the operator's private secret-management records.

Railway volume snapshots restore within the same project and environment. Restoring stages a replacement volume, retains the original volume unmounted, and requires deployment to apply the change; newer snapshots can be removed by that restore. Use a disposable environment to rehearse this mechanism. For a recovery exercise in another project, use a portable logical dump and the procedure in [Self-Hosting](SELF_HOSTING.md#exercise-a-postgresql-restore). These platform details were checked on September 5, 2026 against [Railway's backup documentation](https://docs.railway.com/volumes/backups).

Record the known-good deployment for each application service and confirm its recovery action is available before upgrading. Railway's dashboard rollback restores a retained image and its custom variables; image retention limits availability. An older deployment may instead need a source rebuild. See [Railway's rollback guide](https://docs.railway.com/guides/roll-back-bad-deploy). After any rollback, recheck the source declaration and persistent signing/encryption configuration for the restored revision.

Clef requires the database migration head to match its application code. Revision `0021` refuses downgrade once federated requests or peer-represented requester organizations exist. Revision `0020` refuses downgrade once catalog review digests or row review bindings exist. Revision `0019` refuses downgrade once federation publication records exist. Revision `0018` refuses downgrade once a walkthrough or preparation lease has been recorded. Revision `0017` refuses downgrade once disclosure records, retention settings or erasure requests exist. For a fresh, unused database, rehearse any intended downgrade with the candidate migration tooling while API and worker writes are paused. For a used database, retain its schema and use a compatible forward fix or a separately restored database and matching release. Preserve catalog review bindings, publication consent, privacy and walkthrough records during recovery. Earlier migrations have additional evidence-preservation guards documented in [Self-Hosting](SELF_HOSTING.md#machine-credentials-and-audit-retention).

Prefer a compatible forward fix when reverting would lose recorded activity. If database recovery requires an older snapshot, preserve the current volume and account for every receipt, report, and decision recorded after the recovery point before reopening writes.

Do not add external users, enable live DDEX delivery, or describe a settlement as money moved until the corresponding founder, counterparty, and payment-evidence gates are complete.

For the Clef-operated synthetic reference node, set `NODE_DEPLOYMENT_MODE=public_sandbox`, `SANDBOX_GUEST_ACCESS=true`, and `AUTH_SIGNUP_MODE=operator_only`. That profile fails startup if MLC, DDEX, MusicBrainz, OpenRouter, or Slack integrations are enabled, permits only rate-limited anonymous synthetic sessions, and displays a persistent non-production warning with the running source revision. It does not require an email provider because it collects no guest email address; adopter staging and production still fail closed without configured delivery.
