# Partner business case and operating workflow

**INTERNAL DRAFT — September 6, 2026.** Design for the approved client-owned installation/support partner direction. Prices are proposed commercial terms; all volume, effort, conversion, retention, and cost figures below are explicit planning assumptions, not measured results or market benchmarks. This document defines future operations; it does not implement automation, create a tracker, authorize outreach, or change the current AGPL release.

Use the [licensing overview](README.md) for current versus future terms and the [partner term sheet](CLEF_PARTNER_TERM_SHEET_DRAFT.md) for scope. The first release is **interest-only**: no payments, paid enrollment, partner entitlements, or promises of production readiness. Legal identity, licensing authority, final agreements, and designated covered releases remain gates before commercial operation.

## Business rationale and boundaries

Partners bring existing client relationships and earn implementation and recurring support revenue. Clef receives a predictable annual fee for a separate service grant covering each client-owned installation, while clients retain their infrastructure, records, and ability to change providers. Partner delivery can reduce Clef's direct acquisition and support effort, but this only works if partners actually bring multiple clients and resolve ordinary support themselves.

The model charges **US$1,200/client organization/year**, with **US$600 for each partner's first client in its first year only**. There is no activation charge or technical activation dependency. Partners retain all their service revenue; Clef takes no royalty skim or share of music licensing receipts. Client own-node software use has a zero fee under the future draft. Hosted/OEM opportunities require separate scope and economics. Current AGPL users retain their grants, so the model cannot assume all existing deployments will convert or that service providers need this plan for AGPL work.

Start with implementers who already support rights administrators, can operate client-owned infrastructure, and can nominate several real prospects. Value must come from supported releases, usable documentation, predictable commercial permissions, and reliable handover. Demand, willingness to pay, partner productivity, and support savings remain hypotheses to test after the interest stage and legal gates.

## Planning inputs and unit economics

All amounts are US dollars. Assume annual advance collection, no bad debt/refunds, and unchanged prices during the modeled periods; taxes are pass-through and excluded. Labor is an opportunity cost at **$80/hour**, including founder time. Human effort below is a conservative pooled allowance for exceptions and maintaining reusable automation, allocated across cohorts; it is not a required call, review, or approval for each partner/client. Standard cases run autonomously. Figures are contribution before fixed program costs and core-product engineering, not net profit or cash balances. Client cloud bills and partner service-delivery costs are borne outside Clef's model.

| Input | Base assumption | Arithmetic or treatment |
| --- | --- | --- |
| Productive partner | Five paid client organizations in year one | One discounted client and four standard clients; all start together solely for this annual model. |
| Payment processing | 3% of collected fees | $36 on $1,200; $18 on $600. Assumed blended cost, not a provider quote. |
| Client billing/tool allocation | $24 per client/year | $2 × 12; excludes hosting the client's node. |
| Client annual administrative exceptions | 0.5 Clef hour/year | 0.5 × $80 = $40. |
| Core-product escalation | 1 Clef hour/client/year | 1 × $80 = $80; excludes planned core-product roadmap work. |
| Recurring client cost | Fee × 3% + $24 + $40 + $80 | **$180 standard; $162 introductory.** These are cost estimates, not support-hour entitlements. |
| Client initial exception/automation allocation | 1 Clef hour equivalent, once | $80/client pooled reserve, additional to annual cost; no routine manual review. |
| Ongoing partner exception and workflow-maintenance allocation | $300/productive partner/year | 3.75 hours × $80 pooled reserve; additional to client-specific work. |
| Partner acquisition | $1,200/productive partner | Funnel below; includes time spent on unsuccessful prospects. |
| Initial partner enablement allocation | 4 Clef hour equivalents, once | $320 allocated when first paid client starts, for reusable onboarding maintenance and exceptions; standard onboarding is self-service and automated. |
| Client conditional annual retention | 90% | Of clients whose partner stays; no expansion assumed. |
| Partner annual retention | 90% | Loss conservatively loses all its fee revenue; transfers to another partner are excluded from this model. |

Acquisition funnel assumption for **100 relevant partner prospects**: 20 qualify (20%); 8 complete agreements (8 / 20 = 40%); 5 become productive (5 / 8 = 62.5%). Overall productive conversion = 20% × 40% × 62.5% = **5%**. This describes a possible future commercial funnel, not an authorized outreach batch. Agreement completion alone produces no revenue; a productive partner must bring paying clients.

