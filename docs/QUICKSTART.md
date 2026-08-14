# 15-minute synthetic walkthrough

This path evaluates the software without MLC, DDEX, catalog-owner, or payment credentials. Its records are synthetic and establish no authority.

## 1. Start the node

```bash
cp env.demo.sample .env
docker compose up --build -d --wait
```

Open `http://localhost:6482`. The API health endpoint is `http://localhost:9247/health`.

## 2. Create the administrative path

1. Sign in with a fictional label email and use the setup wizard's conservative AI default.
2. Create one fictional managed client and preview `fixtures/sample_catalog.json` or the console CSV template.
3. Publish a policy for one durable synthetic work key.
4. Submit an authority claim with a fictional contract reference and digest.
5. Sign in as the configured node operator and review the evidence as synthetic.
6. Sign in with a separate requester organization and request a bounded use.
7. Assign a named rights manager, decide the request, and inspect the signed receipt.

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
