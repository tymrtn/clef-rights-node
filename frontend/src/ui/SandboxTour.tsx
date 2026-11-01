import React from "react";
import "./SandboxTour.css";

type Session = { id: string };
type Permission = {
  id: string; status: string; receiptId: string | null; territory: string;
  termStart: string; termEnd: string;
  context: { aiUse: { inputAssets: string[]; sourceDurationSeconds: number; outputDurationSeconds: number } };
};
export type TourSide = {
  role: "label" | "publisher"; name: string; orgId: string; rightType: string; workKey: string;
  permissionId: string; permission: Permission; request: Record<string, any>;
  authority: { status: string; territory: string; evidence: { share?: string; controlledShare?: string } };
  policy: { version: number; contract: { aiPolicy: { limits: Record<string, number | null>; inputs: Record<string, string> }; matrix: { usage: Record<string, string> } } };
};
export type Tour = {
  synthetic: true; title: string; artist: string; version: string;
  identifiers: { isrc: string; iswc: string; source: string };
  requester: { id: string; name: string }; sides: TourSide[];
};
type Verification = { valid: boolean; payloadHashValid: boolean; signatureValid: boolean; transparencyHashValid: boolean };
type ReceiptCheck = { verification: Verification; receipt: any; tampered?: Verification };
type Section = "catalog" | "choices" | "review" | "receipt";
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const steps: { id: Section; label: string }[] = [
  { id: "catalog", label: "Connect the catalog" }, { id: "choices", label: "Set artist choices" },
  { id: "review", label: "Review a request" }, { id: "receipt", label: "Verify the decision" },
];

class TourError extends Error {
  constructor(public status: number, public detail: any) {
    super(typeof detail === "string" ? detail : detail?.message || `Request failed (${status})`);
  }
}

