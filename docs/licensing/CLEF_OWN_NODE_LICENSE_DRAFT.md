# Clef Own-Node License

Version 1.0 — proposed text, September 6, 2026

**DRAFT — awaiting identification of the licensor, confirmation of its licensing authority, and designation of the first covered release. This document grants no license and does not amend the repository's current AGPL license.**

Before adoption, complete these fields and remove this draft notice:

- Licensor: **[legal name of copyright holder or authorized licensing entity]**, operating as Clef.
- Copyright notice: **[copyright year(s) and holder(s)]**.
- First covered release and immutable revision: **[release and commit]**.
- License contact: **[licensor's published contact]**.

## 1. Scope and definitions

“Licensor” means the person or entity identified above. “You” means the single legal person or organization exercising the permissions in this license. An individual acting for an organization must have authority to bind it.

“Software” means the Clef Rights Node implementation and accompanying materials that the Licensor expressly distributes under this license, including modifications to those materials. Separately licensed components and materials remain subject to their own licenses.

“Your Own Node” means an installation that You control, in infrastructure You own or hold directly under Your hosting account, for Your own music-rights administration. It may include development, staging, backup, disaster-recovery, and production instances for that purpose.

“Authorized Partner” means an independent provider with a separate written agreement from the Licensor expressly permitting installation and support for identified client organizations and covered releases. That agreement supplies the partner's service permissions; this license supplies Your own-node permissions. A partner's infrastructure account is not Your Own Node merely because the partner gives You a login.

Your music-rights administration includes catalogs You own, license, represent, or administer under an actual rights-administration mandate. A mandate must concern the underlying music rights and confer a substantive administration responsibility. A software, hosting, or installation contract alone is not such a mandate.

## 2. Permission to operate Your Own Node

Subject to this license, the Licensor grants You a worldwide, nonexclusive, royalty-free copyright license to inspect, copy, modify, test, install, and operate the Software solely for evaluating, establishing, securing, and administering Your Own Node.

You may use Your Own Node commercially. You may negotiate music licenses, collect music-licensing revenue, and charge for Your genuine music-rights administration services. Artists, songwriters, represented rightsholders, license applicants, and other counterparties may access Your Own Node's relevant workflows and records as part of those activities.

You may customize the interface with Your branding and connect Your Own Node to other systems and rights nodes. Separate legal entities each need their own entitlement under this license; an affiliate or group-company relationship does not itself authorize one entity to deploy nodes for the others.

The software-license fee for the permitted own-node use is zero. Cloud infrastructure, third-party services, music rights, and Clef or Authorized Partner services have their own terms and charges. This license imposes no share of music royalties, licensing receipts, or rights-administration revenue.

## 3. Self-installation, Clef installation, and Authorized Partners

You and Your employees may install, configure, modify, secure, upgrade, and administer Your Own Node. You may use general-purpose cloud infrastructure, deployment tools, and coding assistants under Your direction and accounts. Supplying those general-purpose tools or infrastructure alone is permitted; providing a Clef-specific installation or managed-node service is governed by section 4.

The Licensor may install and configure Your Own Node for You under a separate Clef services agreement. That service must identify the Licensor as the provider and leave the installation in Your infrastructure and under Your control.

You may engage an Authorized Partner to install, configure, customize, migrate, secure, upgrade, and support Your Own Node within the scope of its separate partner agreement. The installation must remain in Your directly held infrastructure account, with Your administrative access, data, backups, signing keys, and ability to replace the provider under Your control. The partner may receive revocable delegated access; it must not become the sole controller of the installation. Hiring an independent provider under Your account does not turn that provider into You or an employee.

Expiry or termination of a partner's service entitlement alone does not end Your compliant own-node license or require shutdown, activation, or deletion of Your records. You may continue through Your employees, Clef, or another Authorized Partner. The departing provider's limited handover permissions and obligations must be stated in its separate agreement. This continuity does not promise future releases, free support, or relief from Your own breach of this license.

## 4. Reserved uses

The permissions in this license are conditioned on compliance with the following restrictions. Except for the Licensor's services and services expressly authorized by a separate written agreement as described in section 3, You may not, directly or through another person:

1. Sell, resell, rent, lease, sublicense, or commercially distribute the Software, copies, modifications, or a product or service whose substance is access to its rights-node functionality.
2. Install, deploy, configure, provision, migrate, host, operate, or manage the Software as a service for another legal person or organization, whether paid or unpaid, including in that other organization's own infrastructure.
3. Offer the Software as a hosted service, managed rights-node service, white-label software platform, reseller package, or software installation service for independent customer organizations.
4. Evade these restrictions by renaming or modifying the Software, bundling it with other services, using an affiliate or subcontractor, charging through a different line item, or describing a software service as a rights-administration mandate.

This license alone grants no reseller, implementation-partner, or third-party deployment entitlement. A separate partner agreement may authorize client-owned installation and ongoing support; the restrictions above do not prohibit activities expressly within that grant. Partner-owned hosting, shared hosted platforms, OEM embedding, software resale, and white-label distribution require a distinct hosted/OEM or other express commercial agreement; they are not included by an installation/support entitlement. Client interface branding under section 2 remains permitted.

A customer may purchase Your music-rights administration services under section 2. Supplying that customer with its own node requires the separate authorization described in section 3, rather than a nominal rights-administration mandate. The [partner term sheet](CLEF_PARTNER_TERM_SHEET_DRAFT.md) describes proposed commercial terms only and grants no such authorization while it remains a draft.

## 5. Source inspection and notices

Preserve the Software's copyright, license, and attribution notices and identify Your modifications. Keep an accessible software-notices view in Your installation identifying Clef Rights Node, this license, the deployed revision, and the location of the source for that revision. Your private catalog data, credentials, and confidential agreements are excluded from the source disclosure.

You may publish or share the Software's source and Your modifications without a distribution fee for inspection, contribution, and recipients' permitted own-node use, with this license and the relevant notices intact. Recipients obtain permissions to the Licensor's material directly from the Licensor under this license. You must license any of Your modifications included in that distribution on these same terms. This source-sharing permission does not authorize the reserved services in section 4.

You may retain internal backups and provide the source to the Licensor or Your Authorized Partner for services within its written authorization. Source access, modification, branding changes, or possession of a copy creates no permission to supply software or deployment services beyond this license or a separate written grant.

## 6. Catalog data and interoperability

You and the relevant rightsholders retain their rights in catalog data, music, policies, licenses, receipts, and other records. Subject to those parties' permissions, You may export and exchange those records, operate an API for Your music-rights administration, and federate Your Own Node with other nodes.

The restrictions on selling or deploying the Software do not restrict the sale of music licenses or the exchange of records. The Licensor also permits copying the supplied interface definitions, schemas, and integration examples as necessary to build independent clients that submit, retrieve, exchange, or verify those records. That permission does not extend to copying the node implementation into a product or service reserved by section 4.

## 7. Earlier grants and third-party materials

This license applies only to materials expressly offered under it by a party authorized to do so. Rights already granted under AGPL, Apache, or any other license continue under those terms, including lawful redistribution and derivative works under those earlier grants. This license adds no restrictions to those grants and does not relicense third-party material.

Preserve and comply with the licenses and notices of dependencies, bundled components, standards materials, and separately licensed contributions. If the Licensor lacks authority to offer a component under this license, the component's existing license governs it.

## 8. Term and breach

The permissions granted for a covered release continue for the duration of the applicable copyright while You comply with this license. A later license version does not change the terms for an existing covered release without Your agreement.

On breach, You must stop the violating activity immediately. The Licensor may terminate these permissions by written notice if a material breach remains uncured 30 days after notice describing it. A deliberate or repeated breach of section 4 permits termination by written notice without a cure period.

Following termination, cease use and distribution of the Software and remove operational copies. You may retain legally required archival copies and copies needed solely to export Your records for up to 30 days, with public and customer service disabled. Termination under this license does not terminate rights held under a separate license.

## 9. Warranty, liability, and other rights

To the extent permitted by applicable law, the Software is provided “as is,” without warranties of merchantability, fitness for a particular purpose, title, or noninfringement. The Licensor and contributors are not liable for losses arising from use or inability to use the Software, including lost revenue, lost data, interruption, or indirect or consequential loss, except where applicable law prevents that exclusion. A separately signed agreement may provide additional commitments.

This license grants the copyright permissions expressly stated. Clef trademarks and other rights remain reserved. Preserve truthful software attribution when using Your own branding; further use of Clef's marks requires permission from the relevant holder.

Mandatory applicable law remains effective. If a provision is unenforceable, the remaining provisions continue to the extent permitted by that law. Additional rights require a separate written agreement from a person authorized to grant them.
