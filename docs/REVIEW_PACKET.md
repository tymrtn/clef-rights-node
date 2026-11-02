# Review Clef for your catalog

Clef gives labels and publishers their own system for connecting recordings and compositions, recording creators' conditions and deciding specific licensing requests. Start with one song: see its recording and composition side by side, inspect the proposed AI use, then follow each representative's decision into a signed receipt.

## A ten-minute walkthrough

1. **Open the example catalog.** The guided sandbox prepares *Paper Skies* by Mara Vale, a fictional artist, with separate recording and composition identifiers. Example Records administers the recording; Example Publishing administers the composition. Each has a separate, explicitly fictional authority record.
2. **Read the creator's conditions.** Inspect the permitted musical inputs, source and output durations, territory, model use and reporting requirements. The proposed use is a short instrumental study with a limited source extract.
3. **Review both requests.** Approve the recording and composition separately. Each approval records the named reviewer's decision and the exact credit and reporting obligations. Try a request for model training or a broader territory to see the current policy and authority checks respond.
4. **Verify the result.** Verify an original receipt, then test an altered copy. The original remains available unchanged to the authorized parties. The separate public receipt uses the disclosure selection made before signing.
5. **Inspect connected catalogs.** In the local two-node demonstration, search *Paper Skies* across an independently running label and publisher. Inspect each signed result, its origin and expiry. The catalog administrator chooses which fields to publish; private agreements and evidence stay within party-scoped access.

Every example identity, catalog item and authority document in this walkthrough is synthetic. Organizations use their own catalog records, reviewed rights evidence and authorized staff when installing Clef.

## What each team can assess

| Your role | The useful question | Where to look |
| --- | --- | --- |
| Label or publisher | Can our team turn a creator's instructions into usable licensing conditions and an accountable decision? | Catalog, Policies, Authority, Permission ledger |
| Artist representative | Do the available choices describe the creator's intended uses, exclusions and musical components? | AI policy editor and the exact request conditions |
| Licensing buyer or AI company | Can we find a relevant catalog, understand an available use and submit a bounded request? | Connected catalogs, source policy and request review |
| Data or repertoire team | Can we correct identifiers and reconcile recording–composition connections without losing their sources? | Catalog import preview, correction history and registry references |
| Implementer | Can we reproduce the installation, scope API credentials, operate workers and recover the database and keys? | Setup guide, API documentation and deployment checks |
| Security or privacy reviewer | Do published fields, party access, withdrawals and verifiable records behave as described? | Public disclosure preview, private receipt endpoint and lifecycle evidence |

The MLC supplies publishing references in a U.S. administrative context and DSP-supplied recording metadata as received. The label or publisher supplies the evidence for the rights, shares and territories it administers. Clef retains these sources for review alongside the organization's creator instructions and decisions.

## Reproduce the evidence

- Run `.venv/bin/python scripts/run_local_preview.py` for the resumable guided example. Its default console is `http://127.0.0.1:16482`.
- Run `.venv/bin/python scripts/run_federation_preview.py --state-dir /private/path/to/fresh-preview --verify` for a tested pair of local nodes. Search spans the configured participants; adding a participant requires its origin and verified signing key.
- Run `make verify` for the full source, application, workflow, XML-fixture and deployment-configuration checks. Run `scripts/verify_container_preview.py` against locally built images to exercise the shipped web proxy.
- Read the [AI policy schema](foundation/AI_POLICY_SCHEMA.md), [federation protocol](foundation/CATALOG_FEDERATION.md), [receipt protocol](foundation/RECEIPT_PROTOCOL.md), [trust model](foundation/TRUST_MODEL.md) and [launch checklist](LAUNCH_CHECKLIST.md).

## Questions worth answering before a pilot

1. Which creator instructions, catalog relationships or musical components need a clearer representation for your repertoire?
2. Who can approve a use in your organization, and what evidence must they review first?
3. Which fields can your buyers see publicly, and which require a relationship with the catalog administrator?
4. What happens when a share, territory, creator instruction or administrator changes after a request arrives?
5. Which identifiers and source disagreements consume the most staff time today?
6. Which API, export, asset-delivery or reporting integration would make a first catalog practical for your team?
7. What would you need to complete an independent installation and a small controlled licensing trial?

Use ordinary project issues for product feedback. Send exploits, credentials, personal data and private catalog evidence through a private security advisory.

## Evidence needed for broader claims

Independent security review, an installation in a fresh adopter-owned account and a controlled real-catalog trial remain launch evidence to collect. Live DDEX exchange requires its bilateral operating arrangements. A royalty-distribution case requires external payment and beneficiary payout evidence plus reconciliation; the settlement records provide the review trail. The installing organization adopts its retention, privacy, dispute and incident procedures.

## Claim ledger and editorial record

- **Central claim:** Clef gives labels and publishers their own system for connecting recordings and compositions, recording creators' conditions and deciding specific licensing requests.
- **Strongest evidence:** The runnable synthetic walkthrough exercises separately administered recording and composition records, granular policies, named review, real signed receipts and live scope checks; the two-node verifier tests publication and authenticated source results.
- **Scope:** Current implemented software and reproducible fictional examples. Catalog authority comes from reviewed rightsholder evidence; participating peers are explicitly configured.
- **Falsifier:** A representative cannot express or enforce a declared condition, a decision exceeds reviewed authority, an unauthorized party reads private evidence, or a published result cannot be verified against its source and query.
- **Why it matters:** Catalog owners can expose defined licensing opportunities while keeping decisions, creator instructions and private evidence under their administration.
- **Previous thesis:** “Clef Rights Node lets an organization import identified catalog metadata, declare granular policies, submit evidence of authority, route bounded requests to named reviewers, and issue signed records.”
- **Revised thesis:** “Clef gives labels and publishers their own system for connecting recordings and compositions, recording creators' conditions and deciding specific licensing requests.” The opening now describes the reader's work; the walkthrough retains the prior operational claims and adds the tested federation path.
