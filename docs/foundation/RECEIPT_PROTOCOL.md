# Receipt Protocol

## Receipt contents

- Schema and node identifiers
- Permission request, requester actor, and intended-use snapshot
- For AI uses: operation, source assets, model environment, duration, lyric volume, retention, and policy-evaluation reasons
- Authority claim and verification snapshot
- Rights-policy version and hash
- Decision, actor, timestamp, scope, and expiry
- Exact attribution text, backlink, placement, metadata, and publication-reporting obligations
- Provenance references supplied by the requester
- Canonical payload hash
- Ed25519 signature and key identifier
- Transparency sequence, previous hash, and entry hash

## Verification

A verifier must independently canonicalize the payload, recompute its hash, verify the Ed25519 signature, and verify the transparency entry hash. Online node availability is not required when the public key and receipt are available.

## Corrections

Receipts are immutable. Corrections, revocations, and disputes create new signed records referencing the prior receipt.

Grant receipts use `clef.permission-receipt.v1`. Post-decision status records use `clef.permission-status-receipt.v1` and contain the event actor, reason, previous and resulting status, original grant identifier, prior receipt identifier and payload hash, plus any replacement grant identifier and payload hash. Both record types occupy the same append-only transparency sequence.

The grant's `permission.licenseObligations` object uses `clef.license-obligations.v1`. It records exact credit text, a required HTTPS backlink, permitted credit placements, exact metadata fields, and publication-reporting timing. If an AI policy requires attribution, the node refuses approval until the authority supplies exact credit text and at least one placement.

Publication reports and compliance reviews are append-only administrative evidence linked to the permission request. A report is a `requester_reported` assertion. Exact-value and deadline checks have `comparison_only` effect because they compare the requester's declaration with the signed grant; they do not inspect the external platform. A compliance review is an `authority_reviewed` assertion with `effectOnPermission: none`. Neither record is a grant receipt or lifecycle receipt. Enforcement requires a separately authorized dispute, revocation, or correction.

Settlement reconciliations use `clef.settlement-reconciliation-receipt.v1`. The signed payload identifies the grant, immutable terms, complete beneficiary split, exact minor-unit entries, hashes of entry evidence, deterministic totals, ledger digest, reconciliation actor, and `provisional` or `paid` assertion. A later financial entry does not alter that historical receipt; it makes the receipt stale for current-state claims until a new reconciliation signs the new ledger digest. Settlement receipts occupy the same transparency sequence as permission and lifecycle receipts.

Either permission party may create a dispute record. Revocation and correction require either a decision-capable member of the verified authority organization or an organization-bound credential with lifecycle scope. A correction must reference a distinct active grant for the same work, authority organization, and right. The node expiry process creates one idempotent signed expiry record after the declared term ends and records the term-derived effective timestamp.

Human actors are identified by durable user IDs. Machine actors are identified by organization-bound API credential IDs and names; their bearer secrets never enter a receipt. A machine credential may act only when its organization is the appropriate permission party and it carries the required request, assignment, decision, reporting, compliance-review, lifecycle, settlement, or reconciliation scope. A named human assignment blocks machine decisions and reviews until an authorized authority member clears it. The node does not create synthetic users for integrations.
