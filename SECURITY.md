# Security Policy

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/tymrtn/clef-rights-node/security/advisories/new). Do not open public issues containing exploits, secrets, personal data, or unredacted catalog evidence.

## Production invariants

- Demo identity headers and mock integrations are disabled.
- Persistent signing and session keys are required.
- Postgres or another durable shared database is required.
- External capabilities fail closed unless explicitly configured and authorized.
- Receipt private keys and connector credentials are never returned by the API.
- Authority evidence and personal data must follow deployment-specific retention controls.
- Every staging and production node identifies its exact deployed revision and public corresponding source through the API and console.
