# Connected catalogs: discovery, requests and public terms

## Claim ledger — 1 November 2026

- **Central claim:** an organization can explicitly publish selected catalog fields. Anyone can read those published terms from the source node without an account. A requester on a configured peer node can submit a permission request through its own node, and it receives the source node's decision, which carries a receipt that verifies against the source's pinned key. The source node decides under its own policy and reviewers.
- **Evidence:** `backend/tests/test_federated_requests.py`, `backend/tests/test_federation.py`, `backend/tests/test_federation_hardening.py`, the rendered `ConnectedCatalogs.test.tsx` tests, and `scripts/run_federation_preview.py --verify`. The live verifier runs two separate APIs, databases, signers and web proxies. It sends a signed cross-node request, records the source's human approval, verifies the returned receipt on the requesting node, replays the request, refuses an impostor signature, reads the public terms and node descriptor without an account, and exercises withdrawal, policy changes and an unavailable peer. `scripts/verify_hosted_federation.py` runs the same request proof against two HTTPS deployments; it has been rehearsed locally and has not yet run against hosted nodes.
- **Scope:** configured peers only. Operators establish peer identity and keys out of band, and each node accepts requests from the peers it pins. The originating organization's reviewers decide requests; negotiation, payment and agreement exchange across nodes are absent. Published terms are readable by anyone, and nothing forces a crawler or model operator to read or honor them.
- **Falsifier:** an unpublished or withdrawn entry appears in a new source response or accepts a new request; another tenant can publish it; a changed policy remains advertised under stale consent; private evidence travels in a search result or public terms; a forged, expired or unpinned statement passes; a replayed request creates a second permission request; a requesting node accepts a receipt signed by a key other than the source's pin; or an unavailable peer is reported as a complete search.
- **Why it matters:** an AI company or producer can ask a label or publisher on another node for terms through its own node, and both sides keep a verifiable record of what was asked and what was decided.

Previous thesis (18 September 2026): "an organization can explicitly publish selected catalog fields, and authenticated buyers can search those fields across independently operated, configured nodes while preserving source identity and current publication status."

Current thesis (1 November 2026): the sentence under **Central claim** above.

This expands the demonstrated capability: requests now cross nodes, and published terms have an account-free reading path. The previous claim is preserved in full. The current released alpha and public deployments retain their own release boundaries; enablement and deployment require the operator's release review.

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

Search advertises declared use conditions. The originating node checks an actual request against current authority, territorial scope, policy and agreed obligations. Federation search sends only a query, nonce and result limit to peers; the buyer's session, API credentials, private evidence and requested commercial terms stay at the requesting node.

**Request terms** on a search result sends a permission request through the requester's own node:

1. The requester chooses one of its organizations, the intended use, territory, license term, content categories and, for AI uses, the declared inputs, model environment, durations, retention and accepted controls. These are the same declarations a local request requires.
2. The requesting node signs a `clef.permission-request.v1` statement naming itself, the source node, the requesting organization, the publication and the declared scope, and sends it to the source node. It stores the signed request before sending, so an interrupted delivery stays visible.
3. The source node accepts only a statement signed with a configured peer's pinned key, naming that peer's origin and this node, within a five-minute window. It rechecks that the publication is still current, then evaluates and records the request exactly as it would a local one. The requesting organization is represented there by a member-less requester organization tied to the peer node.
4. A use the published policy allows is approved and receipted immediately. Anything else waits for the source's reviewer.
5. The requesting node shows the source's answer. A rate limit, timeout or source-side conflict leaves the request unconfirmed and retryable; a refusal such as an unpublished entry is recorded as not accepted. **Refresh status** asks the source again with a signed `clef.permission-status-query.v1`; the answer is a signed `clef.permission-status.v1` statement carrying the decision, note and every grant or lifecycle receipt. The requesting node verifies each receipt against the source's pinned key before recording the status.

A status carries the newest 20 grant and lifecycle receipts and reports how many older ones it omitted. A signed request or status query works as a bearer credential for that request's status until it expires five minutes after signing: whoever holds it can replay it to the source and read the status and receipts. Both travel only between the two nodes over TLS and to the requesting organization's own members.

Requests for this node's own entries go to the ordinary local permission ledger. A rejection reaches the requester as a signed status statement; this node's transparency chain records grants and lifecycle changes. Agreement negotiation, payment, automatic peer enrollment, recursive peer discovery and a worldwide catalog index are subsequent capabilities. The controlled local example uses fictional data throughout.

