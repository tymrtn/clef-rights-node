# Adopter-owned Railway deployment candidate

This is the reproducible service map for a template candidate, not a published one-click claim. [`template-spec.json`](template-spec.json) is the reviewable composer manifest; Railway templates are still created from a project or in Railway's template composer. Publish a Deploy button only after a fresh adopter-owned account completes this runbook without Clef-held secrets. See Railway's current [template creation](https://docs.railway.com/templates/create), [monorepo](https://docs.railway.com/deployments/monorepo), and [config-as-code](https://docs.railway.com/config-as-code) documentation.

## Project graph

| Service | Source root | Config path | Public network | Replicas |
| --- | --- | --- | --- | --- |
| Postgres | Railway managed | Managed service | No | Managed |
| api | `/backend` | `/backend/railway.json` | No; private network only | 1 |
| webhook-worker | `/backend` | `/backend/railway.worker.json` | No | 1 or more after load testing |
| expiry-worker | `/backend` | `/backend/railway.expiry.json` | No | Exactly 1 |
| web | `/frontend` | `/frontend/railway.json` | HTTPS | 1 or more |

Railway requires the config path to be absolute from the repository root even when a service root directory is set. The checked-in config files control build and deploy settings; the dashboard still owns service roots, domains, variables, and scaling.

## Operator sequence

1. Create a new Railway project in the adopting organization's account and add managed Postgres.
2. Add four empty services, connect each to the adopter's fork or pinned public revision, and set the roots and config paths above.
3. In the template composer, use the exact expressions in `template-spec.json` to generate the magic-link, signing and webhook-encryption secrets inside the adopter's project. The adopter enters and seals its own SMTP identity and credentials; no Clef operator handles those values. For the manual Docker path, `scripts/bootstrap_env.py` remains the local equivalent.
4. Bind `SOURCE_CODE_REVISION` and `SOURCE_CODE_URL` to the exact public commit used by the candidate before the reproduction begins. Derive `NODE_ID` from `${{RAILWAY_PROJECT_ID}}`, and apply the remaining API and worker variables from `docs/RAILWAY_DEPLOYMENT.md` using private service references where documented.
5. Give only `web` a public domain. Set `API_UPSTREAM` to the API's Railway private domain and port.
6. Set `NODE_DEPLOYMENT_MODE=adopter_staging` and `AUTH_SIGNUP_MODE=operator_only`; keep `MLC_ENABLED=false`, `DDEX_ENABLED=false`, `DDEX_LIVE_MESSAGES=false`, `MUSICBRAINZ_ENABLED=false`, and sandbox data synthetic for the first boot. A public reference deployment instead uses `NODE_DEPLOYMENT_MODE=public_sandbox` with `SANDBOX_GUEST_ACCESS=true`, which rejects live connectors, creates only anonymous short-lived sessions, and renders a persistent warning.
7. Deploy Postgres, API, webhook worker, expiry worker, then web. Confirm that exactly one expiry worker exists.
8. Deliver and consume one operator magic link. Put the resulting short-lived session in `CLEF_OPERATOR_SESSION_ID`, then run `scripts/verify_deployment.py --api-url <private-test-origin> --web-url https://<web-domain> --expected-revision <revision> --expected-mode adopter_staging --skip-compose --require-readiness` from an authorized network path.
9. Confirm the operator-only readiness panel reports current migrations, durable signing, portable email, source identity, and fresh database heartbeats from both workers.
10. Complete the browser acceptance path and a backup/restore exercise before adding a real catalog.
11. Copy `adopter-reproduction.example.json` into a private evidence workspace, fill it from the second operator's actual run, and execute `scripts/verify_adopter_reproduction.py --report <private-report>`. Never commit project identifiers or delivery evidence unless the adopter approves publication.

## Template publication gate

The candidate template must generate or request every secret, derive node identity from the adopter-owned project, use reference variables for service connections, expose only the web service, pin corresponding public source, preserve AGPL disclosure, and make optional adapters default to disabled. A second person must deploy it in a clean account, record elapsed time and failures, pass operator readiness, and remove all test resources before Clef publishes a Deploy button.

Railway's template composer, rather than this repository, is the final platform source of truth for the deployable template. Before creating it, copy the generated, required, derived and fixed variables from `template-spec.json`; after creation, export or inspect the composer settings against that file. Do not replace generated adopter secrets with values from the Clef sandbox or a Clef operator's machine.
