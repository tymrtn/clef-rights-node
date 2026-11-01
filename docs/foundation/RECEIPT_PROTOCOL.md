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

## Access and public transparency

`GET /v1/receipts/{receipt_id}` requires an authenticated member of the requester or authority organization, or an organization-bound API credential from either party. Grant and lifecycle downloads require `permissions:read`; settlement reconciliation downloads require `settlements:read`. Operator status alone grants no receipt access. Successful downloads use `Cache-Control: private, no-store`.

The console retrieves receipts with the active session and offers an authenticated JSON download. A party can give a downloaded receipt to a verifier. `POST /v1/receipts/verify` remains public and verifies the supplied document without fetching private records.

`GET /v1/transparency/head` returns only `sequence` and `entryHash`. `GET /v1/transparency/entries` returns `sequence`, `payloadHash`, `previousEntryHash`, and `entryHash`. A verifier can match a supplied receipt against this hash chain. These endpoints disclose log size and ordering; receipt identifiers, permission identifiers, event types, timestamps and signed contents stay in authenticated records.

An upgrade preserves existing signatures and stored receipts. Consumers of the previous public receipt endpoint must add party credentials; consumers of the public log must use hashes instead of receipt identifiers. Deploy the API and console changes together. Operators should review any historical public exposure and invalidate any previously cached receipt responses on their own infrastructure.

## Opt-in public summaries

An organization owner or administrator sets `publishPublicReceipts` for the organization through `PUT /v1/organizations/{organization_id}/privacy`. Both the requester organization and the authority organization enable publication before issue for a public summary to exist. The split between the private and public payload is decided before signing, and the published field set is fixed at that moment. Later settings changes govern later receipts.

`GET /v1/public/receipts/{public_receipt_id}` returns a separately signed minimal summary containing `schemaVersion`, `receiptId` as an opaque public identifier, `node`, `issuedAt`, `statusAtIssue`, `kind`, and `privateEvidenceCommitment`. Its `/status` endpoint returns the current permission state, so a public reader gets the issue-time statement from the summary and the recorded permission state and term expiry from the status endpoint. Settlement summaries also expose `reconciliationCurrent` and `settlementAssertion` from the retained ledger; a payment reversal changes freshness without rewriting the signed issue-time statement. Work identifiers, party identifiers, agreements, prices, comments, names, email addresses, and free text stay in the authenticated record, and grant, lifecycle, and settlement originals remain behind party credentials.

Public summaries form their own hash chain, independent of the private transparency sequence described above. The public chain discloses public-summary count and ordering; the private sequence keeps its own positions.

`privateEvidenceCommitment` is a domain-separated SHA-256 over a random private nonce and the exact signed private receipt. `GET /v1/receipts/{receipt_id}/disclosure` returns `publicReceiptId`, `publicUrl`, `published`, `withdrawn`, `privateCopyErased`, `retainUntil`, and the `commitmentOpening` with its nonce and algorithm to the same authenticated parties who may read the receipt. A party holding the opening can prove that a specific private receipt produced a given public summary; the secret nonce prevents testing guessed private contents against the commitment. The published value remains correlatable and should be treated as pseudonymous, not anonymous.

`POST /v1/receipts/commitment/verify` checks both signatures, the matching signing keys, the disclosure manifest bound into the private signature, and the commitment opening. Signature verification establishes integrity under the supplied key; a verifier establishes trust in that node key separately. The commitment binds the evidence captured in the private receipt, not the contents of external URLs unless their digests were captured in that evidence.

Either party may call `POST /v1/organizations/{organization_id}/privacy/receipts/{receipt_id}/withdraw-public`. This node stops serving that public summary, and copies already distributed stay with whoever holds them.

## Erasure of a stored private copy

An approved erasure request removes the stored receipt payload and its commitment opening from this node. Execution requires an explicit administrator approval from every required party, the elapsed minimum retention both parties selected, and the absence of a legal hold at the moment of execution.

Three properties survive that deletion. An original exported before the erasure still verifies against the node's public key, because verification uses the document and the key rather than node storage. The historic payload hash keeps its place in the transparency chain, so the record of what was issued and in what order stays intact. The erasure request, its approvals, its actor, and its completion time are retained as audit evidence.

The node reports the linked records it keeps alongside the records it erased. Copies held in contracts, catalog rows, permission history, identity records, financial entries, import batches, DDEX exchanges, delivered webhook payloads, prior exports, and backups are outside this operation and follow the operator procedure in [Data privacy](../DATA_PRIVACY.md).

## Corrections

Receipts are immutable. Corrections, revocations, and disputes create new signed records referencing the prior receipt.

Grant receipts use `clef.permission-receipt.v1`. Post-decision status records use `clef.permission-status-receipt.v1` and contain the event actor, reason, previous and resulting status, original grant identifier, prior receipt identifier and payload hash, plus any replacement grant identifier and payload hash. Both record types occupy the same append-only transparency sequence.

The grant's `permission.licenseObligations` object uses `clef.license-obligations.v1`. It records exact credit text, a required HTTPS backlink, permitted credit placements, exact metadata fields, and publication-reporting timing. If an AI policy requires attribution, the node refuses approval until the authority supplies exact credit text and at least one placement.

Publication reports and compliance reviews are append-only administrative evidence linked to the permission request. A report is a `requester_reported` assertion. Exact-value and deadline checks have `comparison_only` effect because they compare the requester's declaration with the signed grant; they do not inspect the external platform. A compliance review is an `authority_reviewed` assertion with `effectOnPermission: none`. Neither record is a grant receipt or lifecycle receipt. Enforcement requires a separately authorized dispute, revocation, or correction.

Settlement reconciliations use `clef.settlement-reconciliation-receipt.v1`. The signed payload identifies the grant, immutable terms, complete beneficiary split, exact minor-unit entries, hashes of entry evidence, deterministic totals, ledger digest, reconciliation actor, and `provisional` or `paid` assertion. A later financial entry does not alter that historical receipt; it makes the receipt stale for current-state claims until a new reconciliation signs the new ledger digest. Settlement receipts occupy the same transparency sequence as permission and lifecycle receipts.

Either permission party may create a dispute record. Revocation and correction require either a decision-capable member of the verified authority organization or an organization-bound credential with lifecycle scope. A correction must reference a distinct active grant for the same work, authority organization, and right. The node expiry process creates one idempotent signed expiry record after the declared term ends and records the term-derived effective timestamp.

Human actors are identified by durable user IDs. Machine actors are identified by organization-bound API credential IDs and names; their bearer secrets never enter a receipt. A machine credential may act only when its organization is the appropriate permission party and it carries the required request, assignment, decision, reporting, compliance-review, lifecycle, settlement, or reconciliation scope. A named human assignment blocks machine decisions and reviews until an authorized authority member clears it. The node does not create synthetic users for integrations.