Acquisition budget for that batch: maintaining approved sourcing/outreach automation and handling its exceptions, 40 hours × $80 = $3,200; qualification-rule maintenance and identity/capability exceptions, a pooled 15 hours × $80 = $1,200; contract-template/workflow maintenance and nonstandard contracting exceptions, a pooled 20 hours × $80 = $1,600. Total **$6,000 / 5 productive partners = $1,200 each**. There are no mandatory qualification calls or per-agreement human approvals on the standard path. These allocations preserve the conservative budget while automated completion handles ordinary cases; exceptional legal work beyond the reserve must be counted separately. The three nonproductive agreement completions receive no ongoing enablement allocation until their first paid client; further pursuit adds acquisition cost. Validate actual automation costs and exception incidence rather than treating these reserves as measured savings or required labor.

For one productive partner with five new clients:

- Year-one fees = $600 + 4 × $1,200 = **$5,400**.
- Recurring client cost = $162 + 4 × $180 = **$882**.
- Initial client exception/automation allocation = 5 × $80 = **$400**; annual partner allocation = **$300**.
- Acquisition plus enablement = $1,200 + $320 = **$1,520**, or $304/client. Including the initial client allocation makes fully loaded initial acquisition/enablement **$384/client**.
- Year-one contribution = $5,400 − $882 − $400 − $300 − $1,520 = **$2,298**, or **42.56%** of fees.
- Renewal of all five = $6,000 − (5 × $180) − $300 = **$4,800**, or **80%**, before fixed costs. Each standard client contributes $1,020 before partner-level costs.

The first-year introductory concession costs Clef $600 of fees and saves $18 processing: **$582 net contribution reduction per new partner**. It does not repeat at renewal and is not a separate activation charge.

For `N ≥ 1` new clients per partner, with one introductory fee and the same assumptions:

`Revenue = 1,200N − 600`

`Cost = (180N − 18) + 80N + 300 + 1,520 = 260N + 1,802`

`Year-one contribution = 940N − 2,402`

| New clients per partner | Fees | Total allocated cost | Contribution |
| --- | ---: | ---: | ---: |
| 1 | $600 | $2,062 | −$1,462 |
| 3 | $3,000 | $2,582 | $418 |
| 5 | $5,400 | $3,102 | $2,298 |
| 8 | $9,000 | $3,882 | $5,118 |

Year-one acquisition recovery requires `ceil(2,402 / 940) = 3` clients under these assumptions. Annual payment may arrive early, but costs occur throughout the term. At five clients, a smoothed payback proxy is `(1,520 + 400) / ((5,400 − 882 − 300) / 12) = 5.46 months`. This is a normalized contribution calculation, not an observed cash-payback date. Staggered client starts delay recovery and must be tracked as actual cohorts.

## Retention, scale, and sensitivity

For the original five-client cohort, expected fee-bearing clients after one renewal = `5 × 90% partner retention × 90% conditional client retention = 4.05`. Fractional clients are expectations across many cohorts, never billable quantities. Both rates remain constant, conditional client retention is independent across years, and no expansion or replacement clients are assumed.

| Cohort year | Expected clients | Expected fees | Client recurring cost | Expected partner cost | Contribution before fixed costs |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1, new | 5 | $5,400 | $882 | $300 | $2,298 after $1,920 initial costs |
| 2 | 5 × 0.81 = 4.05 | $4,860 | $729 | $300 × 0.90 = $270 | **$3,861** |
| 3 | 5 × 0.81² = 3.2805 | $3,936.60 | $590.49 | $300 × 0.90² = $243 | **$3,103.11** |

Three-year undiscounted cohort contribution = $2,298 + $3,861 + $3,103.11 = **$9,262.11**. This finite horizon avoids presenting an unbounded lifetime-value claim. At renewal, expected revenue retention is 81% for a full-price cohort; year two versus the discounted initial $5,400 is $4,860 / $5,400 = **90%** because the discount expires. Report these separately so discount expiry is not mistaken for improved client retention.

