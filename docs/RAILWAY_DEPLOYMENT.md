# Railway Deployment

This topology is for a private staging pilot first. Public access remains gated by founder approval, corresponding-source availability, legal review, and the operator checks in `LAUNCH_CHECKLIST.md`.

## Services

Create one Railway project with five services:

1. **Postgres** - Railway-managed PostgreSQL.
2. **api** - repository root directory `/backend`, config path `/backend/railway.json`.
3. **webhook-worker** - root `/backend`, config `/backend/railway.worker.json`, no public domain.
4. **expiry-worker** - root `/backend`, config `/backend/railway.expiry.json`, exactly one replica, no public domain.
5. **web** - root `/frontend`, config `/frontend/railway.json`, public HTTPS domain.

The API config runs `alembic upgrade head` as a pre-deploy gate, then the Docker image repeats the idempotent migration before startup. The workers share the API database but do not run migrations. The web service proxies same-origin `/api` requests to the API over Railway private networking.

## API and worker variables

Set these on the API and both workers unless a line says otherwise:

```dotenv
APP_ENV=staging
DEMO_MODE=false
MOCK_INTEGRATIONS=false
ALLOW_DEV_IDENTITY_HEADERS=false
ALLOW_DEV_MAGIC_LINKS=false
DATABASE_URL=${{Postgres.DATABASE_URL}}
RIGHTS_MAGIC_LINK_SECRET=<secret-manager value>
NODE_ID=urn:clef:rights-node:staging
NODE_DEPLOYMENT_MODE=adopter_staging
NODE_SIGNING_PRIVATE_KEY_B64=<persistent Ed25519 private key>
SOURCE_CODE_REVISION=<immutable commit or tag>
SOURCE_CODE_URL=<HTTPS corresponding-source URL for that revision>
WEBHOOK_ENCRYPTION_KEY_B64=<separate persistent 32-byte key>
NODE_OPERATOR_EMAILS=<operator email>
AUTH_SIGNUP_MODE=operator_only
MAILGUN_API_KEY=<secret-manager value>
MAILGUN_DOMAIN=<verified sending domain>
CONSOLE_BASE_URL=https://<web-domain>
CORS_ALLOW_ORIGINS=https://<web-domain>
STRUCTURED_LOGGING=true
WEBHOOK_ALLOW_PRIVATE_TARGETS=false
```

Only the API needs a public or private service endpoint. The web service should be the sole public application domain. Keep the staging source repository private only while access is restricted to the founder; make the exact corresponding source available to every network user before inviting anyone else.

## Web variables

```dotenv
PORT=8080
API_UPSTREAM=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}
VITE_API_BASE=/api
VITE_DEMO_MODE=false
```

`API_UPSTREAM` is consumed at container startup, so the same web image can move between staging and production without rebuilding against a public API URL.

## Connectors

Start the pilot with `DDEX_ENABLED=false` and `DDEX_LIVE_MESSAGES=false`. Enable test MWL export only after the operating entity accepts the free DDEX Implementation Licence, obtains its DPID, installs the pinned official schemas into the deployment image or a controlled read-only mount, and configures a willing counterparty's DPID and test profile.

MLC credentials belong only in Railway's secret store. Enable `catalog_lookup` and `ownership_evidence_read` only if the account permits them; the results remain observed evidence and never create authority or permission.

## Release sequence

1. Run `make test-local`, `make verify-workflow`, `make verify-ddex`, `make verify-deployment`, and the frontend production build.
2. Commit intentionally and use that immutable revision for both `SOURCE_CODE_REVISION` and `SOURCE_CODE_URL`.
3. Deploy Postgres, API, workers, then web. Keep the API and workers off public networking.
4. Confirm `/health`, `/v1/node/info`, magic-link delivery, database migration head, worker health, and signed node identity.
5. Complete the browser acceptance flow in `LAUNCH_CHECKLIST.md` with one controlled catalog.
6. Back up PostgreSQL and both persistent signing/encryption keys, restore into an isolated staging project, and rerun the read-only real-pilot verifier.

Do not add external users, enable live DDEX delivery, or describe a settlement as money moved until the corresponding founder, counterparty, and payment-evidence gates are complete.

For the Clef-operated synthetic reference node, set `NODE_DEPLOYMENT_MODE=public_sandbox`, `SANDBOX_GUEST_ACCESS=true`, and `AUTH_SIGNUP_MODE=operator_only`. That profile fails startup if MLC, DDEX, MusicBrainz, OpenRouter, or Slack integrations are enabled, permits only rate-limited anonymous synthetic sessions, and displays a persistent non-production warning with the running source revision. It does not require an email provider because it collects no guest email address; adopter staging and production still fail closed without configured delivery.
