# Connected catalog discovery

## Claim ledger — 18 September 2026

- **Central claim:** an organization can explicitly publish selected catalog fields, and authenticated buyers can search those fields across independently operated, configured nodes while preserving source identity and current publication status.
- **Evidence:** `backend/tests/test_federation.py`, the rendered `ConnectedCatalogs.test.tsx` tests, and `scripts/run_federation_preview.py --verify`. The live verifier runs two separate APIs, databases, signers and web proxies; it exercises withdrawal, policy changes and an unavailable peer.
- **Scope:** this working candidate implements a configured-peer discovery protocol. Operators establish peer identity and keys out of band. Publication requires an organization administrator and verified authority. The originating organization administers permission requests and license decisions.
- **Falsifier:** an unpublished or withdrawn entry appears in a new source response; another tenant can publish it; a changed policy remains advertised under stale consent; private evidence travels in a search result; a forged or expired remote statement passes; or an unavailable peer is reported as a complete search.
- **Why it matters:** labels and publishers can make their catalogs discoverable while retaining control over the public fields, source records and licensing decisions.

Previous capability: discovery queried the current node's authenticated authority directory.

Current capability: authenticated discovery queries the current node's explicitly published entries and up to eight independently configured peers, verifying each remote response against its pinned key.

This expands the demonstrated capability. The current released alpha and public deployments retain their own release boundaries; enablement and deployment of this candidate require the operator's release review.

## The administrator's flow

1. Supply a catalog policy and complete the node operator's authority review.
2. Open **Connected catalogs**, choose the catalog entry, and select **Preview public fields**.
3. Review the organization name, artist and title, catalog references, represented right and territory, policy version, and enumerated use conditions. Confirm authority to publish this exact projection.
4. Clef compares the preview digest with the current policy, authority evidence and publication revision before recording consent.
5. The entry becomes available through public source search. Authenticated local users and API credentials with `directory:read` can search the configured network.
6. A policy or authority change suspends that publication until a new review. **Withdraw publication** removes it from subsequent searches and clears this node's stored public projection; its consent digest and audit event remain.

The administration list is paginated. **Load more publications** reaches earlier entries; API clients follow `nextCursor` on `GET /v1/organizations/{org_id}/catalog/publications`, with a page size up to 200. Cursors are scoped to the organization.

The publication exposes the fields shown in the preview. Agreements, private evidence, contact records, free-form contract metadata and commercial terms remain behind existing organization and party access controls. Catalog identifiers are organization-supplied references; their appearance together records that organization's published connection.

An already distributed public statement remains with its recipient. Statements expire within 60 seconds, and each new search rechecks the source. Operators handle retained private catalog records through their retention and erasure procedures. Publication withdrawal clears the distributed projection at this node; it leaves the underlying catalog, policy, mandate and audit records available to their authorized administrators.

## Discovery and licensing

Search advertises declared use conditions. The originating node checks an actual request against current authority, territorial scope, policy and agreed obligations. Buyers authenticate separately when making a request to that organization. Federation search sends only a query, nonce and result limit to peers; the buyer's session, API credentials, private evidence and requested commercial terms stay at the requesting node.

This candidate's console supports search, source inspection, consent and withdrawal. Cross-node request submission, agreement negotiation, payment, automatic peer enrollment, recursive peer discovery and a worldwide catalog index are subsequent capabilities. The controlled local example uses fictional data throughout.

## Protocol and trust

`POST /v1/federation/catalog/search` accepts `{query, nonce, limit}` and returns a signed `clef.catalog-discovery.v1` statement. The payload contains its source `nodeId` and canonical `origin`, the exact query and nonce, issue and expiry times, a truncation flag, and the approved entries.

The Ed25519 proof uses `CLEF-CANONICAL-JSON-1`. It signs a discovery statement separately from permission receipts and the transparency ledger. A receiver checks the configured peer's public key, key identifier, node identifier and origin; signature and payload hash; query and nonce; strict public-field vocabulary; maximum lifetime; and result count. A downloadable statement preserves that source evidence for inspection.

