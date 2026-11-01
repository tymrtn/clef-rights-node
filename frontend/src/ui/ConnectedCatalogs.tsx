import React from "react";
import { USAGE_CATEGORIES, RESTRICTION_CATEGORIES } from "../types/rights";
import "./ConnectedCatalogs.css";

type PublicEntry = {
  publicationId: string; organization: { id: string; name: string }; authorityClaimId: string;
  workKey: string; workTitle: string; artistName: string; rightType: string; territory: string;
  policyVersion: number; publicationRevision: number; synthetic: boolean;
  catalogReferences: { isrc: string | null; iswc: string | null };
  policy: Record<string, Record<string, string | number | boolean | null>>;
};
type Source = { id: string; nodeId: string; origin: string; status: string; expiresAt?: number;
  entries: PublicEntry[]; statement?: unknown; truncated?: boolean };
type SearchResult = { query: string; checkedAt: number; partial: boolean; truncated: boolean;
  sources: Source[]; results: { entry: PublicEntry; source: { id: string; nodeId: string; origin: string; expiresAt: number } }[] };
type Publication = { id: string; authorityClaimId: string; revision: number; status: string; publicFields: PublicEntry | Record<string, never> };
type Preview = { publicFields: PublicEntry; previewDigest: string; distribution: string; freshnessSeconds: number };
type Claim = { id: string; workKey: string; rightType: string; territory: string; status: string };

const labels: Record<string, string> = {
  ...Object.fromEntries([...Object.values(USAGE_CATEGORIES), ...Object.values(RESTRICTION_CATEGORIES)].map(category => [category.id, category.title])),
  ai_grounded_generation: "Generation using licensed music", ai_model_training: "Model training",
  ai_model_fine_tuning: "Model fine-tuning", ai_embedding_creation: "Creating embeddings",
  ai_embedding_retrieval: "Retrieving embeddings", ai_source_separation: "Separating stems",
  ai_music_transformation: "AI remixes and transformations", ai_lyric_analysis: "Lyric analysis",
  ai_lyric_generation: "Generating or adapting lyrics", ai_synthetic_voice: "Synthetic voices",
  ai_training_recursive: "Recursive AI training", derivative_remix: "Remixes",
  full_mix: "Full recording", stems: "Supplied stems", isolated_vocals: "Isolated vocals", lyrics: "Lyrics",
  composition_data: "Composition, MIDI or score", reference_embeddings: "Existing embeddings",
  private_single_tenant: "Private model", shared_commercial_model: "Shared commercial model",
  public_or_open_weights: "Public or open-weight model",
  maxSourceDurationSeconds: "Source audio (seconds)", maxOutputDurationSeconds: "Generated audio (seconds)",
  maxLyricCharacters: "Lyric characters", sourceRetentionDays: "Source retention (days)", embeddingRetentionDays: "Embedding retention (days)",
  provenanceReceipt: "Provenance receipt", outputWatermark: "Output watermark", attribution: "Artist credit",
  similarityReview: "Similarity review", deletionAttestation: "Deletion record",
  requires_approval: "Reviewer approval", allowed: "Allowed by policy", blocked: "Blocked",
  denied: "Excluded", conditional: "Conditions apply", master: "Recording rights", composition: "Composition rights",
  usage: "Uses", restrictions: "Content conditions", inputs: "Musical components", modelScopes: "Model access",
  limits: "Duration and retention", safeguards: "Required safeguards", published: "Published",
  needs_review: "Changed · review before sharing", withdrawn: "Withdrawn",
};
const label = (value: string) => labels[value] || value.replace(/_/g, " ");
const errorText = (error: unknown) => error instanceof Error ? error.message : "Please try again.";

