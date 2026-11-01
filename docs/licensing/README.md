# Software licensing

## Current release

`v0.1.0-alpha.1` and the current checkout use [AGPL-3.0-only](../../LICENSE). The [proposed Clef Own-Node License](CLEF_OWN_NODE_LICENSE_DRAFT.md) is a draft for a future release. Its restrictions are not currently operative. The partner plan does not require current AGPL users or service providers to buy a commercial license to exercise their existing AGPL rights, subject to that license's obligations.

## Proposed partner plan — DRAFT

The approved business direction is documented here for implementation and legal review; approval of the plan does not adopt a license or open paid enrollment.

The proposed company standard path is fully autonomous. Deterministic checks qualify installation/support partners after verified business identity and contact, acceptance of the standard scope, and objective deployment/capability checks. An automated summary distinguishes verified/measured evidence from self-declared client evidence and grants no certification or entitlement. Standard agreements, orders, billing, and renewals follow approved rules without per-case Clef human approval; humans handle exceptions. Program-level legal authority and release-adoption gates remain required. The workflow below distinguishes existing interest-pack mail delivery from the future qualification and commercial lifecycle.

- [Own-Node License DRAFT](CLEF_OWN_NODE_LICENSE_DRAFT.md): the future client's zero-fee software grant and the boundary for services supplied by others.
- [Partner term sheet DRAFT](CLEF_PARTNER_TERM_SHEET_DRAFT.md): separate installation/support permissions, commercial terms, and client continuity.
- [Internal business case and operating workflow DRAFT](PARTNER_BUSINESS_CASE_AND_WORKFLOW_DRAFT.md): assumptions, cost/acquisition/retention arithmetic, lifecycle rules, and exception handling. This is a design, not an operating partner service.

The proposed partner fee is **US$1,200 per client organization per year**, payable by the partner to Clef. **Each partner's first client costs US$600 for that client's first year only**; that client's renewal and every additional client's first year cost US$1,200. There is no activation fee, activation key, runtime phone-home requirement, or remote license shutdown. Partners set and retain their installation, migration, customization, training, and support revenue; Clef takes no percentage of those services or of music royalties or licensing receipts. The partner owns client support, with bounded product-defect escalation to Clef as described in the drafts.

**First release: partner interest only.** Prepare or collect expressions of interest through an approved channel; do not take payment, sign paid enrollments, issue partner entitlements, promise production readiness, or describe interested providers as authorized partners. Any external outreach still requires approval for its recipient, channel, and payload. Paid operation requires the legal and release gates below, a final signed partner agreement, and a client order. Existing AGPL use continues under the current terms.

The proposed commercial-use boundary is:

> Organizations may run Clef for their own music-rights administration, including the catalogs of artists and rightsholders they actually represent. Their employees may self-install; Clef or a separately licensed partner may install and support a node in the client's own infrastructure. Third-party services require separate authorization. Hosted platforms, OEM embedding, software resale, and white-label distribution require distinct commercial terms.

## Examples under the proposed terms

| Activity | Proposed treatment |
| --- | --- |
| Label runs its node and licenses its artists' catalog for AI use | Permitted; genuine music-rights administration and its revenue are allowed. |
| Publisher gives represented writers access to approvals and records | Permitted within the publisher's rights-administration service. |
| A collecting society administers represented members' rights through its own node | Permitted, subject to its actual authority over those rights. |
| An employee uses a coding assistant to install on the organization's Railway account | Permitted self-installation using general-purpose tools. |
| Clef installs on the adopter's infrastructure and hands over administration | Reserved Clef service, under a separate services agreement. |
| Separately licensed partner installs, upgrades, or supports a registered client's node in the client's own cloud account | Permitted within the signed partner agreement; the client retains control and its own-node entitlement. |
| Consultancy installs Clef on a customer's account without a separate partner grant | Reserved; the future own-node license alone does not authorize this, even if bundled or free. |
| Agency renames a fork and sells it, embeds it in another product, or hosts customer nodes in its own accounts | Requires distinct hosted/OEM or resale authorization; the installation/support partner plan does not include it. |
| Parent company's IT team deploys a node for a separate subsidiary | Requires a separate service grant covering that subsidiary; each legal entity is counted separately. The subsidiary may also self-install through its employees or use Clef/an Authorized Partner. |
| Partner leaves or its annual entitlement lapses | The compliant client keeps running its covered release and may self-support or select Clef/another Authorized Partner; no runtime deactivation. |
| Company claims a nominal mandate only to sell customers their own nodes | Prohibited; a software contract is insufficient. |
| Independent application exchanges recordings, work references, policies, or receipts with a node | Permitted interoperability; data and music permissions remain applicable. |
| Recipient exercises valid rights in an earlier AGPL or Apache copy | Governed by that earlier license, including its commercial permissions. |

## Adoption requirements

Identify the legal licensor and confirm it has authority over all material being offered under the new terms. Git author names alone do not establish ownership or permission to relicense contributions. Check the full distribution and contribution history, including earlier permissive releases, and obtain any needed permissions or exclude the affected material.

Review the draft's patent scope, termination provisions, and enforceability for the actual licensor and intended markets before designating a release. The draft presently grants copyright permissions; it does not settle the licensing of separately held patents.

Before paid partner enrollment, identify the legal contracting entity and authorized signatories; approve final client and partner terms, tax/invoicing treatment, data responsibilities, support boundaries, and continuity provisions; and record the releases and immutable revisions each agreement covers. Confirm ownership or sufficient licensing authority for both the own-node and separate commercial grants, including contributions and third-party distribution obligations. Interest, an invoice, a payment, or a Git author name cannot substitute for these gates. Keep hosted/OEM licensing in a separate review and agreement.

Preserve third-party notices. A preliminary local metadata inspection on September 5, 2026 found MIT, ISC, Apache-2.0, CC-BY-4.0, BlueOak-1.0.0, MPL-2.0, BSD-3-Clause, and 0BSD declarations in the frontend lockfile, and LGPL-with-exceptions metadata for installed `psycopg2-binary`. This is a starting inventory, not a complete source, container, binary, or transitive-dependency audit; component obligations remain independently applicable.

For the designated release, adopt the completed text as the root `LICENSE`, retain earlier-license notices, and update the README, package metadata, `/v1/node/info`, console disclosures, release/pilot verification expectations, and marketing copy together. Preserve source-revision inspection and the corresponding-source obligations of any AGPL material that remains. The license URL and any installer acceptance must identify the actual release's terms.

Describe a release under the proposed restrictions as **source-available**, with permitted commercial own-node use. Keep the earlier alpha's AGPL label attached to that version. Record contribution terms for future submissions explicitly; the existing contributing guide provides no separate relicensing permission.

## Why a separate license is required

The AGPL's sections 2, 7, and 10 preserve qualifying existing grants and prevent adding the proposed restrictions to those grants. The copyright holder can offer authorized material under different terms, while existing recipients retain their earlier permissions. See the [GNU license FAQ](https://www.gnu.org/licenses/gpl-faq.html.en#ReleaseUnderGPLAndNF) and the repository's [AGPL text](../../LICENSE).

The proposed restrictions also fall outside the Open Source Definition's redistribution and commercial-use freedoms. See the [Open Source Initiative's definition](https://opensource.org/osd). Publishing source code under these terms should therefore be described as source-available.
