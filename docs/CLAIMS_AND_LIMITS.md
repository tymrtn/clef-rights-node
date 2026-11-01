# Claims and limits

This file is the canonical public-claim boundary for the alpha. A capability belongs in marketing copy only when a current test, verifier, or source reference supports it.

## Implemented

- Self-hosted organization, role, catalog, policy, authority, permission, receipt, audit, webhook, and external-settlement records.
- Separate composition, master, lyrics, performance, voice, and likeness authority declarations.
- AI policy dimensions for training, fine-tuning, licensed grounding, embeddings, stems, transformations, lyrics, synthetic voice, duration, retention, model environment, attribution, watermarking, similarity review, and deletion attestations.
- Evidence review before authority becomes requester-discoverable.
- Explicit administrator consent before catalog fields enter public federation search; pinned signatures and live searches across up to eight configured peers, with withdrawal, stale-policy suppression and partial-failure reporting.
- Signed permission requests between configured nodes: the requester's node signs the request, the source node decides it under its own policy and reviewers, and its answer carries receipts that the requester's node verifies against the source's pinned key. Replays return the original record; unpinned or forged signatures are refused.
- Account-free reading of published terms (`/v1/public/catalog/publications/{id}`) and a signed node descriptor (`/.well-known/clef-node`).
- These federation capabilities are a working candidate with a two-node local proof and a hosted verifier rehearsed locally; see the [federation claim ledger and boundaries](foundation/CATALOG_FEDERATION.md).
- Named human routing, exact signed obligations, publication reports, compliance reviews, lifecycle receipts, and independent signature checks. Receipt verification reports `valid` only for this node's key or a configured peer's pinned key.
- Authorized lookups from The MLC for musical-work metadata, reported publishing claims in a U.S. administrative context, and DSP-supplied recording references. Results remain observed evidence; master ownership, controlled shares and territorial mandates come from the relevant rightsholders.
- Schema-validated DDEX MWL generation and recorded acknowledgements when an operator supplies licensed schemas, identifiers, capabilities, and a counterparty agreement.
- Records of reserves, royalties, external payments, beneficiary payouts, reversals, and reconciliation. Clef does not hold or transfer funds.

## Not implemented or not established

- Automated copyright, ownership, infringement, similarity, or legal determinations.
- Universal licenses, automatic PRO/CMO registration, production DDEX delivery, or partner acceptance.
- Money movement, escrow, KYC, sanctions screening, tax withholding, collections, or guaranteed royalties.
- Model training, generation, source detection, acoustic watermark insertion, platform takedowns, or enforcement outside a signed obligation.
- Certification, endorsement, conformance, or approval by The MLC, DDEX, a PRO/CMO, label, publisher, platform, or coalition.
- Open federation: nodes exchange requests only with peers their operators configured and pinned. There is no peer discovery, worldwide index, cross-node negotiation or payment.
- Machine enforcement of published terms. Terms are published for anyone to read; nothing makes a crawler or model operator read or follow them.
- A signed receipt for a local rejection. Grants and lifecycle changes are receipted; a rejection is recorded in the audit log, and a cross-node requester receives it as a signed status statement.
- A Clef-hosted production service or production support commitment.

## Required language

- Imported catalog data is metadata, not authority.
- A verified claim records an operator's evidence review; it does not create ownership.
- A permission receipt proves what this node recorded and signed; it does not bind an unrepresented party.
- A publication report is submitted evidence, not proof of what a third-party platform displayed.
- Payment and payout records describe external evidence; Clef does not move money.

## Prohibited extrapolations

Do not call Clef definitive, universal, fully compliant, automatically licensed, DDEX-certified, The MLC-approved, real-time attribution, exact contribution analysis, guaranteed payment, or automated royalty filing. Do not say every creator is credited, every use is licensed, or every royalty is paid. Do not say AI systems see, receive or respect Clef terms; say the terms are published where AI companies can read them and request permission. Do not call configured federation an open network, and do not say every decision is signed.

## Catalog-source claim ledger, 2026-09-17

- Central claim: Clef links catalog observations to separately reviewed authority so labels and publishers can administer bounded permissions.
- Strongest evidence: the catalog, authority and permission workflow tests, explicit `sourceScope` on The MLC lookup responses, and retained per-ISRC reconciliation observations.
- Scope and limits: The MLC’s publishing context is U.S.; its recording references are DSP-supplied and processed as received. Master ownership and master shares require rightsholder evidence. Cross-source agreement can share the same upstream data.
- Falsifier: a permission exceeds the represented right, share or territory, or a purported work link cannot be traced to its source and reviewed evidence.
- Why it matters: administrators can use existing catalog information while taking responsibility for the rights and permissions they supply.

Previous capability sentence: “MLC catalog and ownership-evidence reads when an operator supplies authorized credentials. Results remain observed evidence.”

Revised capability sentence: “Authorized lookups from The MLC for musical-work metadata, reported publishing claims in a U.S. administrative context, and DSP-supplied recording references. Results remain observed evidence; master ownership, controlled shares and territorial mandates come from the relevant rightsholders.”

This narrows the implied scope of “ownership-evidence reads”: publishing information and recording references have different sources and territorial meaning. The central claim about label/publisher administration is preserved. Technical capability identifiers remain stable for existing integrations.

## Federation claim ledger, 2026-11-01

- Central claim: a requester on a configured peer node can request a published catalog entry's terms through its own node and receive the source node's decision with receipts verifiable against the source's pinned key; anyone can read the published terms without an account.
- Strongest evidence: `backend/tests/test_federated_requests.py` (signed round trip, replay, forged and unpinned signers, withdrawn entries, foreign-key receipts) and the two-process `scripts/run_federation_preview.py --verify` proof.
- Scope and limits: configured, pinned peers only; the source's reviewers decide; no negotiation, payment, peer discovery or index; published terms carry no enforcement.
- Falsifier: an unpinned node gets a request recorded; a replay creates a second request; a withdrawn entry accepts a request; a requester records a receipt the source's key did not sign; public terms expose a field the administrator did not preview.
- Why it matters: "an API to request terms for AI use" holds across organizations' own nodes, with each side keeping a verifiable record.

Previous capability sentence: "Explicit administrator consent before catalog fields enter public federation search; pinned signatures and live searches across up to eight configured peers, with withdrawal, stale-policy suppression and partial-failure reporting."

Revised capability sentences: the discovery sentence is unchanged; signed cross-node requests and account-free public terms are added. This widens the claim and narrows nothing.