`POST /v1/federation/search` requires a session or a `directory:read` credential. It returns per-source status, separate source statements, attributed results, and explicit `partial` and `truncated` flags. Queries stay in POST bodies and are not added to the audit log or browser analytics. A deployment's own reverse proxy and observability configuration must apply its query-retention policy.

Peer trust is an operator decision. Verify the peer identity and key through a channel controlled by the organization before configuration. Key rotation requires updating the pin after the same verification; a mismatched key makes that peer unavailable until corrected. A valid signature establishes the source of the statement. The organization and its operator remain responsible for the supplied catalog and authority evidence.

## Network and resource boundaries

- Maximum eight configured peers. Search input: 2–200 printable characters; 1–50 entries requested per source.
- Each source examines at most 200 matching publication candidates and reports truncation when that window or the requested result count is exceeded. Refine the search by identifier or organization for larger catalogs.
- Complete signed envelopes fit a 262,144-byte UTF-8 budget, including long multibyte names. Sources truncate before signing the final response; receivers reject oversized or ambiguous JSON.
- Three-second peer transport deadline and bounded worker capacity. An outstanding timed-out DNS/socket worker keeps its capacity slot until it exits, preventing an accumulating background queue.
- HTTPS origins, validated DNS answers, pinned socket destinations and hostname-verified TLS. Redirects, proxies, caller credentials and compressed responses are excluded from transport.
- Private, loopback, link-local and special-purpose destinations are rejected. A separate development/test switch permits literal `127.0.0.1` or `::1` for the local proof. Production and staging reject that switch.
- Responses use `Cache-Control: no-store`. Failed peers contribute a status and no cached catalog fallback. The interface marks statements expired and asks for a new search.

## Configuration

Federation is disabled by default. Apply `alembic upgrade head` (currently `0020_catalog_review_basis`; publication consent was introduced in `0019_catalog_federation`), use a persistent signing key, and configure:

```dotenv
FEDERATION_ENABLED=true
FEDERATION_PUBLIC_ORIGIN=https://rights.example.org
FEDERATION_ALLOW_LOOPBACK=false
FEDERATION_PEERS_JSON=[{"id":"publisher","origin":"https://rights.publisher.example","nodeId":"urn:publisher:node","publicKey":"REPLACE_WITH_VERIFIED_BASE64URL_PUBLIC_KEY"}]
```

The origins must serve the source search route through their normal HTTPS proxy. Configure at most eight distinct peer node IDs and origins, excluding this node. The peer ID `local` is reserved for the current node. Public keys use the unpadded base64url encoding of 32 Ed25519 bytes. They are public identifiers; keep signing private keys in the node's secret store. Invalid enabled configuration fails startup.

Restart the API after changing peer configuration. Enable the feature only after reviewing publication responsibility, peer identities, public fields, source availability and operational ownership. Existing source and software license disclosures remain required.

## Reproduce the local proof

Install the repository's Python and frontend dependencies, then run:

```bash
.venv/bin/python scripts/run_federation_preview.py
```

The label console opens on `http://127.0.0.1:16484`; the publisher console runs on `16485`. Each has a separate database, signing key, API and explicitly published fictional catalog. Choose **Explore the example catalog**, then **Search connected catalogs**, and search **Paper Skies** or **ZZDEM2600001**. This cross-node fixture is distinct from the guest's private request-and-approval walkthrough.

The launcher retains private state in `~/.cache/clef/federation-preview`, isolates environment credentials, disables external providers and email, and binds every server to loopback. A designated fictional operator uses local development sign-in links to seed and resume the catalogs through ordinary API authorization. Guest reviewers have separate accounts and examples. Ctrl-C stops both nodes; rerunning preserves catalog edits and publication choices.

For the deterministic failure proof, select a fresh private directory:

```bash
.venv/bin/python scripts/run_federation_preview.py --state-dir /tmp/clef-federation-proof --verify
```

The verifier records a compact `proof.json`, exits nonzero on a failed assertion, and stops its servers. It refuses an existing database in verification mode. Preserve failed synthetic state for investigation, reproduce the failure as a regression test, and validate a code change before rerunning against a fresh directory.