| Sensitivity, all other base inputs unchanged | Result | Implication |
| --- | --- | --- |
| Core escalation takes 3 rather than 1 hour/client/year | Extra 2 × $80 × 5 = $800; year-one contribution $2,298 − $800 = **$1,498** | Partner support quality and product reliability materially affect margin. |
| Productive conversion halves to 2.5% with the same $6,000 batch spend | Acquisition $6,000 / 2.5 = $2,400; year-one contribution **$1,098** | Acquisition cost rises by $1,200 per productive partner. |
| Both changes occur | $2,298 − $800 − $1,200 = **$298** | Little remains for fixed costs; pause expansion and repair the model. |
| Partner retention 75%, conditional client retention 80% | Year-two clients 5 × 0.75 × 0.80 = 3; fees $3,600; cost 3 × $180 + $300 × 0.75 = $765; contribution **$2,835** | Support continuity protects clients but does not guarantee Clef fee retention. |
| Partner brings only one new client | **−$1,462** in year one | The introductory client alone does not justify assumed acquisition effort. |

Illustrative fixed program budget: **$24,000/year** ($12,000 legal/accounting, $8,000 shared operations, $4,000 shared tooling) plus **$12,000 one-time launch preparation** ($6,000 agreement work, $6,000 lifecycle implementation). These are budget placeholders, not approved spend. Shared tooling is separate from the $24/client allocation; shared operations exclude the client/partner labor counted above. Core-product engineering and general company overhead remain excluded and must be added before claiming company profitability.

At full renewal and five clients per partner, recurring program break-even = $24,000 / $4,800 = **5 partners / 25 clients**, with zero cushion and no churn. In an all-new first year including launch preparation: `ceil(($24,000 + $12,000) / $2,298) = 16` five-client partners, or **80 clients**. Fees = 16 × $5,400 = $86,400; contribution = 16 × $2,298 − $36,000 = **$768**. These are distinct steady-state and first-year scenarios, not a growth forecast.

A partner's own illustrative five-client economics: charge $2,000 setup + $150/month support per client, retaining `5 × ($2,000 + 12 × $150) = $19,000`. Assume 12 setup hours and 1 support hour/month per client at the partner's $60/hour cost: `5 × (12 + 12) × $60 = $7,200`. After the fixed Clef fees, $19,000 − $7,200 − $5,400 = **$6,400** before partner overhead, sales effort, and taxes. Full renewal at the same support price gives $9,000 − $3,600 − $6,000 = **−$600**. Support-only renewal breaks even at `($6,000 + $3,600) / (5 × 12) = $160/client/month`, before overhead. Partners must price or recover the annual fee sustainably; retaining service revenue alone does not ensure profitability. These example prices are not requirements or recommended market rates.

## Lifecycle design and data contract

The company standard path is fully autonomous: approved, versioned rules qualify partners, produce a qualification summary, process standard agreements and client orders, reconcile billing, deliver records, and manage renewals and ordinary continuity without a Clef employee reviewing each case. Partner/client acceptance and signatures remain required inputs; Clef's routine actions use the approved contracting authority and templates. Humans handle exceptions. Establishing legal licensing authority, adopting releases, and approving the operating policy are program-level prerequisites, not a repeated human approval queue for standard applications.

This is the inspectable rule specification for the future qualification and commercial lifecycle. It does not claim that partner qualification, billing, agreement, CRM, or entitlement automation is implemented. The landing site's interest-pack intake and mail delivery have a separate existing implementation, described under retry policies below. Before implementing the remaining lifecycle, select the existing CRM/tracker and billing/agreement systems; keep their records as the single source of truth. Do not use Markdown status files or a second ad hoc customer database as operational state.

Parameterized inputs: program stage (`interest_only` or `commercial_open`), approved rule version, UTC event time, partner/client legal IDs, verified identity references, agreement IDs/hashes and signer evidence, release/revision/license schedule, consent/contact preferences, client control attestation, annual start/end dates, price currency and tax treatment, payment/refund events, support/transfer events, and owner-approved exceptions. Defaults: `interest_only`, proposed writes in dry-run, zero external sends, zero charges, and no grant issuance.

Minimum future system records:

