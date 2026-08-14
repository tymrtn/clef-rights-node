# Provisional adopter-owned Railway deployment

This is a reproducible service map, not a published one-click template. Railway templates are created from a project or in Railway's template composer, where service roots, variables, networking, and reference variables are captured. Publish a template only after a fresh adopter-owned account completes this runbook without Clef-held secrets. See Railway's current [template creation](https://docs.railway.com/templates/create), [monorepo](https://docs.railway.com/deployments/monorepo), and [config-as-code](https://docs.railway.com/config-as-code) documentation.

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
3. Generate staging secrets locally with `scripts/bootstrap_env.py`; enter values directly in Railway's secret store. Do not commit or send the generated file.
4. Apply the API and worker variables from `docs/RAILWAY_DEPLOYMENT.md`, using `${{Postgres.DATABASE_URL}}` and private service references where documented.
5. Give only `web` a public domain. Set `API_UPSTREAM` to the API's Railway private domain and port.
6. Set `NODE_DEPLOYMENT_MODE=adopter_staging` and `AUTH_SIGNUP_MODE=operator_only`; keep `MLC_ENABLED=false`, `DDEX_ENABLED=false`, `DDEX_LIVE_MESSAGES=false`, `MUSICBRAINZ_ENABLED=false`, and sandbox data synthetic for the first boot. A public reference deployment instead uses `NODE_DEPLOYMENT_MODE=public_sandbox` with `SANDBOX_GUEST_ACCESS=true`, which rejects live connectors, creates only anonymous short-lived sessions, and renders a persistent warning.
7. Deploy Postgres, API, webhook worker, expiry worker, then web. Confirm that exactly one expiry worker exists.
8. Run `scripts/verify_deployment.py --api-url <private-test-origin> --web-url https://<web-domain> --expected-revision <revision> --expected-mode adopter_staging --skip-compose` from an authorized network path.
9. Complete the browser acceptance path and a backup/restore exercise before adding a real catalog.

## Template publication gate

The candidate template must generate or request every secret, use reference variables for service connections, expose only the web service, pin corresponding public source, preserve AGPL disclosure, and make optional adapters default to disabled. A second person must deploy it in a clean account, record elapsed time and failures, and remove all test resources before Clef publishes a Deploy button.
