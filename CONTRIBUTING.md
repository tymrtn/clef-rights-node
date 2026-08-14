# Contributing

Contributions should strengthen artist authority, factual precision, portability, and independent verification.

## Required checks

```bash
cd backend && PYTHONPATH=. ../.venv/bin/pytest -q
cd frontend && npm ci && npm run build
```

Schema, receipt, permission-state, and adapter-capability changes require regression tests and migration review. Never commit credentials, private keys, catalog data without permission, or synthetic production identities.

Do not describe imported metadata as verified authority or a provisional reserve as permission.