| Record | Required fields and validation |
| --- | --- |
| Partner | Stable legal identity, verified business-identity/contact evidence, versioned scope acceptance, objective capability-check results, qualification summary, agreement version/status, first-client discount state and order reference; identity cannot be reset by contact changes. |
| Client service order | Single client legal identity, partner ID, signed scope and consent, client-owned infrastructure attestation, immutable covered-release references, term dates, USD amount and tax fields, invoice/payment references, and transfer lineage. |
| Release approval | Licensor legal identity, copyright/contribution authority evidence, dependency review, final license text hash, release/revision/source location, and named human approvals. No moving branch reference as the covered revision. |
| Lifecycle event | Unique source event ID, entity/order ID, expected previous state/version, rule version, UTC timestamp, decision/reason, actor, and evidence references. Corrections append; they do not erase history. |
| Exception | Trigger, affected record IDs, evidence, proposed action, accountable owner, deadline, decision, and any rule-change candidate. Stored in the chosen tracker. |

Store only necessary commercial metadata and evidence references, not catalog contents, music contracts, passwords, or signing keys. Confirm retention, deletion, data access, and legal requirements before live collection. Interest capture needs only contact/company, intended client count and scope, and permission to follow up; defer full client identities and legal documents until qualification. Withdrawal suppresses follow-up; deletion follows the approved retention policy.

Outputs per event: one validated state decision (`apply`, `hold`, or `no_op`), a reason code, an append-only audit event when appropriate, and either a proposed invoice/message/entitlement record or a tracker exception. Effectful output requires approved live configuration, authorized scope, and all transition gates. An entitlement record is documentary proof of a service grant, never a node activation token.

## Automated qualification and summary

Apply the following versioned checks deterministically. All required checks must return `pass`; unknown, contradictory, unsupported, expired, or failed evidence cannot be converted into a pass by an AI summary.

| Check | Required evidence and automatic decision |
| --- | --- |
| Business identity | Match legal name, registration identifier/jurisdiction, and active status against a supported authoritative business registry or approved identity-verification provider. Record source, timestamp, and result. Unsupported entity types or conflicting matches go to an exception; a typed company name is a self-declaration. |
| Contact | Complete a single-use contact verification challenge and the approved check linking the contact to the verified business, such as a business-domain control challenge or verified provider association. Email syntax or an email provider's acceptance of a message does not verify the person or their authority. Missing association goes to an exception. |
| Standard scope | Record acceptance of the exact installation/support scope version: client-owned infrastructure and control, partner-owned support and handover, published fee schedule, and separate hosted/OEM terms. Changed terms or hosted/OEM requests route to exceptions; ordinary acceptance needs no Clef human review. |
| Deployment and capability | Validate a versioned synthetic deployment report against required machine-checkable results: approved revision/source and notices, successful deployment/health and TLS checks, backup restoration with matching synthetic data, and delegated-access revocation while the test client retains owner access. Bind results to the application, fresh challenge, report digest, and supported runner provenance. Missing checks, failed results, or unrecognized evidence go to an exception. Do not run qualification probes against an unconsenting live client. |
| Client evidence classification | Record proposed client counts, mandates, infrastructure ownership, and references as `self_declared` when supplied by the applicant/client. Record independently verified identity and measured test results separately. A declaration is not an independently verified deployment, certification, or proof of music-rights authority; client-specific acceptance and control checks remain later order requirements. |

On all passes, automatically set `qualified` and generate a fixed-template summary containing the partner legal ID, contact-verification status, scope version, each check's result, evidence source/class/date, deployment report reference, qualification rule version, remaining client/legal/release gates, and current program stage. No human sign-off or qualification call is required. The summary states **qualified for standard program fit**, with client assertions explicitly labeled **self-declared**; it grants no certification, endorsement, software license, or music permission. During `interest_only`, a qualified applicant remains an interested prospect with no paid enrollment or entitlement.

On an exception, generate the same summary with `held` or separate-scope routing, the failed check/reason, and the accountable exception owner. Standard machine-verifiable missing inputs may be requested automatically through approved templates; conflicting facts, nonstandard terms, and unsupported evidence require human resolution. Qualification summaries use deterministic fields and wording, so an LLM cannot silently upgrade the evidence class or change the decision.

## States and deterministic transitions

