# Clef installation and support partner term sheet

**DRAFT — September 6, 2026. Proposed business terms for a future program; nonbinding, not an offer or license grant. First-release participation is interest-only.** The current checkout and `v0.1.0-alpha.1` remain [AGPL-3.0-only](../../LICENSE). No fee or restriction here attaches to permissions already held under AGPL, Apache, or another earlier license. See the [licensing overview and adoption gates](README.md).

The commercial direction below is approved for drafting. The proposed administrative defaults and unresolved legal terms require inclusion in a final agreement before paid operation.

## Parties and prerequisites

The agreement must identify **[Clef legal licensor/contracting entity, registration/address, authorized signer]**, **[partner legal entity, registration/address, authorized signer]**, and each **[client legal entity, billing reference, administrative contact]**. “Clef” is a working brand, not a substitute for identifying the contracting party.

Before signature or billing, Clef must establish authority to grant the proposed copyright permissions, resolve contribution and third-party obligations, obtain legal review, and designate the covered release(s), immutable revision(s), source location(s), and applicable license texts. Patent rights, if needed, require express treatment. Each client must accept the applicable own-node terms and authorize the partner's access; technical authority to install software supplies no authority over music rights.

Standard partner qualification is automated: verified business identity/contact, acceptance of the unchanged standard scope, and objective deployment/capability checks produce a deterministic qualification summary without a Clef human review or qualification call. The summary labels applicant/client self-declarations separately from independently verified facts and measured test results; qualification is neither certification nor a license grant. Once program-level legal/release prerequisites are complete, standard contracting, client orders, billing, and renewals proceed autonomously under approved rules and the parties' required acceptances. Humans resolve exceptions such as conflicting evidence, unsupported checks, or nonstandard terms. See the [qualification and lifecycle design](PARTNER_BUSINESS_CASE_AND_WORKFLOW_DRAFT.md).

## Grant and client control

For each registered client during its paid service term, the proposed separate, nonexclusive partner grant permits installing, configuring, customizing, migrating, securing, upgrading, training for, and supporting Clef on that client's own infrastructure. Copying and modifying covered software is permitted only as needed for those services, with applicable source, license, attribution, and third-party obligations preserved. The client's continuing software entitlement comes directly from the applicable own-node license, not a revocable software sublicense from the partner.

The client must directly hold its hosting account and retain owner access, domains, billing control, data, backups, source/revision records, and signing-key custody or recovery capability. Partner access is delegated, limited, and revocable. A client login to a partner-owned hosting account is insufficient. A partner may provide ongoing technical administration within these boundaries; the client retains rights decisions and infrastructure control.

One client organization means one legal entity receiving these services. Its development, staging, production, backup, and disaster-recovery instances for its own rights administration are included in one annual fee. Represented artists and catalogs using that organization's rights-administration workflows do not become separately billable clients merely by participating. A separate organization receiving its own installation/support is a separate client, including an affiliate. Record scope before service begins; unclear mandates or entity boundaries require review.

The grant covers only releases expressly included in the executed agreement or a later approved schedule. It does not promise future releases or authorize relicensing third-party material. The partner may not sublicense its partner entitlement. Any subcontractor requiring service permissions must be expressly covered by the agreement or separately authorized; the partner remains accountable for its service commitments.

## Price and service revenue

| Item | Proposed term |
| --- | --- |
| Annual partner fee payable to Clef | **US$1,200 per client organization per year.** |
| Introductory fee | **US$600 for each partner's first client, for that client's first year only.** |
| Further clients and renewals | US$1,200 each per year, including renewal of the introductory client. |
| Activation | None: no activation/setup fee payable to Clef, activation key, mandatory license-server check, or runtime shutdown tied to billing. |
| Partner service charges | Partner sets its own installation, migration, customization, training, and support prices and retains 100% of that revenue. The fixed annual Clef fee remains payable independently. |
| Music revenue | No royalty skim or percentage of catalog value, music-license revenue, settlements, or rights-administration receipts. |
| Infrastructure and other services | Client contracts for and pays its cloud and third-party costs; partner services are separately agreed. |

Proposed billing defaults: annual invoicing in advance, US dollars, with applicable taxes separately stated; partner is the debtor to Clef even if it recovers the cost in its client pricing. The agreed start date and cleared payment must both occur before future commercial service entitlement begins, after all legal gates pass. One annual term runs from the recorded start through the day before its anniversary. A payment record is commercial evidence, not software activation or proof of music permission.