## Public terms

Anyone can read a current publication's terms without an account:

- `GET /v1/public/catalog/publications/{publicationId}` returns a signed `clef.catalog-terms.v1` statement with the same public fields as search, plus where requests are accepted. A withdrawn or stale publication returns 404.
- `POST /v1/federation/catalog/search` returns a signed `clef.catalog-discovery.v1` statement for a query and caller-chosen nonce.
- `GET /.well-known/clef-node` returns the signed `clef.node-descriptor.v1`: node ID, origin, current and announced next signing keys, supported statement types and endpoint paths.

Public responses carry `Link: </.well-known/clef-node>; rel="describedby"`. Publishing terms states them; reading or honoring them is the reader's choice.

## Protocol and trust

`POST /v1/federation/catalog/search` accepts `{query, nonce, limit}` and returns a signed `clef.catalog-discovery.v1` statement. The payload contains its source `nodeId` and canonical `origin`, the exact query and nonce, issue and expiry times, a truncation flag, and the approved entries.

The Ed25519 proof uses `CLEF-CANONICAL-JSON-1`. It signs a discovery statement separately from permission receipts and the transparency ledger. A receiver checks the configured peer's public key, key identifier, node identifier and origin; signature and payload hash; query and nonce; strict public-field vocabulary; maximum lifetime; and result count. A downloadable statement preserves that source evidence for inspection.

`POST /v1/federation/search` requires a session or a `directory:read` credential. It returns per-source status, separate source statements, attributed results, and explicit `partial` and `truncated` flags. Queries stay in POST bodies and are not added to the audit log or browser analytics. A deployment's own reverse proxy and observability configuration must apply its query-retention policy.

Every signed statement names its `schemaVersion`, and each verifier accepts exactly one schema with a closed field set, so a signature over one statement type never verifies as another. Published policy limits are whole numbers, which serialize identically in every JSON canonicalization a peer implementation may use.

Peer trust is an operator decision. Verify the peer identity and key through a channel controlled by the organization before configuration. `scripts/federation_peer.py https://peer.example --id publisher --expect-key-id ed25519:…` fetches the peer's descriptor, refuses it unless its current key matches the key ID you verified, and prints the configuration entry.

To rotate a node's key without an outage, set `NODE_NEXT_SIGNING_PUBLIC_KEY_B64`. The descriptor announces it, and peers add it as `nextPublicKey`, after which they accept either key. Switch the signing key, then peers move it to `publicKey` and the old key to `retiredPublicKeys`; the rotating node lists its old key in `NODE_RETIRED_SIGNING_PUBLIC_KEYS_B64`. Retired keys verify receipts issued before the rotation and are never accepted on a new statement. A key that matches no pin makes that peer unavailable until corrected. `scripts/federation_peer.py` derives the key ID from the public key itself, so a descriptor cannot claim another key's ID.

`POST /v1/receipts/verify` reports `valid` only when the signature checks and the signer is this node or a configured peer, matched by key and node ID; `signer` names which. A self-consistent receipt from an unknown key returns `signatureValid: true` and `valid: false`.

A valid signature establishes the source of the statement. The organization and its operator remain responsible for the supplied catalog and authority evidence.

## Network and resource boundaries

- Maximum eight configured peers. Search input: 2–200 printable characters, excluding control, invisible formatting, bidirectional-override, private-use and unassigned characters; 1–50 entries requested per source.
- Each source examines at most 200 matching publication candidates and reports truncation when that window or the requested result count is exceeded. Refine the search by identifier or organization for larger catalogs.
- Complete signed envelopes fit a 262,144-byte UTF-8 budget, including long multibyte names. Sources truncate before signing the final response; receivers reject oversized or ambiguous JSON.
- A total transport deadline of three seconds for search and ten for requests, enforced by closing the socket, so a peer that drips bytes cannot hold a worker. Each peer has at most four concurrent exchanges within a node-wide pool of 32, so one slow peer leaves capacity for the others. A DNS lookup cannot be interrupted; its worker keeps its slot until the lookup returns.
- Signed requests are limited to 64 KiB. A request ID is single-use per peer: an identical redelivery returns the original record, and a different statement under the same ID is refused.
- HTTPS origins, validated DNS answers, pinned socket destinations and hostname-verified TLS. Redirects, proxies, caller credentials and compressed responses are excluded from transport.
- Private, loopback, link-local, multicast and special-purpose destinations are rejected. A separate development/test switch permits literal `127.0.0.1` or `::1` for the local proof. Production and staging reject that switch.
- Responses use `Cache-Control: no-store`. Failed peers contribute a status and no cached catalog fallback. The interface marks statements expired and asks for a new search.

