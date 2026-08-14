# Clef Rights Node Foundation Spec

## Objective

Provide labels, publishers, PROs, CMOs, collectives, and other rights administrators with a self-hostable authority store and permission API for represented creators, with signed receipts and interoperable evidence exports. Organization category is descriptive only and never establishes authority.

## Required capabilities

- Organizations, memberships, and least-privilege roles
- Works, recordings, parties, identifiers, and policy versions
- Evidence-backed authority claims and conflicts
- Permission requests, decisions, expiry, revocation, and disputes
- Named authority-organization review assignment with requester-safe disclosure and human-review enforcement
- Exact credit, backlink, placement, metadata, and publication-reporting obligations signed into each grant
- Append-only requester publication reports and authority compliance reviews that never alter permission status implicitly
- Canonical signed receipts and a public verifier
- Append-only transparency records
- Capability-scoped MLC and DDEX adapters, with preview-first CSV catalog intake
- Append-only DDEX exchange and partner-acknowledgement evidence, without implied permission effects
- Auditable webhooks and API credentials
- Organization-scoped, auditable registry lookup without distributing upstream credentials
- Reserve, royalty, reconciliation, and payout records
- Structured AI-use policies covering operations, source assets, model environments, duration and retention limits, and required safeguards

The normative AI policy shape and evaluation rules are documented in `AI_POLICY_SCHEMA.md`.

Settlement records use exact currency minor units. Terms, beneficiary splits, entries, and reconciliation snapshots are append-only. Beneficiaries total 10,000 basis points; deterministic largest-remainder allocation resolves indivisible minor units. A `paid` assertion requires a positive obligation and exact equality across confirmed external payment, total payouts, and every beneficiary allocation. Reserves never alter permission status.

Catalog intake separates metadata from authority. Works require ISWC or MLC song code; recordings require ISRC. Uploads stage rows for review, classify duplicates and conflicts, and require explicit commit. Catalog assets and client assignments are append-only; corrections create a higher version. Every catalog read model states that authority remains unverified until a separate claim passes operator review.

Permission administration separates routing, grant terms, reported use, and enforcement. A named reviewer assignment prevents other humans and machine credentials from deciding or reviewing the case. Grant approval signs exact obligations. A requester's publication report is a declaration; automated equality checks are comparisons only. An authority compliance review records a finding but has no automatic effect on the grant. Dispute, revocation, correction, and expiry remain explicit signed lifecycle actions.

Production webhook events enter a delivery outbox in the same transaction as the audited state change. Endpoint secrets are encrypted at rest, network delivery occurs in a separate worker, transient failures retry with bounded backoff, and events and attempt records are append-only.

## Explicit non-claims

- Metadata lookup does not prove authority.
- A reserve or standing offer is not permission.
- Clef does not automatically interpret law or resolve ownership disputes.
- A configured API credential does not expand the credential holder's authority.

## First release gate

One real catalog must complete staged import, client assignment, authority verification, policy publication, reviewer routing, permission request, approval with exact obligations, signed receipt verification, publication reporting, authority compliance review, and a reconciled payment record. The read-only `verify_real_pilot.py` acceptance workflow must then qualify the live records, their authority-document fingerprint, publication evidence, external payment evidence, and signed reconciliation; a synthetic run never satisfies this gate.