Partner qualification and each client's annual service order have separate states; expiry of one order must not expire the partner's other clients. Use transactional uniqueness for client/term coverage and partner introductory allocation, optimistic state-version checks, and idempotency keyed by source system/event ID. A replay must not create another charge, discount, email, or grant. Reconcile payment events with the authoritative billing provider; an unverified webhook or out-of-order event cannot move an order backward or issue a grant.

While a partner's first-order discount reservation is unresolved, hold later client invoices so a full-price order cannot become its first paid client accidentally. Operations may void an abandoned unpaid order and release its reservation before selecting another first order; a paid or disputed order requires reviewed refund/correction handling. Resolve the reservation from billing evidence, never an elapsed-time guess.

| Event / state | Checks | Deterministic result and owner |
| --- | --- | --- |
| Interest received / new | Approved intake, consent, duplicate contact/company check | Record `interested`; queue approved acknowledgment automatically. Exact duplicates are idempotent; conflicting identity records go to Operations as exceptions. Commercial artifacts remain disabled. |
| Stage remains `interest_only` / any | Global stage checked before every commercial side effect | Hold invoices, payment collection, paid enrollment, and entitlement issuance even if a record says qualified or paid. Founder owns changing stage. |
| Qualification / interested | Verified business identity/contact, standard scope acceptance, objective deployment/capability checks, and explicit classification of self-declared client evidence | All checks pass → automatically `qualified` with the fixed-template summary; no Clef human review. Hosted/OEM → separate queue; failed/unknown/conflicting checks → exception. Qualification grants no certification or entitlement. |
| Program opening | Legal licensor and signer identity, authority/contribution review, final agreements, designated releases, production/release gates, approved billing/support/privacy process | Founder and legal owner record approval before `commercial_open`; automation cannot approve these gates. Commercial opening also requires explicit approval of outbound templates/channels and any payment integration. |
| Partner agreement / qualified | Machine-validated signature evidence, signer authority requirements in the approved policy, unchanged standard version/scope, completed legal/release gates | Automatically record `contracted` under the approved contracting workflow; no Clef case-by-case approval. Unsupported signer evidence or changed terms → exception. No client entitlement exists yet. |
| Client order / contracted partner | Verified client identity, client acceptance/access authorization, client control, release coverage, no duplicate/overlapping term | Create `order_ready`; reserve first-client discount atomically if eligible. USD price is $600 only for that reservation, otherwise $1,200. |
| Invoice / order_ready | Client order passing approved rules, partner billing authorization, tax fields validated by supported tax rules/provider | Automatically issue one annual invoice through the chosen billing system; `awaiting_payment`. Unsupported tax treatment → exception. Live effect only after commercial opening. |
| Payment and start / awaiting_payment | Verified cleared payment, agreed start reached, agreement and release gates still valid | Record `in_term`, consume discount reservation once, deliver service entitlement and handover checklist. Future-dated payment waits for its start. No runtime activation. |
| Installation handover / in_term | Partner submits client owner-access confirmation, source/revision/notices, backup/restore evidence, recovery contacts | Record delivery acceptance or open a support exception. The annual term follows the signed order, not a runtime callback. |
| Renewal / 60, 30, 7 days before end | Valid contact consent, order still open, renewal not already decided | Queue approved reminders; renewed order requires affirmative confirmation. Price $1,200. Cancel scheduled reminders once renewed or declined. |
| Unpaid renewal / term end | No verified renewal for next period | Mark only that order `expired`; stop ordinary partner service rights for it and enter 30-day handover. Never disable the node or its music/data records. |
| Transfer / in_term or transition | Client consent, replacement grant, outgoing term/payment, identity and security review | Hold for human approval; append transfer/credit record and preserve remaining paid client period. No automatic second fee or new introductory benefit. |
| Termination / any paid order | Named human decision under final agreement; client continuity and incident plan | End service rights as decided; allow only contractually permitted transition, then `closed`. Customer own-node rights remain independently governed. |
| End of transition | Handover evidence, credential revocation, retention/deletion obligations | Close partner service access; client may self-support or use an authorized replacement. Incomplete handover becomes a human exception, not remote deactivation. |

