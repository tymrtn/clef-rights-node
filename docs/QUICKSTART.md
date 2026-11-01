# 15-minute synthetic walkthrough

This path evaluates catalog administration, scoped requests and signed receipts using fictional records. Real deployments use the organization's own mandates, reviewers and integration credentials.

## Prepared public-sandbox walkthrough

For a local review with dependencies installed, run:

```bash
.venv/bin/python scripts/run_local_preview.py
```

Open `http://127.0.0.1:16482`. The launcher starts the real API and console on loopback, migrates an isolated SQLite database, and retains its signing keys and records in `~/.cache/clef/local-preview`. It uses an empty environment file and disables email and provider integrations. Your repository `.env` and production database stay separate from this evaluation.

Ctrl-C stops both servers. Run the same command to resume; `--state-dir /path/to/private-directory` selects another example database. `--web-port` and `--api-port` select unused local ports. `--check` runs the database migration and schema check without starting servers. If startup fails, inspect `api.log`, `web.log` or `migration.log` in the state directory. Restore the matching signing keys when restoring a saved preview database.

Install dependencies first if needed: `python3 -m venv .venv`, `.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock`, and `npm --prefix frontend ci`.

In a node explicitly configured with `NODE_DEPLOYMENT_MODE=public_sandbox`, `SANDBOX_GUEST_ACCESS=true` and `VITE_DEMO_MODE=false`, choose **Explore the example catalog**. Clef prepares a separate fictional label, publisher and requester for your anonymous session.

1. Follow **Paper Skies** from its illustrative recording identifier to its composition reference. The pairing comes from the example catalog.
2. Compare the label's stem policy with the publisher's composition policy, including duration, model access and retention limits.
3. Approve the recording and composition requests separately. Try the broader training, worldwide or five-minute requests to exercise the API's scope checks.
4. Verify each signed receipt, test an altered copy and download the original JSON. Private receipt access uses the authenticated session.

**Inspect catalog record**, **Open the full policy** and **Explore the full console** lead to the underlying records. **Return to walkthrough** resumes the same example. Reloading preserves completed decisions and policy changes; interrupted preparation resumes the existing records. **Start a fresh example** creates a new anonymous session, leaving the previous example's audit records intact.

All names, identifiers, mandates and pairings are fictional. The guest plays all reviewers. Stems and lyrics describe permitted inputs; asset delivery and watermarking require a separately connected production service. This preparation endpoint is available only to anonymous public-sandbox guests; adopter environments return 404.

See [self-hosting](SELF_HOSTING.md) for the public-sandbox configuration and signing requirements. Apply `alembic upgrade head` before running this version; the current head is `0020_catalog_review_basis`, following the walkthrough and publication-consent migrations.

## Search a label and publisher on separate nodes

```bash
.venv/bin/python scripts/run_federation_preview.py
```

Open `http://127.0.0.1:16484`, choose **Explore the example catalog**, then **Search connected catalogs**. Search **Paper Skies** or **ZZDEM2600001** to find the fictional recording at the label and its composition at the publisher. Each result identifies its source, public artist conditions and statement expiry. Expand **Inspect the source statements** to download the signed responses.

The launcher runs separate databases, keys, APIs and consoles on loopback. Rerunning preserves existing catalog edits and publication choices. `--verify --state-dir /tmp/clef-fresh-federation-proof` exercises withdrawal, stale policy and a failed peer against fresh synthetic state, then stops the servers. See the [protocol, publication controls and operating limits](foundation/CATALOG_FEDERATION.md).

## Build an organization from scratch

The manual path below exercises the same administration console with development sign-in links.

## 1. Start the node

```bash
cp env.sample .env
docker compose up --build -d --wait
```

Open `http://localhost:6482`. The API health endpoint is `http://localhost:9247/health`.

## 2. Create the administrative path

1. Sign in with a fictional label email and use the setup wizard's conservative AI default.
2. Create one fictional managed client, download the console's CSV template, add fictional catalog rows and preview the CSV.
3. Publish a policy for one durable synthetic work key.
4. Submit an authority claim with a fictional contract reference and digest.
5. Sign in as the configured node operator and review the evidence as synthetic.
6. Sign in with a separate requester organization and request a bounded use.
7. Assign a named rights manager, decide the request, and inspect the signed receipt.

### Recover an import after a catalog change

Under **Catalog**, reopen the original import and choose **Refresh preview**. Clef rechecks the stored CSV against current recordings, compositions and managed clients. Review any conflicts again and confirm the refreshed import. Earlier conflict decisions remain in the audit history. Changed file contents require a revised CSV upload; adding a missing client needs only a preview refresh.

Each resolution, refresh and commit carries the `previewDigest` returned by the selected preview as `expected_preview_digest`. A resolution also returns the updated digest; use that value for the next action. A stale digest receives 409 and requires reopening the current preview. Retry an interrupted commit with the same digest and confirmation: the completed batch is returned once. Pre-upgrade pending imports require a refresh; committed imports retain their records and history.

### Withdraw an authority assertion

Under **Authority**, an owner, administrator or rights manager chooses **Review withdrawal**, checks the pending-request and issued-grant counts, records a reason and confirms. The claim becomes revoked, new permissions and pending approvals stop, and its connected-catalog listing disappears from fresh searches. Issued receipts retain their signed history; review each existing grant in the **Permission ledger** for any separate revocation, dispute or correction its terms require.

The API uses `GET /v1/organizations/{org_id}/authority-claims/{claim_id}/withdrawal-preview`, followed by `POST .../{claim_id}/withdraw` with `expected_digest`, `reason` and `confirm_withdrawal: true`. An interrupted response can be retried with the same payload. A changed authority record requires a new preview. Withdrawal uses a human organization session.

## 3. Run the machine-verifiable path

```bash
make test-local
make verify-workflow
make verify-ddex
make verify-deployment
cd frontend && npm run build
```

`verify-workflow` creates its own temporary database and reports each gate. The DDEX verifier checks bundled examples against pinned official schemas when installed; it does not send a message.

## 4. Stop safely

```bash
docker compose down
```

Use `docker compose down -v` only when you intend to delete the local evaluation database.

Next: read [Claims and limits](CLAIMS_AND_LIMITS.md) before showing the node to another organization.