async function request<T>(path: string, session: Session, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method,
    headers: { "X-Session-Id": session.id, ...(body ? { "Content-Type": "application/json" } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) throw new TourError(response.status, data.detail);
  return data as T;
}

export function exampleApproval() {
  return { decision: "approved", note: "Fictional approval for the declared instrumental study",
    obligations: { attribution: { required: true,
      credit_text: "Paper Skies — Mara Vale (fictional sandbox example)",
      placements: ["description", "metadata"] }, publication_reporting_required: true,
      publication_evidence_due_days: 30, usage_reporting_frequency: "once" } };
}

export function scopeProbe(side: TourSide, kind: "training" | "territory" | "duration") {
  const payload = JSON.parse(JSON.stringify(side.request));
  delete payload.context.tourStep;
  payload.context.tourProbe = kind;
  if (kind === "training") payload.intended_usage = "ai_model_training";
  if (kind === "territory") payload.territory = "worldwide";
  if (kind === "duration") payload.context.aiUse.sourceDurationSeconds = 300;
  return payload;
}

function statusLabel(value: string) {
  return ({ pending: "Ready for review", approved: "Approved", rejected: "Declined", revoked: "Revoked",
    disputed: "Disputed", expired: "Expired", corrected: "Corrected" } as Record<string, string>)[value] || value;
}

export function SandboxTour({ session, onConsole, onSetup, onSignOut, onRestart, onDownload, federationEnabled = false }: {
  session: Session;
  onConsole: (orgId: string, tab: "catalog" | "policies" | "permissions" | "connected") => void;
  federationEnabled?: boolean;
  onSetup: () => void; onSignOut: () => Promise<void>; onRestart: () => Promise<void>;
  onDownload: (receiptId: string) => Promise<void>;
}) {
  const [tour, setTour] = React.useState<Tour | null>(null);
  const [section, setSection] = React.useState<Section>("catalog");
  const [perspective, setPerspective] = React.useState<"label" | "publisher" | "requester">("label");
  const [busy, setBusy] = React.useState(false);
  const busyRef = React.useRef(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [checks, setChecks] = React.useState<Record<string, ReceiptCheck>>({});
  const initial = React.useRef<Promise<Tour> | null>(null);
  const alive = React.useRef(true);

  React.useEffect(() => {
    alive.current = true;
    let cancelled = false;
    initial.current ??= request<Tour>("/v1/sandbox/tour", session, "POST");
    initial.current.then(data => { if (!cancelled) setTour(data); })
      .catch(caught => { if (!cancelled) setError(caught.message); });
    return () => { cancelled = true; alive.current = false; };
  }, [session.id]);

  async function run(action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(""); setNotice("");
    try { await action(); }
    catch (caught) { if (alive.current) setError(caught instanceof Error ? caught.message : "Please retry."); }
    finally { busyRef.current = false; if (alive.current) setBusy(false); }
  }
  async function reload(method = "GET") {
    const data = await request<Tour>("/v1/sandbox/tour", session, method);
    if (alive.current) setTour(data);
    return data;
  }
  async function decide(side: TourSide, decision: "approved" | "rejected") {
    let failure: unknown;
    try {
      await request(`/v1/permission-requests/${side.permissionId}/decide`, session, "POST",
        decision === "approved" ? exampleApproval() : { decision, note: "Fictional reviewer declined this example request" });
    } catch (caught) { failure = caught; }
    const latest = await reload();
    const status = latest.sides.find(row => row.permissionId === side.permissionId)?.permission.status;
    if (status === decision) {
      if (alive.current) setNotice(`${side.role === "label" ? "Recording" : "Composition"} decision recorded. ${decision === "approved" ? "The signed receipt is ready to inspect." : "The request is closed."}`);
    } else if (failure) throw failure;
  }
  async function verify(side: TourSide, tamper = false) {
    if (!side.permission.receiptId) return;
    const receipt = await request<any>(`/v1/receipts/${side.permission.receiptId}`, session);
    const verification = await request<Verification>("/v1/receipts/verify", session, "POST", { receipt });
    let tampered: Verification | undefined;
    if (tamper) {
      const copy = JSON.parse(JSON.stringify(receipt));
      copy.payload.permission.territory = "worldwide";
      tampered = await request<Verification>("/v1/receipts/verify", session, "POST", { receipt: copy });
    }
    if (alive.current) setChecks(current => ({ ...current, [side.permissionId]: { receipt, verification, tampered } }));
  }
  async function probe(side: TourSide, kind: "training" | "territory" | "duration") {
    try {
      const result = await request<{ status: string }>("/v1/permission-requests", session, "POST", scopeProbe(side, kind));
      if (alive.current) setNotice(`This request was accepted with status “${result.status}” under the current policy. Inspect it in the full console.`);
    } catch (caught) {
      if (!(caught instanceof TourError && caught.status === 409 &&
        (Array.isArray(caught.detail?.policyEvaluation) || caught.detail === "Requested territory exceeds the verified authority claim"))) throw caught;
      if (alive.current) setNotice(`Stopped by the live permission check: ${caught.message}.`);
    }
  }

  const selected = tour?.sides.find(side => side.role === perspective) || tour?.sides[0];
  const approvals = tour?.sides.filter(side => side.permission.status === "approved").length || 0;
  const sectionIndex = steps.findIndex(step => step.id === section);
  const message = <div aria-live="polite">{error && <div className="tour-message tour-error" role="alert">{error} <button disabled={busy} onClick={() => void run(async () => { await reload("POST"); })}>Reload example</button></div>}{notice && <div className="tour-message">{notice}</div>}</div>;

  return <div className="clef-tour">
    <header className="tour-header"><a href="#tour-main" className="tour-wordmark" aria-label="Clef example catalog">clef<span aria-hidden="true">/</span></a>
      <span className="tour-kicker">Interactive example · fictional catalog</span>
      <div className="tour-header-actions">{federationEnabled && tour && <button disabled={busy} onClick={() => onConsole(tour.requester.id, "connected")}>Search connected catalogs</button>}<button disabled={busy} onClick={onSetup}>Set up an organization</button><button disabled={busy} onClick={() => void run(onSignOut)}>Sign out</button></div>
    </header>
    <main id="tour-main" className="tour-main">
      <div className="tour-intro"><p className="tour-kicker">Catalog controls for the AI licensing era</p>
        <h1>Two approvals for<br />one AI music request.</h1>
        <p>Review the recording and composition separately, preserve Mara Vale’s conditions and give the requester a verifiable decision.</p>
        <p className="tour-small">You play each reviewer in this fictional example. Every action uses Clef’s permission checks and signing system. Use fictional data throughout this public sandbox.</p>
      </div>
      {!tour ? <section className="tour-card" aria-busy={!error}><h2>{error ? "Let’s finish preparing your example" : "Preparing your example catalog…"}</h2><p>Connecting the recording, composition and review requests.</p>{message}</section> : <>
        <nav className="tour-steps" aria-label="Walkthrough steps">{steps.map((step, i) => <button key={step.id} aria-current={step.id === section ? "step" : undefined} onClick={() => { setSection(step.id); setNotice(""); setError(""); }}><span>{String(i + 1).padStart(2, "0")}</span>{step.label}</button>)}</nav>
        <div className="tour-perspectives" aria-label="Organization perspective"><span>View as</span>{(["label", "publisher", "requester"] as const).map(role => <button key={role} aria-pressed={perspective === role} onClick={() => setPerspective(role)}>{role === "label" ? "Label" : role === "publisher" ? "Publisher" : "AI music company"}</button>)}<span className="tour-count">{approvals} of 2 example approvals</span></div>
        {message}
        {section === "catalog" && <section aria-labelledby="tour-catalog-title">
          <div className="tour-section-heading"><p className="tour-kicker">01 / The catalog</p><h2 id="tour-catalog-title">One title, two sets of rights.</h2><p>{perspective === "label" ? "Your recording sits alongside its composition reference. Each organization administers its own part." : perspective === "publisher" ? "Connect the composition to the recording while keeping the songwriter’s conditions and publishing approval separate." : "See which organizations represent the recording and composition, then request the scope you need from each."}</p></div>
          <div className="tour-pair" role="group" aria-label="Fictional recording and composition pairing">
            {tour.sides.map(side => <article className="tour-card tour-asset" key={side.role}>
              <div className="tour-asset-heading"><span className="tour-kicker">{side.role === "label" ? "Recording / master" : "Composition / song"}</span><span className="tour-pill">Illustrative</span></div>
              <div className="tour-identifier"><strong>{side.role === "label" ? "ISRC" : "ISWC"}</strong><span>Identifies the {side.role === "label" ? "recording" : "composition"}</span></div>
              <h3>{tour.title}</h3><p>{tour.artist}</p><dl><div><dt>{side.role === "label" ? "Example ISRC" : "Example ISWC"}</dt><dd>{side.role === "label" ? tour.identifiers.isrc : tour.identifiers.iswc}</dd></div><div><dt>Administered by</dt><dd>{side.name}</dd></div><div><dt>Example mandate</dt><dd>{Number(side.authority.evidence.share ?? side.authority.evidence.controlledShare)}% of the {side.rightType} · {side.authority.territory}</dd></div><div><dt>Review status</dt><dd>{side.authority.status === "verified" ? "Verified for this fictional example" : side.authority.status}</dd></div></dl>
              <button className="tour-link" onClick={() => onConsole(side.orgId, "catalog")}>Inspect catalog record ↗</button>
            </article>)}
            <span className="tour-connector" aria-hidden="true">↔</span>
          </div>
          <p className="tour-small">Pairing source: {tour.identifiers.source}. Identifiers and ownership are illustrative. The catalog records carry this source reference; each organization has its own reviewed example mandate.</p>
        </section>}
        {section === "choices" && selected && <section aria-labelledby="tour-choices-title">
          <div className="tour-section-heading"><p className="tour-kicker">02 / Artist choices</p><h2 id="tour-choices-title">Turn “ask me first” into a usable policy.</h2><p>{selected.name} keeps a versioned policy for the {selected.rightType}. Explore the current policy in the console to change the conditions.</p></div>
          <div className="tour-grid"><article className="tour-card"><span className="tour-pill">Policy version {selected.policy.version}</span><h3>Generation using licensed music</h3><p className="tour-policy-state">{selected.policy.contract.matrix.usage.ai_grounded_generation === "requires_approval" ? "Artist representative reviews each request" : selected.policy.contract.matrix.usage.ai_grounded_generation === "blocked" ? "Blocked by the current policy" : "Allowed within the published conditions"}</p><dl>{Object.entries(selected.policy.contract.aiPolicy.inputs).map(([key, value]) => <div key={key}><dt>{({ full_mix: "Full recording", stems: "Stems", isolated_vocals: "Isolated vocals", lyrics: "Lyrics", composition_data: "Composition data", reference_embeddings: "Reference embeddings" } as Record<string, string>)[key] || key}</dt><dd>{value === "requires_approval" ? "Review required" : value === "blocked" ? "Blocked" : "Allowed"}</dd></div>)}</dl><button className="tour-link" onClick={() => onConsole(selected.orgId, "policies")}>Open the full policy ↗</button></article>
            <article className="tour-card"><h3>Give the request clear boundaries.</h3><dl>{Object.entries(selected.policy.contract.aiPolicy.limits).map(([key, value]) => <div key={key}><dt>{({ maxSourceDurationSeconds: "Source audio · seconds", maxOutputDurationSeconds: "Output · seconds", maxLyricCharacters: "Lyric characters", sourceRetentionDays: "Source retention · days", embeddingRetentionDays: "Embedding retention · days" } as Record<string, string>)[key] || key}</dt><dd>{value ?? "Set in the individual license"}</dd></div>)}</dl><p>Model access, credit, similarity review and deletion obligations are set alongside these limits.</p><p className="tour-small">Stems and lyrics here describe permitted inputs. Organizations arrange audio delivery and require watermarking and usage reports from their production partners.</p></article></div>
        </section>}
        {section === "review" && selected && <section aria-labelledby="tour-review-title">
          <div className="tour-section-heading"><p className="tour-kicker">03 / The request</p><h2 id="tour-review-title">A specific use. A separate decision for each right.</h2><p>{tour.requester.name} requests a 60-second instrumental study, using up to 30 seconds of source material in a private model for the United States.</p></div>
          <div className="tour-grid">{tour.sides.map(side => <article key={side.role} className="tour-card"><div className="tour-asset-heading"><span className="tour-kicker">{side.role === "label" ? "Label review" : "Publisher review"}</span><span className={`tour-pill ${side.permission.status === "approved" ? "tour-approved" : ""}`}>{statusLabel(side.permission.status)}</span></div><h3>{side.name}</h3><dl><div><dt>Right requested</dt><dd>{side.rightType === "master" ? "Recording" : "Composition"}</dd></div><div><dt>Input</dt><dd>{side.permission.context.aiUse.inputAssets.map(value => value === "composition_data" ? "Composition data" : value === "stems" ? "Stems" : value).join(", ")}</dd></div><div><dt>Territory</dt><dd>{side.permission.territory}</dd></div><div><dt>Term</dt><dd>{side.permission.termStart} → {side.permission.termEnd}</dd></div></dl>
            <p className="tour-small">Approval includes the credit “Paper Skies — Mara Vale (fictional sandbox example)” in the description and metadata, plus publication evidence within 30 days.</p>
            {side.permission.status === "pending" && <div className="tour-actions"><button className="tour-primary" disabled={busy} onClick={() => void run(() => decide(side, "approved"))}>Approve {side.role === "label" ? "recording" : "composition"} use</button><button disabled={busy} onClick={() => void run(() => decide(side, "rejected"))}>Decline</button></div>}
            <button className="tour-link" onClick={() => onConsole(side.orgId, "permissions")}>Inspect the request and review history ↗</button>
          </article>)}</div>
          <aside className="tour-challenge"><div><h3>Try a request beyond the agreed scope.</h3><p>These buttons submit a different request through the same API. The published policy and territorial mandate decide what happens.</p></div><div className="tour-actions"><button disabled={busy} onClick={() => void run(() => probe(selected, "training"))}>Request model training</button><button disabled={busy} onClick={() => void run(() => probe(selected, "territory"))}>Request worldwide use</button><button disabled={busy} onClick={() => void run(() => probe(selected, "duration"))}>Request five minutes</button></div></aside>
        </section>}
        {section === "receipt" && <section aria-labelledby="tour-receipt-title"><div className="tour-section-heading"><p className="tour-kicker">04 / The decision</p><h2 id="tour-receipt-title">The conditions travel with the approval.</h2><p>Each approved right gets its own signed receipt. Verify the original, then change a copy’s territory to see the signature check catch the difference.</p><button className="tour-link" disabled={busy} onClick={() => void run(async () => { await reload(); setNotice("Decision status refreshed from the node."); })}>Refresh decision status</button></div><div className="tour-grid">{tour.sides.map(side => {
          const check = checks[side.permissionId];
          return <article className="tour-card" key={side.role}><div className="tour-asset-heading"><span className="tour-kicker">{side.role === "label" ? "Recording receipt" : "Composition receipt"}</span><span className="tour-pill">{statusLabel(side.permission.status)}</span></div><h3>{side.name}</h3>{!side.permission.receiptId ? <><p>Approve the example request to issue this receipt.</p><button className="tour-link" onClick={() => setSection("review")}>Review the request →</button></> : <><p className="tour-mono">{side.permission.receiptId}</p><div className="tour-actions"><button className="tour-primary" disabled={busy} onClick={() => void run(() => verify(side))}>Verify signature</button><button disabled={busy} onClick={() => void run(() => verify(side, true))}>Test an altered copy</button><button disabled={busy} onClick={() => void run(() => onDownload(side.permission.receiptId!))}>Download signed JSON</button></div>{check && <div className="tour-verification" role="status"><h4>{check.verification.valid ? "Original receipt verified" : "Verification failed"}</h4><ul><li>Payload integrity: {check.verification.payloadHashValid ? "verified" : "failed"}</li><li>Issuer signature: {check.verification.signatureValid ? "verified" : "failed"}</li><li>Audit chain entry: {check.verification.transparencyHashValid ? "verified" : "failed"}</li></ul>{check.tampered && <p>{check.tampered.valid ? "The altered copy passed. This needs investigation." : "Altered copy rejected: changing US to worldwide invalidated the signed payload."}</p>}<details><summary>Inspect the signed record</summary><pre>{JSON.stringify(check.receipt, null, 2)}</pre></details></div>}</>}<p className="tour-small">Receipt access is limited to the parties. Signature verification establishes the recorded decision; the current status above tracks any later withdrawal or dispute.</p></article>;
        })}</div><aside className="tour-challenge"><div><h3>Your catalog. Your approvals. Your infrastructure.</h3><p>The full console adds your team, policy versions, API credentials, reports and exports. Labels and publishers remain responsible for the rights they administer.</p></div><button className="tour-primary" onClick={() => onConsole(tour.sides[0].orgId, "permissions")}>Explore the full console ↗</button></aside></section>}
        <footer className="tour-navigation"><button disabled={sectionIndex === 0} onClick={() => setSection(steps[sectionIndex - 1].id)}>← Previous</button><span>{sectionIndex + 1} / {steps.length}</span>{sectionIndex < steps.length - 1 ? <button className="tour-primary" onClick={() => setSection(steps[sectionIndex + 1].id)}>{steps[sectionIndex + 1].label} →</button> : <button disabled={busy} onClick={() => void run(onRestart)}>Start a fresh example</button>}</footer>
      </>}
    </main>
  </div>;
}