## Configuration

Federation is disabled by default. Apply `alembic upgrade head` (currently `0021_federated_requests`; publication consent was introduced in `0019_catalog_federation`), use a persistent signing key, and configure:

```dotenv
FEDERATION_ENABLED=true
FEDERATION_PUBLIC_ORIGIN=https://rights.example.org
FEDERATION_ALLOW_LOOPBACK=false
FEDERATION_PEERS_JSON=[{"id":"publisher","origin":"https://rights.publisher.example","nodeId":"urn:publisher:node","publicKey":"REPLACE_WITH_VERIFIED_BASE64URL_PUBLIC_KEY"}]
```

The origins must serve `/v1/federation/catalog/search`, `/v1/federation/inbound/`, `/v1/public/catalog/` and `/.well-known/clef-node` at the origin itself. The shipped web image's nginx template routes exactly these paths to the API alongside `/api/`; `make verify-deployment` checks it. Configure at most eight distinct peer node IDs and origins, excluding this node. The peer ID `local` is reserved for the current node. Public keys use the unpadded base64url encoding of 32 Ed25519 bytes; an entry may add `nextPublicKey` during a rotation. They are public identifiers; keep signing private keys in the node's secret store. Invalid enabled configuration fails startup.

Restart the API after changing peer configuration. Enable the feature only after reviewing publication responsibility, peer identities, public fields, source availability and operational ownership. Existing source and software license disclosures remain required.

## Reproduce the local proof

Install the repository's Python and frontend dependencies, then run:

```bash
.venv/bin/python scripts/run_federation_preview.py
```

The label console opens on `http://127.0.0.1:16484`; the publisher console runs on `16485`. Each has a separate database, signing key, API and explicitly published fictional catalog. Choose **Explore the example catalog**, then **Search connected catalogs**, and search **Paper Skies** or **ZZDEM2600001**. This cross-node fixture is distinct from the guest's private request-and-approval walkthrough. A requester organization on the label node can choose **Request terms** on the publisher's composition entry; the publisher console's permission ledger then shows the request for review.

The launcher retains private state in `~/.cache/clef/federation-preview`, isolates environment credentials, disables external providers and email, and binds every server to loopback. A designated fictional operator uses local development sign-in links to seed and resume the catalogs through ordinary API authorization. Guest reviewers have separate accounts and examples. Ctrl-C stops both nodes; rerunning preserves catalog edits and publication choices.

For the deterministic failure proof, select a fresh private directory:

```bash
.venv/bin/python scripts/run_federation_preview.py --state-dir /tmp/clef-federation-proof --verify
```

The verifier records a compact `proof.json`, exits nonzero on a failed assertion, and stops its servers. It refuses an existing database in verification mode. Preserve failed synthetic state for investigation, reproduce the failure as a regression test, and validate a code change before rerunning against a fresh directory.

## Hosted proof

`scripts/verify_hosted_federation.py` runs the request proof against two staging deployments over HTTPS: discovery, a signed cross-node request, the source's human decision, receipt verification against the pinned key, replay and impostor refusal, public terms and the descriptor, and withdrawal with renewed consent. It seeds the same clearly labelled fictional catalog. Each node needs federation enabled, the other node pinned as a peer, and the shipped web image (or an equivalent proxy for the four origin paths above). Sign in to each console as its operator and supply the session IDs through `CLEF_LABEL_SESSION` and `CLEF_PUBLISHER_SESSION`; the script never prints them.

```bash
.venv/bin/python scripts/verify_hosted_federation.py \
  --label-origin https://label.example.org --publisher-origin https://publisher.example.org \
  --label-key <pinned label key> --publisher-key <pinned publisher key> --output hosted-proof.json
```

`--allow-loopback` rehearses the same script against the local two-node preview before a hosted run.

Before hosting, decide how the API learns client addresses. Rate limits key on the address the API sees, and behind the web proxy that is the proxy itself unless the API trusts forwarded headers from it. Left as is, all public traffic shares one limit: anonymous reads of the public endpoints can exhaust the allowance peers and sign-ins depend on. Trusting forwarded headers safely depends on the hosting platform's edge proxy, so verify it on the staging deployment.
