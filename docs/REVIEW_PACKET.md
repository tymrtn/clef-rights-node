# Ten-minute public review packet

## What to inspect

Clef Rights Node lets an organization import identified catalog metadata, declare granular policies, submit evidence of authority, route bounded requests to named reviewers, and issue signed records. The signature protects record integrity; it does not manufacture rights.

Run `make verify-workflow` for the synthetic end-to-end path and `make verify-ddex` for the pinned MWL fixtures. Read the [trust model](foundation/TRUST_MODEL.md), [receipt protocol](foundation/RECEIPT_PROTOCOL.md), [AI policy schema](foundation/AI_POLICY_SCHEMA.md), and [claims boundary](CLAIMS_AND_LIMITS.md).

## Threats already treated explicitly

- metadata being mistaken for authority;
- self-asserted claims becoming discoverable;
- conflicting controlled shares;
- cross-tenant reads or decisions;
- reviewer substitution;
- mutable audit, usage, review, webhook, or exchange evidence;
- replayed credentials, links, files, deliveries, and acknowledgements;
- unsigned lifecycle changes and broken receipt linkage;
- unsafe webhook targets and secret disclosure;
- provisional reserves being described as money moved.

## Known gaps

- No independent security audit has been completed.
- The Railway path is provisional until reproduced in a clean adopter-owned account.
- Live DDEX transport depends on bilateral operating arrangements and is not an alpha capability.
- Production legal, privacy, retention, sanctions, and data-processing policies remain operator responsibilities.
- The public case has not yet demonstrated a real authority, decision, publication, payment, payout, and reconciliation chain.

## Questions for reviewers

1. Which record could still be mistaken for legal authority or third-party acceptance?
2. Can a requester or administrator bypass a named human decision or change history?
3. Which AI policy dimension is missing or ambiguously combined?
4. Can an independent verifier reconstruct the exact decision and lifecycle?
5. Which data should never leave the operator's own systems?
6. Where does the adapter model overstate interoperability?
7. What would prevent your organization from deploying one synthetic node?

Publish ordinary findings as issues. Use a private security advisory for exploits, credentials, personal data, or unredacted catalog evidence.