Schedule dates using each signed annual anniversary in UTC and an explicit end-exclusive interval. For a February 29 start, use February 28 in non-leap renewal years unless the agreement specifies otherwise. Renewal continues the preceding period's endpoint without gaps or overlap. Money uses integer USD cents: `120000` standard and `60000` introductory. Counters count legal client organizations, not seats, catalogs, requests, royalties, or node instances. Price changes require a new approved schedule and applicable agreement; automation never invents discounts.

## Exceptions, review thresholds, and improvement

| Trigger | Response / accountable owner |
| --- | --- |
| Missing licensor identity, signer authority, contribution permission, or covered release; obsolete terms | Hold commercial transition; legal/release owner resolves with evidence. AI cannot establish these facts. |
| Hosted/OEM scope, partner-controlled infrastructure, nominal rights mandate, unauthorized subcontractor | Hold order; commercial/legal owner evaluates separate terms or corrected client control. |
| Conflicting entity matches, disputed discount, transfer, merger, refund, payment mismatch, or event replay conflict | Billing owner reviews the exception; freeze affected write, preserve unrelated orders, reconcile source records. Exact duplicates are a safe `no_op`; concurrent standard first orders use atomic reservation without a human approval. |
| Client lacks owner access/restore capability, partner exit, security incident, key exposure, or inability to export | Immediate human operations/security triage and continuity procedure. Never put secrets into the exception record or wait for billing resolution to restore client control. |
| Core escalation exceeds 2 hours/client in a rolling year, repeated same defect across 3 clients, or reproducible data-integrity issue | Product owner reviews cause, documentation/product fixes, and any separately scoped service. The threshold is internal, not a promised SLA or automatic support denial. |
| Mature productive partners average fewer than 3 paid clients by month 12; acquisition exceeds $1,800/productive partner; or combined stress leaves contribution below $500/partner | Founder reviews acquisition spend, enablement and pricing assumptions before expanding recruitment. Do not silently change existing prices or terms. |
| Measured annual partner or conditional client retention below 80%, or exit reason cites lock-in/support failure | Founder and operations review cohorts and handovers. With fewer than 10 renewal-eligible partners, review every exit rather than claiming a stable retention estimate. |
| Novel case or unavailable required system | `hold`, retry transient failures with bounded backoff, then create one exception with an owner. Never infer approval from timeout or missing data. |

### Retry policies: current pack delivery versus future billing

The landing operations companion is `clef-pro-landing/docs/PARTNER_OPERATIONS.md`. That file was unavailable in this checkout during this correction; the current pack behavior below is verified against the existing [delivery implementation](../../../clef-pro-landing/server/partner/delivery.mjs), [scheduled worker](../../../clef-pro-landing/netlify/functions/partner-delivery-retry.mjs), and [delivery tests](../../../clef-pro-landing/scripts/test-partner-delivery.mjs). This design does not replace the pack's implementation or claim that it is deployed/enabled.

| Workflow | Retry policy and boundary |
| --- | --- |
| Current interest-pack mail delivery, implemented | At most **10 total attempts including the first**, within **23 hours of the first attempt**. Retry delay is the greater of exponential backoff (1, 2, 4, 8… minutes) and provider `Retry-After`, plus deterministic jitter below 15 seconds. The worker is scheduled every minute, subject to delivery gates/rate limits. The persisted request body and idempotency key remain identical on retries. Exhaustion or a next retry outside the safe window produces `manual_review`; terminal provider failures stop immediately. Intake also has a separate 7-day expiry; it does not extend the 23-hour retry window. Mail-provider acceptance records acceptance, not inbox delivery, contact verification, or partner qualification. |
| Future billing/invoice transport, proposed only | After the initial request, allow up to **3 retries**, waiting **1, 5, and 30 minutes respectively** after successive failures (**4 total attempts maximum**), only for transient failures. Respect a longer provider `Retry-After` within its documented idempotency window; otherwise hold for an exception. This proposal covers idempotent billing API transport, not mail delivery, collection of overdue money, card-decline retries, or a new charge authorization. Finalize against the selected provider before implementation. |

For future billing, verify authoritative provider state after an uncertain write before retrying. Keep the same request and idempotency key; hold an unresolved outcome instead of creating a new charge. The applicable workflow owns its outbox, attempt count, and retry window; never apply the proposed billing schedule to existing pack jobs. Legal holds never auto-retry into approval. The business ledger and partner/client contracts remain authoritative when infrastructure is unavailable; no outage disables a node.