The introductory benefit is recorded once against the verified partner identity and its first paid client order. Additional instances, re-enrollment, entity renaming, or replacement of a contact do not reset it. If two first orders arrive together, reserve the discount for one in a single transaction. Voids, refunds, duplicate entities, mergers, and partner transfers require review and an auditable credit or correction; they must not silently award a second discount. Example: a partner with five new clients owes US$600 + 4 × US$1,200 = **US$5,400** in year one; renewal of all five costs **US$6,000**.

Proposed renewal default: reminders at 60, 30, and 7 days before expiry, with affirmative renewal/order confirmation before charging. No automatic price increase or retroactive change to a paid term. Cancellation stops the next renewal; ordinary midterm cancellation has no automatic prorated refund, subject to the final agreement and mandatory law. Clef-caused inability to provide the contracted grant, disputed payments, and service transfers require individual resolution. These billing defaults must be finalized in the signed agreement.

## Support responsibilities

The partner owns the client relationship, onboarding, first-line and second-line support, infrastructure maintenance, backups and restore testing, upgrades, monitoring, and incident coordination. The partner agrees its service hours, response targets, recovery objectives, escalation process, and handover obligations directly with the client. It retains the associated revenue and cost risk.

Clef supplies partner documentation and receives reproducible core-product defects through a named partner contact. Clef triages those reports; this draft promises no resolution deadline, 24/7 coverage, unlimited engineering, or direct client support SLA. Custom development, data cleanup, client-specific integrations, and infrastructure troubleshooting need separately agreed scope and pricing. Security incidents use the approved private reporting route and immediate human triage. Any paid Clef support commitment must be expressly agreed; the cost assumptions in the internal model are planning estimates, not support allowances or customer promises.

## Continuity, expiry, and handover

The client's compliant entitlement to the covered installed release continues if the partner agreement ends, its annual service entitlement expires, or the partner closes. There is no remote deactivation, data lock, key withholding, or forced deletion because the partner has not renewed. Existing music licenses, signed receipts, and data remain governed by their own terms; a partner billing event cannot revoke them. The client can self-support through its employees, engage Clef, or appoint another Authorized Partner.

Maintain a client-accessible handover package throughout service: deployment/revision inventory, configuration and restore instructions, source/notices, backup/export locations, recovery contacts, and a secrets-transfer procedure. Transfer secrets through the client's secret manager, never invoices or support tickets. The client must already have owner access before the partner leaves.

Proposed transition grant: for 30 days after expiry or termination, the outgoing partner may, with client consent, export, transfer, restore, and perform necessary safety maintenance solely to complete handover. It may not use this period for new installations, expansion, or ongoing commercial service beyond transition. Credentials implicated in an incident may be revoked immediately; handover then proceeds through the client or a replacement provider. Retain only records required by the final contract/law after returning or deleting client copies. The client's separate own-node breach remains governed by that license's own termination terms.

A replacement partner's service rights must be confirmed before it takes over. Proposed default: carry the remaining prepaid client term to the replacement through a signed transfer record, without a second annual fee for the same client period; the replacement pays US$1,200 at the next renewal. The introductory benefit remains consumed by the original partner and the transfer alone neither consumes nor refreshes the replacement's benefit. Transfers and any refunds/credits require Clef review. Continuity grants continued use of an installed covered release, not perpetual free upgrades or support.

## Separate hosted/OEM terms

This installation/support plan does not grant partner-owned hosting, multi-client hosted platforms, OEM embedding, software resale, or white-label distribution. Those require a distinct hosted/OEM or other commercial agreement defining scope, fees, distribution obligations, support, and client continuity. Branding a client's own interface is permitted within its own-node grant and does not create an OEM entitlement. An interested hosted/OEM provider goes to a separate review queue; this US$1,200 schedule is not its quoted price.

## Agreement completion and launch

Before paid launch, finalize governing law/forum, notices and cure/termination mechanics, liability and indemnities, confidentiality/privacy and data roles, security duties, taxes, refunds and transfers, trademark use, subcontractor scope, support commitments, and any patent treatment. Confirm that the final partner grant and own-node text agree on continuity and reserved uses. Record all legal identity, licensing authority, and release-designation approvals with evidence; do not infer them from an expression of interest or payment.

The first release collects partner interest only through an approved channel. It issues no paid enrollment, invoice, entitlement, certification, endorsement, or deployment commitment. External communication requires Tyler's explicit approval for its recipient, channel, and payload. Later commercial operation follows the [internal lifecycle design](PARTNER_BUSINESS_CASE_AND_WORKFLOW_DRAFT.md) only after its launch gates are met.