function download(value: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function PolicyDetails({ entry }: { entry: PublicEntry }) {
  return <details className="connected-policy"><summary>Artist choices and use conditions</summary>
    <p className="connected-note">Content conditions apply alongside the selected use, musical components, territory and terms.</p>
    <div className="connected-policy-grid">{Object.entries(entry.policy).map(([section, values]) =>
      <section key={section}><h4>{label(section)}</h4><dl>{Object.entries(values).map(([key, value]) =>
        <div key={key}><dt>{label(key)}</dt><dd>{section === "restrictions" && value === "allowed" ? "Use policy applies" : value === null ? "Set in the request" : typeof value === "boolean" ? value ? "Required" : "Optional" : typeof value === "number" ? value : label(value)}</dd></div>)}</dl></section>)}</div>
  </details>;
}

export function ConnectedCatalogs({ apiBase = "", sessionId, organizationId, canPublish, synthetic = false }: {
  apiBase?: string; sessionId: string; organizationId: string; canPublish: boolean; synthetic?: boolean;
}) {
  const [query, setQuery] = React.useState(synthetic ? "Paper Skies" : "");
  const [result, setResult] = React.useState<SearchResult | null>(null);
  const [searching, setSearching] = React.useState(false);
  const [error, setError] = React.useState("");
  const [publicationError, setPublicationError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [claims, setClaims] = React.useState<Claim[]>([]);
  const [publications, setPublications] = React.useState<Publication[]>([]);
  const [publicationCursor, setPublicationCursor] = React.useState<string | null>(null);
  const [claimId, setClaimId] = React.useState("");
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [confirmed, setConfirmed] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [now, setNow] = React.useState(Date.now());
  const busyRef = React.useRef(false);
  const searchSequence = React.useRef(0);
  const scope = `${sessionId}:${organizationId}`;
  const currentScope = React.useRef(scope); currentScope.current = scope;
  const alive = React.useRef(true);
  const searchAbort = React.useRef<AbortController | null>(null);
  const root = `/v1/organizations/${encodeURIComponent(organizationId)}/catalog/publications`;

  async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const response = await fetch(`${apiBase.replace(/\/$/, "")}${path}`, {
      method: body === undefined ? "GET" : "POST", signal,
      headers: { "X-Session-Id": sessionId, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request could not be completed (${response.status}).`);
    return data;
  }

  async function loadPublications() {
    const [claimData, publicationData] = await Promise.all([
      api<{ claims: Claim[] }>(`/v1/organizations/${encodeURIComponent(organizationId)}/authority-claims`),
      api<{ publications: Publication[]; nextCursor?: string | null }>(root),
    ]);
    if (alive.current && currentScope.current === scope) {
      setClaims(claimData.claims.filter(claim => claim.status === "verified"));
      setPublications(publicationData.publications);
      setPublicationCursor(publicationData.nextCursor || null);
    }
  }

  React.useEffect(() => {
    alive.current = true;
    let cancelled = false;
    if (canPublish) void loadPublications().catch(caught => { if (!cancelled) setPublicationError(errorText(caught)); });
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => { cancelled = true; alive.current = false; clearInterval(timer); searchAbort.current?.abort(); searchSequence.current++; };
  }, [scope, canPublish]);

  async function search(event?: React.FormEvent) {
    event?.preventDefault();
    if (query.trim().length < 2) return;
    const sequence = ++searchSequence.current;
    searchAbort.current?.abort();
    const controller = new AbortController(); searchAbort.current = controller;
    setSearching(true); setError(""); setResult(null);
    try {
      const data = await api<SearchResult>("/v1/federation/search", { query: query.trim(), limit: 20 }, controller.signal);
      if (alive.current && currentScope.current === scope && sequence === searchSequence.current) { setResult(data); setNow(Date.now()); }
    } catch (caught) {
      if (alive.current && sequence === searchSequence.current && !controller.signal.aborted) setError(errorText(caught));
    } finally {
      if (alive.current && sequence === searchSequence.current) setSearching(false);
    }
  }

  async function mutate(action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setPublicationError(""); setNotice("");
    try { await action(); }
    catch (caught) { if (alive.current && currentScope.current === scope) setPublicationError(errorText(caught)); }
    finally { busyRef.current = false; if (alive.current && currentScope.current === scope) setBusy(false); }
  }

  async function getPreview() {
    await mutate(async () => {
      setPreview(null); setConfirmed(false);
      const data = await api<Preview>(`${root}/preview`, { authority_claim_id: claimId });
      if (alive.current && currentScope.current === scope) setPreview(data);
    });
  }

  async function publish() {
    if (!preview || !confirmed) return;
    const exact = preview;
    await mutate(async () => {
      await api(root, { authority_claim_id: exact.publicFields.authorityClaimId, preview_digest: exact.previewDigest, confirm_publication: true });
      if (!alive.current || currentScope.current !== scope) return;
      setPreview(null); setConfirmed(false); setResult(null);
      setNotice("Published. This catalog entry is now available in connected searches.");
      await loadPublications();
    });
  }

  const expired = result?.sources.some(source => source.expiresAt && source.expiresAt * 1000 <= now);
  return <div className="connected-catalogs">
    <header className="connected-intro"><p className="connected-eyebrow">Catalog discovery</p><h1>Search connected catalogs.</h1>
      <p>Find a recording, its composition and the organizations reviewing each use. Each catalog publishes its own artist choices and keeps its records at the source.</p>
      {synthetic && <p className="connected-note">Fictional catalog demonstration · independent local nodes · illustrative identifiers</p>}
    </header>
    <form className="connected-search" onSubmit={search}><label htmlFor="connected-query">Track, artist, catalog, ISRC or ISWC</label>
      <div><input id="connected-query" value={query} minLength={2} maxLength={200} placeholder="Search participating catalogs" onChange={event => setQuery(event.target.value)} />
        <button type="submit" disabled={searching || query.trim().length < 2}>{searching ? "Checking sources…" : "Search catalogs"}</button></div>
    </form>
    {error && <p role="alert" className="connected-error">{error}</p>}
    {result && <section aria-label="Connected search results" className="connected-results">
      <div className="connected-result-heading"><h2>{result.results.length} {result.results.length === 1 ? "record" : "records"} for “{result.query}”</h2>
        <span>Checked {new Date(result.checkedAt * 1000).toLocaleTimeString()}</span></div>
      <div className="connected-sources" aria-label="Source availability">{result.sources.map(source => <div key={source.id} role="group" aria-label={`${source.id} source status`}>
        <strong>{source.id === "local" ? "This node" : source.id}</strong><span>{source.status === "ok" ? "Signature checked" : source.status === "timeout" ? "Timed out" : "Temporarily unavailable"}</span>
        {source.status === "ok" && <span className="connected-freshness">{!source.expiresAt ? "Freshness unavailable" : source.expiresAt * 1000 <= now ? "Expired · search again" : `Current until ${new Date(source.expiresAt * 1000).toLocaleTimeString()}`}</span>}
        <small>{source.origin}</small></div>)}</div>
      {result.partial && <p role="status" className="connected-warning">Some sources could not answer. These results cover the sources that responded; search again to check the others.</p>}
      {result.truncated && <p className="connected-warning">More entries may be available. Narrow your search by identifier or catalog name.</p>}
      {expired && <p role="status" className="connected-warning">One or more source statements have expired. Search again to refresh those catalog results.</p>}
      {!result.results.length && <p>No published entries matched this search. An organization can share a verified catalog entry using the publication controls below.</p>}
      <div className="connected-records">{result.results.map(({ entry, source }) => <article key={`${source.nodeId}:${entry.publicationId}`} aria-label={`${entry.organization.name} catalog result`}>
        <div className="connected-record-kind"><span>{label(entry.rightType)}</span><span>{entry.territory}</span></div>
        <h3>{entry.workTitle}</h3><p className="connected-artist">{entry.artistName}</p><p className="connected-owner">Published by <strong>{entry.organization.name}</strong></p>
        <dl className="connected-identifiers">{Object.entries(entry.catalogReferences).filter(([, value]) => value).map(([key, value]) => <div key={key}><dt>{key.toUpperCase()}</dt><dd>{value}</dd></div>)}</dl>
        <div className="connected-uses">{Object.entries(entry.policy.usage).filter(([, state]) => state !== "blocked").map(([use]) => <span key={use}>{label(use)}</span>)}</div>
        <p className="connected-note">Catalog references supplied by this organization. Its reviewer checks the requested use, scope and terms.</p>
        <PolicyDetails entry={entry} />
        <footer><span className="connected-freshness">{source.expiresAt * 1000 <= now ? "Expired · search again" : `Current until ${new Date(source.expiresAt * 1000).toLocaleTimeString()}`}</span><span>Policy {entry.policyVersion} · publication {entry.publicationRevision}{entry.synthetic ? " · fictional" : ""}</span><code>{source.nodeId}</code></footer>
      </article>)}</div>
      <details className="connected-proof"><summary>Inspect the source statements</summary><p>Each statement binds the search, published fields, source node and expiry. This node checks remote signatures against the operator’s configured peer keys.</p>
        {result.sources.filter(source => source.statement).map(source => <button key={source.id} onClick={() => download(source.statement, `clef-discovery-${source.id}.json`)}>Download {source.id === "local" ? "this node’s" : source.id} statement</button>)}
      </details>
    </section>}
    {canPublish && <section className="connected-publish" aria-label="Publish your catalog"><p className="connected-eyebrow">Your organization's choice</p><h2>Choose what buyers can find.</h2>
      <p>Review the exact public fields before sharing. Agreements, evidence and commercial terms stay in the organization’s private records. Policy or authority changes require a fresh publication review.</p>
      {publicationError && <p role="alert" className="connected-error">{publicationError}</p>}{notice && <p role="status" className="connected-success">{notice}</p>}
      <label htmlFor="publication-claim">Catalog entry with verified authority</label><div className="connected-publication-controls"><select id="publication-claim" value={claimId} disabled={busy} onChange={event => { setClaimId(event.target.value); setPreview(null); setConfirmed(false); }}>
        <option value="">Choose an entry</option>{claims.map(claim => <option key={claim.id} value={claim.id}>{claim.workKey} · {label(claim.rightType)} · {claim.territory}</option>)}</select>
        <button disabled={busy || !claimId} onClick={() => void getPreview()}>Preview public fields</button></div>
      {!claims.length && <p className="connected-note">Add a catalog policy and complete its authority review to prepare a publication.</p>}
      {preview && <div className="connected-preview"><h3>{preview.publicFields.workTitle} · {preview.publicFields.organization.name}</h3><p>{preview.distribution}. Search statements remain current for up to {preview.freshnessSeconds} seconds.</p>
        <details open><summary>Exact public fields</summary><pre>{JSON.stringify(preview.publicFields, null, 2)}</pre></details>
        <label className="connected-consent"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />I am authorized to publish these fields for this organization.</label>
        <button disabled={busy || !confirmed} onClick={() => void publish()}>{busy ? "Saving…" : "Publish these fields"}</button>
        <p className="connected-note">Withdrawal removes the entry from future searches. Previously downloaded public statements remain with their recipients.</p>
      </div>}
      {!!publications.length && <div className="connected-publication-list">{publications.map(publication => <div key={publication.id}><span><strong>{publication.publicFields.workTitle || publication.authorityClaimId}</strong><small>{label(publication.status)} · revision {publication.revision}</small></span>
        {publication.status !== "withdrawn" && <button disabled={busy} onClick={() => void mutate(async () => {
          await api(`${root}/${encodeURIComponent(publication.id)}/withdraw`, { expected_revision: publication.revision });
          if (!alive.current || currentScope.current !== scope) return;
          setPreview(null); setConfirmed(false); setResult(null); setNotice("Withdrawn from future searches. Existing signed statements expire within one minute.");
          await loadPublications();
        })}>Withdraw publication</button>}</div>)}</div>}
      {publicationCursor && <button disabled={busy} onClick={() => void mutate(async () => {
        const page = await api<{ publications: Publication[]; nextCursor: string | null }>(`${root}?cursor=${encodeURIComponent(publicationCursor)}`);
        if (!alive.current || currentScope.current !== scope) return;
        setPublications(current => [...current, ...page.publications.filter(row => !current.some(existing => existing.id === row.id))]);
        setPublicationCursor(page.nextCursor);
      })}>Load more publications</button>}
    </section>}
  </div>;
}
