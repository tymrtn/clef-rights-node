# Data Privacy

This document describes what a Clef Rights Node publishes, how long it stores private records, what an organization can export, and which stored copies an approved erasure request removes. It covers the console panel under **Operations → Data privacy** and the matching `/v1/organizations/{organization_id}/privacy` API.

An organization owner or administrator uses these controls with a signed-in session. Machine credentials carry integration scopes and stop short of this surface, so publication, retention, export, and erasure stay with a named human actor.

Each deployment assigns the controller and processor roles for itself, and the assignment differs by record and by deployment. An organization self-hosting for its own catalog usually acts as controller over the records it enters. An operator running a node on behalf of other rights holders may act as processor for the catalog and client records those holders supply while acting as controller over its own staff accounts, credentials, and access logs. This node supplies mechanisms and records. The deployment supplies the role assignment, the legal basis, the records of authority, and the procedure that covers copies held outside the node.

## Four distinct operations

| Operation | What it changes | Where it lives |
| --- | --- | --- |
| Audit history and correction | Adds a new signed record that references the prior one. History stays append-only. | `docs/foundation/RECEIPT_PROTOCOL.md#corrections` |
| Credential revocation | Ends a machine credential's ability to act. Past actions keep their credential attribution. | **Operations → Machine credentials** |
| Private-copy erasure | Removes the stored receipt payload and its commitment opening, or a managed-client contact email. | **Operations → Data privacy → Erasure requests** |
| Public withdrawal | Stops this node from serving a receipt's public summary. | **Operations → Data privacy → Public summary for one receipt** |

Each one answers a different question. Choose the operation that matches the obligation you are meeting, and record which one you performed.

## Publication controls

`publishPublicReceipts` governs receipts issued after the setting is saved. Both the requester organization and the authority organization enable publication before issue for a public summary to exist. The console asks for an explicit confirmation the first time an organization turns publication on.

The private and public payload split is decided before signing, and the published field set is fixed at issue. A later settings change governs later receipts; historic records keep the disclosure that applied when they were signed. Enabling publication today leaves earlier receipts in authenticated storage.

A public summary contains exactly these fields:

- `schemaVersion`
- `receiptId` — an opaque public identifier distinct from the private receipt ID
- `node`
- `issuedAt`
- `statusAtIssue`
- `kind`
- `privateEvidenceCommitment`

Work identifiers, party identifiers, agreement terms, prices, comments, names, email addresses, and free text stay in the private record. Grant, lifecycle, and settlement originals stay behind authentication.

`GET /v1/public/receipts/{public_id}` returns that signed minimal summary, and its `/status` endpoint returns the current permission state. The summary is a statement about the moment of issue. A reader who needs the current state reads the status endpoint. `currentStatus` accounts for an elapsed term even before the expiry worker records it; `recordedPermissionStatus` preserves the stored state. Settlement summaries also return `reconciliationCurrent` and `settlementAssertion`, calculated from retained ledger records. A reversal makes the old assertion provisional even after private-copy erasure; its signed `statusAtIssue` stays unchanged.

Public summaries occupy their own hash chain with its own sequence numbers, separate from the private transparency sequence. A public log position therefore omits the private sequence number of the same receipt, and it does not reveal how many private records sit between two published ones.

Both chains still advance in issue order. A reader who compares public positions against issue timestamps, or against times they already know from another source, can infer the relative order in which the published receipts were issued and narrow when an unpublished receipt was issued between them. Treat the separation as removal of the private sequence number, and assume ordering and timing correlation remains available to anyone reading the public chain.

### Private evidence commitment

`privateEvidenceCommitment` is a domain-separated SHA-256 over a random 32-byte private nonce and the exact signed private receipt. A party holding the opening — the nonce and the algorithm identifier, available from `GET /v1/receipts/{receipt_id}/disclosure` — can prove that a specific private receipt produced that public summary.

A reader without the opening cannot invert the digest and cannot test a guessed receipt against it, because the test needs the nonce. The digest is still a stable, unique, published value, so it works as a correlatable identifier for that public summary: a reader can recognise the same commitment wherever it appears and count how many summaries a node published.

Erasing a stored private copy removes its commitment opening along with the payload, which ends the node's ability to reproduce that proof.

### Withdrawal

Either party may call `POST /v1/organizations/{organization_id}/privacy/receipts/{receipt_id}/withdraw-public`. The node stops serving that public summary. Copies already distributed stay with whoever holds them, so treat withdrawal as a change to what this node offers, and handle downstream copies through your own notice process.

