# Trust Model

## Assertions

- `observed`: imported from an external data source
- `self_asserted`: claimed by a user or organization
- `verified`: supported by reviewed authority evidence
- `permissioned`: an authorized party granted a specific request
- `provisional`: funds or terms are offered without permission
- `disputed`: one or more assertions conflict
- `revoked`: a prior assertion or grant is no longer active
- `expired`: a grant's declared term has ended and the node recorded that transition
- `paid`: the current immutable settlement ledger was reconciled with a positive obligation, exact external payment, and exact beneficiary payouts

Every response and receipt must preserve the assertion type, source, actor, evidence references, timestamp, and applicable scope.

A settlement term or reserve remains `provisional`. A later financial entry makes an older reconciliation stale; `paid` applies only while the reconciliation digest matches the current immutable terms, beneficiary split, and entries. Clef records external financial evidence and does not imply custody or transfer of funds.

## Authority

Authority is scoped by right type, work or recording, territory, term, and delegation. Email control alone is never sufficient authority evidence.

## Node trust

Each node signs its own receipts. Consumers decide which node keys and authority-verification policies they trust. Receipts remain cryptographically verifiable even when a node is not trusted as an authority.