Runtime AI is optional for summarizing a novel exception or proposing a rule improvement. It returns: immediate result or abstention, failed deterministic rule, rationale and confidence, proposed rule/schema change, minimal regression case and expected outcome, evidence reference, and required human approver. It cannot sign, issue grants, change fees, resolve legal authority, or send messages on its own. Human/legal review as applicable and replay of accepted cases precede any versioned rule promotion. Retain candidates and decisions in the existing tracker; do not create Markdown control logs.

Automated monthly operating reports use actual collected fees, refunds, unique paid clients, active partners, discount use, automation costs, exception/maintenance hours by acquisition/onboarding/support, and exceptions. Measure partner conversion with a dated prospect denominator; productivity by months since first paid client; client retention conditional on partner retention; transfers separately from lost revenue; contribution after actual processing and labor costs. Cohort dashboards reconcile to billing and never count expressions of interest as customers or revenue. Humans receive threshold breaches and unresolved exceptions; standard reports do not create a recurring human approval gate.

## Acceptance cases for future implementation

These are executable-test requirements for the future lifecycle implementation, not claims that an automation has passed them. The doc-only release can verify policy consistency and arithmetic now. Before live operation, implement replayable fixtures against the selected systems in dry-run and exercise these cases without charging or sending:

| Input case | Required result |
| --- | --- |
| Verified business identity/contact, unchanged standard scope, all objective capability checks pass | Automatically `qualified` and generate the evidence-classified summary; zero Clef human approvals or mandatory calls. |
| Only a business name/email string, mail-provider acceptance, or a self-declared client success story | Insufficient for verified identity/contact or objective capability; request supported inputs or hold the exception. Never mark as certified. |
| Passing test deployment plus self-declared client count/mandate | Summary distinguishes measured test results from client assertions; no inference of production readiness or music authority. |
| Standard commercial agreement, client order, invoice, payment, and renewal meet the approved policy | Complete the standard lifecycle autonomously after program gates; humans see only exceptions. |
| `interest_only`, qualified partner, even with a stray payment event | Interest/exception record only; zero invoice, enrollment, grant, or outbound commercial promise. |
| Current AGPL release with no commercial grant request | No new fee or restriction inferred; route to its existing license. |
| Commercial stage but one legal/release gate missing | `hold`; zero invoice/grant. |
| Verified partner's first paid client followed by a second client | First year $600 then $1,200; renewal of each $1,200. |
| Two simultaneous first-client orders | Exactly one $600 reservation; no second discount on retries. |
| One client with five operational/test/backup instances and 100 represented artists | One client annual fee; no seat/catalog/instance charge. |
| Two separate client legal entities in one corporate group | Two scoped orders; no affiliate exemption inferred. |
| Duplicate payment callback or out-of-order refund/payment | No duplicate invoice/grant; reconcile uncertain billing state and hold disputes. |
| Renewal declined or unpaid; partner exits | Client keeps running; outgoing service limited to 30-day transition; no key/data lock. |
| Approved transfer halfway through a paid term | Preserve client term without duplicate fee; retain original discount history; replacement's next renewal $1,200. |
| Partner-owned hosting/OEM request | Separate commercial queue; no installation-plan grant or price quote. |
| Missing client owner access, unknown release, failed restore, or novel entity structure | Human exception with evidence; no silent acceptance. |
| Withdrawn follow-up consent, repeated scheduled event, or February 29 anniversary | Suppress disallowed contact; one intended effect; explicit consistent term date. |
| Current pack reaches attempt 10 or its 23-hour safe window | Use existing `manual_review` behavior and identical persisted request; never substitute the future billing retry schedule. |
| Future billing initial request plus 3 transient retries remains unresolved | Reconcile provider state and hold one exception after at most 4 attempts; never issue a fresh duplicate charge. |

Interest-stage exit criteria: evidence of relevant partner demand and plausible client counts, understood support capability and client-control requirements, reviewed unit economics using measured effort where available, and explicit founder decision to pursue commercial launch. These findings inform the decision; only completed legal, licensing-authority, release, agreement, and operational gates can authorize paid operation.