## Retention

`receiptRetentionDays` is an adopter-defined minimum storage duration between 1 and 36500 days. Where the two parties to a receipt have selected different durations, the longest selected duration governs.

The minimum is evaluated again when an erasure runs, against both the duration fixed at issue and the durations saved now. Raising the value postpones a pending erasure. Lowering it leaves the minimum fixed at issue in force, so a shortened setting cannot release a copy early.

An empty value means this organization reviews each erasure request by hand and records its own decision date. Manual review keeps the same approval requirement: every required party still approves before execution.

These settings are storage controls. They make no representation about GDPR, CCPA, or any other statutory obligation, and satisfying a statutory request remains the adopter's assessment with its own counsel.

## Legal hold

`legalHold` blocks the receipt-copy and managed-client contact-email erasures implemented here. Operators apply matching holds to other storage, exports and backups through their own procedures. The node checks the hold when it builds an erasure preview and checks it again at the moment of execution, so a hold applied between preview and execution still blocks the deletion. Clear the hold through the same panel when the retaining obligation ends.

## Export

`GET /v1/organizations/{organization_id}/privacy/export?resource={resource}&limit=100&cursor=...` returns one page of records for a single resource:

`clients`, `catalog`, `policies`, `claims`, `permissions`, `receipts`, `members`, `audit`

Each page carries `schemaVersion`, `organizationId`, `resource`, `records`, `nextCursor`, and `exportedAt`. Follow `nextCursor` until it returns `null` for the complete resource. The console shows a page, downloads it as JSON, and loads the next page on request.

Two resources need their exact scope stated:

- `policies` returns the current policy record for each policy key from `rights_contracts`, at the version stored right now. Superseded versions live in `rights_history` and appear in no page of this export.
- `audit` omits the `privacy.export.created` events this node records for each export page. Including them could keep adding records while the export is being paginated. Those events stay in the audit chain and remain readable in the operator audit view; read them there when you need the export history itself.

### Operator archive export

Historical and operational tables sit outside the export API. An operator who needs them performs a direct database extract as a separate, named operation:

`rights_history`, `rn_authority_conflicts`, `rn_catalog_import_batches`, `rn_catalog_import_rows`, `rn_catalog_assignments`, `rn_permission_review_assignments`, `rn_permission_usage_reports`, `rn_permission_compliance_reviews`, `rn_receipt_disclosures`, `rn_privacy_erasure_requests`, `rn_ddex_exchanges`, `rn_ddex_acknowledgements`, `rn_webhook_events`, `rn_webhook_deliveries`, `rn_webhook_attempts`, `rn_settlements`, `rn_settlement_beneficiaries`, `rn_settlement_entries`, `rn_settlement_reconciliations`

That extract carries no organization scoping of its own, so the operator applies the scope, records who ran it, and handles the output under the same procedure as a downloaded export.

Exports are scoped to the requesting organization and contain private records, including client contact details and audit history. The downloaded file falls under the organization's own retention and handling procedure from the moment it lands on a workstation. The export API selects no signing keys, session tokens, API credential secrets or webhook endpoint secrets. An operator database extract needs its own field selection and secret exclusions. Free-text evidence and notes can still contain values a user entered; review exports before sharing.

## Erasure requests

An erasure request covers one of two scopes:

- `receipt_copy` — the stored receipt payload for one receipt, plus its private commitment opening
- `client_contact_email` — the contact email stored for one managed client

The lifecycle:

1. **Open.** `POST /v1/organizations/{organization_id}/privacy/requests` with `{kind, resource_id}` creates the request and lists the organizations whose approval is required.
2. **Preview.** `GET .../requests/{id}/preview` returns `willErase`, `retained`, `blockedBy`, `canExecute`, `retainUntil`, and `legalHold`. Read `retained` before you answer anyone about scope: it names the linked records this node keeps.
3. **Approve.** `POST .../requests/{id}/approve` records one explicit administrator approval for the calling organization. Repeat approvals from the same organization collapse into that one approval, and approval alone performs no deletion.
4. **Execute.** `POST .../requests/{id}/execute` with `{confirm_request_id}` runs the erasure once every required party has approved, the minimum retention has elapsed, and no hold applies. The console shows the preview and asks the administrator to type or paste the request ID before the final click. Either result stays on screen beside a refreshed preview: a completed erasure keeps its `erased` and `retained` lists visible, and a refusal keeps the node's reason visible next to the state the node reports now.

The response reports `erased` and `retained`. Signatures on originals exported before the erasure keep verifying against the node's public key, and the historic payload hash stays in the audit chain, so the transparency record of what was issued survives the deletion of the stored copy.

This is copy erasure with a stated scope: the stored receipt payload and its commitment opening, or one managed-client contact email. It makes no claim about a whole subject's personal data, and reporting it as one would misstate what happened, because the locations below hold their own copies and the records listed further down survive by design.

## Residual locations

Personal data associated with a work, a client, or a permission also lives in records this API leaves in place:

- Contracts and authority documents held by the adopter
- Catalog rows, client references, and import batches
- Permission history, publication reports, and compliance reviews
- Identity records for members and requester contacts
- Financial and settlement entries, including external transaction references
- DDEX exchange payloads and recorded acknowledgements
- Webhook events, attempts, and payloads already delivered to a receiver
- Prior exports, operator reports, and encrypted backups
- Database write-ahead logs and archived segments, which hold the pre-deletion row image until they age out
- Table and index pages freed by the delete, which keep the old bytes until a later write overwrites them or the table is rewritten
- Read replicas, standbys, and logical replication targets, each of which received the row and applies the deletion on its own schedule

The last three are properties of the database rather than records an administrator can address one at a time. A deletion is durable there once the write-ahead logs covering it have aged out, every replica has applied it, and the freed pages have been overwritten or the table rewritten. State that timeline when you report a completed erasure.

The console lists these locations inline under **Operations → Data privacy**, so an administrator reading the panel sees the follow-up without leaving the node.

Each location needs its own inventory, its own authority to act, and its own operator handling. Two of them sit outside this node entirely: a webhook payload accepted by a receiver is governed by the agreement with that receiver, and an export that has left the node is governed by wherever it was stored.

A broad personal-data request stays open until every residual location has been addressed. Record the residual locations you reviewed and the disposition of each, then close the request against that record.

### Backups and restores

Encrypted backups keep whatever they captured. Two practices keep a completed erasure durable:

1. **Expiry.** Let backups age out on their declared schedule, and record that schedule so a requester learns when the last copy expires.
2. **Restore suppression.** Keep the identifiers of completed erasure requests, and replay those requests against any database restored from a backup taken before the erasure ran. Do this as part of the restore runbook, before the restored node accepts traffic.

`scripts/verify_postgres_recovery.py` exercises the restore path itself; the erasure replay is the operator step that follows it.

### Records this node keeps after an erasure

Erasure leaves a minimum record so that security investigations and the transparency chain stay intact:

- The erasure request, its approvals, its actor, and its completion time
- The historic payload hash in the audit chain
- Audit events describing the deletion
- Incident and access logs under the operator's own security retention

Name these records when you report a completed erasure. They are the evidence that the erasure happened.

## Audio

This node records the scope of an audio use and the commitments the parties made about it. Audio files stay in the operator's existing delivery infrastructure, and watermarking, metering, and storage are performed by that infrastructure. The console offers no audio upload, so a deletion request covering audio is executed where the audio actually lives, and the node's records describe what was permitted.

## Related documents

- [Receipt protocol](foundation/RECEIPT_PROTOCOL.md) — receipt contents, verification, access, and the public disclosure surface
- [Self-hosting](SELF_HOSTING.md) — retention policy, backups, and the PostgreSQL restore exercise
- [Trust model](foundation/TRUST_MODEL.md) — what a receipt proves
- [Claims and limits](CLAIMS_AND_LIMITS.md) — the current stage of this implementation

## Upgrade and operate

1. Back up the database and rehearse restore in an isolated environment. Keep the backup protected under its declared retention schedule.
2. From the backend environment, run `alembic upgrade head`; this release adds `0017_receipt_privacy`. Deploy API and console together. Existing signed payloads stay byte-for-byte intact; legacy receipts gain no public summaries.
3. As an organization owner or administrator, open **Operations → Data privacy**. Choose the minimum retention and review any applicable holds before issuing new receipts. Publication starts off and requires both organizations to opt in before signing.
4. Run a synthetic two-party grant, inspect its public summary anonymously, export the private copy as a party, and check that an unrelated organization receives no private data.
5. Assign an operator for broader personal-data requests, residual storage, export handling and backup restores. Keep those requests open until the separately scoped tasks are complete.

The export API uses keyset pagination, not a frozen database snapshot. For a consistent full archive during ongoing writes, an operator must use a scoped database snapshot.
