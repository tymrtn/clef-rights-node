import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectedCatalogs } from "./ConnectedCatalogs";

const entry = { publicationId: "publication-1", organization: { id: "publisher-1", name: "Example Publishing · fictional" },
  authorityClaimId: "claim-1", workKey: "iswc:T1234567894", workTitle: "Paper Skies", artistName: "Mara Vale (fictional)",
  rightType: "composition", territory: "US", policyVersion: 1, publicationRevision: 1, synthetic: true,
  catalogReferences: { isrc: "ZZDEM2600001", iswc: "T1234567894" },
  policy: { usage: { ai_grounded_generation: "requires_approval", ai_model_training: "blocked" }, inputs: { composition_data: "requires_approval" } } };
const preview = { publicFields: entry, previewDigest: "a".repeat(64), distribution: "Public catalog search", freshnessSeconds: 60 };
const ok = (value: unknown) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
let view: ReactTestRenderer | undefined;
afterEach(() => { if (view) act(() => view!.unmount()); view = undefined; vi.unstubAllGlobals(); vi.useRealTimers(); });
const button = (text: string) => view!.root.findAllByType("button").find(node => node.children.includes(text))!;
const rendered = () => JSON.stringify(view!.toJSON());
const organizations = [{ id: "org-1", name: "Example Label · fictional" }, { id: "org-2", name: "Example Studio · fictional" }];
const peer = { id: "example-publisher", nodeId: "urn:publisher", origin: "https://publisher.example.test" };
const outbound = { id: "request-1", sourceId: peer.id, sourceNodeId: peer.nodeId, sourceOrigin: peer.origin, publicationId: "publication-1",
  requesterOrgId: "org-1", status: "pending", remotePermissionId: "permission-9", receipts: [] as unknown[], decisionNote: null as string | null,
  decidedAt: null as string | null, policyState: "requires_approval", requestStatement: {}, statusStatement: {}, createdAt: "2026-11-01T10:00:00", refreshedAt: "2026-11-01T10:00:01" };
const searchOf = (entries: typeof entry[]) => {
  const source = { ...peer, expiresAt: Math.floor(Date.now() / 1000) + 60 };
  return { query: "Paper Skies", checkedAt: Math.floor(Date.now() / 1000), partial: false, truncated: false,
    sources: [{ ...source, status: "ok", entries }], results: entries.map(item => ({ entry: item, source })) };
};

const confirmation = "I have reviewed every category. My selections describe this use; leaving all categories clear means none apply.";
const option = (text: string) => view!.root.findAllByType("label").find(node => node.children.includes(text))!;

// Every console mount lists the organization's sent requests; `requests` is read at call time.
function stubFetch(handler: (...args: any[]) => Promise<Response>, requests: unknown[] = []) {
  vi.stubGlobal("fetch", vi.fn(async (url, init) => String(url).endsWith("/federation/permission-requests") && init?.method === "GET" ? ok({ requests }) : handler(url, init)));
}

function fixtureFetch(writes: any[]) {
  return vi.fn(async (url, init) => {
    if (init?.method === "POST") {
      const body = JSON.parse(init.body); writes.push({ url: String(url), body });
      if (String(url).endsWith("/preview")) return ok(preview);
      return ok({ id: "publication-1", revision: 1, publicFields: entry, status: "published" });
    }
    return ok(String(url).endsWith("/authority-claims") ? { claims: [{ id: "claim-1", workKey: entry.workKey, rightType: "composition", territory: "US", status: "verified" }] } : { publications: [] });
  });
}

describe("connected catalogs in the rendered console", () => {
  it("requires preview and explicit consent, then sends its exact digest once", async () => {
    const writes: any[] = [];
    stubFetch(fixtureFetch(writes));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish />); });
    expect(button("Preview public fields").props.disabled).toBe(true);
    act(() => view!.root.findByType("select").props.onChange({ target: { value: "claim-1" } }));
    await act(async () => { await button("Preview public fields").props.onClick(); });
    expect(rendered()).toContain("Exact public fields");
    expect(button("Publish these fields").props.disabled).toBe(true);
    act(() => view!.root.findByProps({ type: "checkbox" }).props.onChange({ target: { checked: true } }));
    await act(async () => { button("Publish these fields").props.onClick(); button("Publish these fields").props.onClick(); });
    expect(writes.filter(row => row.url.endsWith("/publications"))).toEqual([{ url: "/v1/organizations/org-1/catalog/publications",
      body: { authority_claim_id: "claim-1", preview_digest: preview.previewDigest, confirm_publication: true } }]);
    expect(rendered()).toContain("Published. This catalog entry");
  });

  it("keeps a failed publication reviewable and surfaces a stale-policy rejection", async () => {
    const writes: any[] = [];
    const initial = fixtureFetch(writes);
    stubFetch(vi.fn(async (url, init) => String(url).endsWith("/publications") && init?.method === "POST"
      ? new Response(JSON.stringify({ detail: "The publication or policy changed. Review a fresh preview." }), { status: 409 }) : initial(url, init)));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish />); });
    act(() => view!.root.findByType("select").props.onChange({ target: { value: "claim-1" } }));
    await act(async () => { button("Preview public fields").props.onClick(); });
    act(() => view!.root.findByProps({ type: "checkbox" }).props.onChange({ target: { checked: true } }));
    await act(async () => { button("Publish these fields").props.onClick(); });
    expect(view!.root.findByProps({ role: "alert" }).children.join("")).toContain("Review a fresh preview");
    expect(rendered()).not.toContain("Published. This catalog entry");
  });

  it("retains source identity and clearly distinguishes a partial search from zero matches", async () => {
    const now = Math.floor(Date.now() / 1000);
    const source = { id: "example-publisher", nodeId: "urn:publisher", origin: "https://publisher.example.test", expiresAt: now + 60 };
    stubFetch(vi.fn(async () => ok({ query: "Paper Skies", checkedAt: now, partial: true, truncated: false,
      sources: [{ ...source, status: "ok", entries: [entry], statement: { payload: {} } }, { id: "other-label", nodeId: "urn:other", origin: "https://other.example.test", status: "timeout", entries: [] }],
      results: [{ entry, source }] })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    expect(rendered()).toContain("Some sources could not answer");
    expect(rendered()).toContain("Example Publishing");
    expect(rendered()).toContain("urn:publisher");
    expect(rendered()).toContain("T1234567894");
    expect(rendered()).not.toContain("Publish your catalog");
  });

  it("does not resurrect a previous query when its late response arrives", async () => {
    let resolveOld!: (value: Response) => void;
    let call = 0;
    const empty = (query: string) => ok({ query, checkedAt: Math.floor(Date.now() / 1000), sources: [], results: [], partial: false, truncated: false });
    stubFetch(vi.fn(() => ++call === 1 ? new Promise<Response>(resolve => { resolveOld = resolve; }) : Promise.resolve(empty("New catalog"))));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    act(() => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    act(() => view!.root.findByProps({ id: "connected-query" }).props.onChange({ target: { value: "New catalog" } }));
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    await act(async () => { resolveOld(empty("Stale query")); });
    expect(rendered()).toContain("New catalog");
    expect(rendered()).not.toContain("Stale query");
  });

  it("does not point a visitor who cannot publish to publication controls", async () => {
    stubFetch(vi.fn(async () => ok({ query: "Unknown", checkedAt: Math.floor(Date.now() / 1000), sources: [], results: [], partial: false, truncated: false })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    expect(rendered()).toContain("No published entries matched this search.");
    expect(rendered()).not.toContain("publication controls");
    expect(rendered()).not.toContain("local nodes");
  });

  it("keeps content eligibility separate from permission for a use", async () => {
    const now = Math.floor(Date.now() / 1000);
    const source = { id: "local", nodeId: "urn:local", origin: "https://label.example.test", expiresAt: now + 60 };
    const restrictedEntry = { ...entry, policy: { ...entry.policy,
      usage: { ai_grounded_generation: "requires_approval", ads_brand: "allowed" },
      restrictions: { political: "denied", adult: "allowed", alcohol_tobacco_cannabis: "conditional" } } };
    stubFetch(vi.fn(async () => ok({ query: "Paper Skies", checkedAt: now, partial: false, truncated: false,
      sources: [{ ...source, status: "ok", entries: [restrictedEntry] }], results: [{ entry: restrictedEntry, source }] })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    const valueFor = (term: string) => view!.root.findAllByType("dt").find(node => node.children.includes(term))!.parent!.findByType("dd").children.join("");
    expect(valueFor("Generation using licensed music")).toBe("Reviewer approval");
    expect(valueFor("Brand Advertising")).toBe("Allowed by policy");
    expect(valueFor("Political Content")).toBe("Excluded");
    expect(valueFor("Adult Content")).toBe("Use policy applies");
    expect(valueFor("Alcohol, Tobacco & Cannabis")).toBe("Conditions apply");
    expect(rendered()).not.toContain("Policy allows this use");
  });

  it("marks expired statements so an old result cannot look current", async () => {
    const now = Math.floor(Date.now() / 1000);
    stubFetch(vi.fn(async () => ok({ query: "Paper Skies", checkedAt: now - 100, partial: false, truncated: false,
      sources: [{ id: "local", nodeId: "urn:local", origin: "https://local.example.test", status: "ok", expiresAt: now - 1, entries: [] }], results: [] })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    expect(rendered()).toContain("One or more source statements have expired");
  });

  it("attributes expiry to its own source and catalog while another remains current", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-18T02:00:00Z"));
    const now = Math.floor(Date.now() / 1000);
    const sources = [
      { id: "label", nodeId: "urn:label", origin: "https://label.example.test", expiresAt: now + 6, status: "ok", entries: [entry] },
      { id: "publisher", nodeId: "urn:publisher", origin: "https://publisher.example.test", expiresAt: now + 60, status: "ok", entries: [entry] },
    ];
    const results = sources.map(source => ({ source, entry: { ...entry, organization: { id: source.id, name: source.id } } }));
    stubFetch(vi.fn(async () => ok({ query: "Paper Skies", checkedAt: now, partial: false, truncated: false, sources, results })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    act(() => { vi.advanceTimersByTime(10000); });
    const text = (name: string) => JSON.stringify(view!.root.findByProps({ "aria-label": name }).findAllByType("span").map(node => node.children));
    expect(text("label source status")).toContain("Expired · search again");
    expect(text("label catalog result")).toContain("Expired · search again");
    expect(text("publisher source status")).toContain("Current until");
    expect(text("publisher catalog result")).toContain("Current until");
    expect(text("publisher catalog result")).not.toContain("Expired");
  });

  it("lets an administrator reach later publication pages without losing earlier records", async () => {
    const first = { id: "publication-1", authorityClaimId: "claim-first", revision: 1, status: "withdrawn", publicFields: {} };
    const second = { ...first, id: "publication-2", authorityClaimId: "claim-second" };
    stubFetch(vi.fn(async (url) => ok(String(url).endsWith("/authority-claims") ? { claims: [] }
      : String(url).includes("?cursor=") ? { publications: [first, second], nextCursor: null }
      : { publications: [first], nextCursor: "publication-1" })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish />); });
    await act(async () => { button("Load more publications").props.onClick(); });
    expect(rendered()).toContain("claim-first");
    expect(rendered()).toContain("claim-second");
    expect(view!.root.findAllByType("strong").filter(node => node.children.includes("claim-first"))).toHaveLength(1);
    expect(button("Load more publications")).toBeUndefined();
  });

  it("offers to request terms only where the entry has a use that is not blocked", async () => {
    const closed = { ...entry, publicationId: "publication-2", organization: { id: "publisher-2", name: "Closed Catalog · fictional" },
      policy: { ...entry.policy, usage: { ai_grounded_generation: "blocked", ai_model_training: "blocked" } } };
    stubFetch(vi.fn(async () => ok(searchOf([entry, closed]))));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    const requestButtons = (name: string) => view!.root.findByProps({ "aria-label": `${name} catalog result` }).findAllByType("button").filter(node => node.children.includes("Request terms"));
    expect(requestButtons("Example Publishing · fictional")).toHaveLength(1);
    expect(requestButtons("Closed Catalog · fictional")).toHaveLength(0);
  });

  it("signs a request with the exact entry, terms and declared AI scope, then shows the source's pending answer", async () => {
    const writes: any[] = [];
    const sent: unknown[] = [];
    const governed = { ...entry, policy: { ...entry.policy, restrictions: { political: "denied" }, safeguards: { attribution: true, outputWatermark: false } } };
    stubFetch(vi.fn(async (url, init) => {
      writes.push({ url: String(url), body: JSON.parse(init.body) });
      if (String(url).endsWith("/federation/search")) return ok(searchOf([governed]));
      sent.push(outbound); return ok(outbound);
    }), sent);
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    act(() => button("Request terms").props.onClick());
    const uses = view!.root.findByProps({ id: "request-usage" }).findAllByType("option");
    expect(uses.map(option => option.props.value)).toEqual(["ai_grounded_generation"]);
    expect(uses[0].children.join("")).toContain("requires approval, reviewed by a person at the source");
    expect(view!.root.findByProps({ id: "request-organization" }).props.value).toBe("org-1");
    expect(view!.root.findByProps({ id: "request-territory" }).props.value).toBe("US");
    expect(rendered()).toContain("This node signs the request and sends it to https://publisher.example.test");
    expect(rendered()).toContain("Your session and credentials stay on this node");
    act(() => view!.root.findByProps({ id: "request-term-start" }).props.onChange({ target: { value: "2026-12-01" } }));
    act(() => view!.root.findByProps({ id: "request-term-end" }).props.onChange({ target: { value: "2027-11-30" } }));
    expect(option("Political Content").findByType("span").children.join("")).toBe("(denied)");
    expect(option("Composition, MIDI or score").findByType("span").children.join("")).toBe("(requires approval)");
    expect(option("Full recording").findByType("input").props.checked).toBe(true);
    expect(button("Sign and send request").props.disabled).toBe(true);
    act(() => option(confirmation).findByType("input").props.onChange({ target: { checked: true } }));
    expect(button("Sign and send request").props.disabled).toBe(true);
    act(() => option("Artist credit").findByType("input").props.onChange());
    expect(button("Sign and send request").props.disabled).toBe(false);
    await act(async () => { view!.root.findByProps({ "aria-label": "Request terms for Paper Skies" }).props.onSubmit({ preventDefault() {} }); });
    expect(writes.filter(row => row.url.endsWith("/permission-requests"))).toEqual([{ url: "/v1/federation/permission-requests", body: {
      source_id: "example-publisher", publication_id: "publication-1", requester_org_id: "org-1", intended_usage: "ai_grounded_generation",
      territory: "US", term_start: "2026-12-01", term_end: "2027-11-30", context: { releaseTitle: "", restrictionCategories: [],
        aiUse: { inputAssets: ["full_mix"], modelScope: "private_single_tenant", acceptedSafeguards: ["attribution"], sourceDurationSeconds: null,
          outputDurationSeconds: null, lyricCharacters: null, sourceRetentionDays: null, embeddingRetentionDays: null } } } }]);
    const result = view!.root.findByProps({ "aria-label": "Example Publishing · fictional catalog result" });
    expect(result.findByProps({ role: "status" }).findByType("strong").children).toEqual(["Waiting for the source's decision"]);
    expect(view!.root.findAllByProps({ "aria-label": "Request to https://publisher.example.test for publication-1" })).toHaveLength(1);
  });

  it("does not preselect source material that the published policy blocks", async () => {
    const governed = { ...entry, policy: { ...entry.policy, inputs: { full_mix: "blocked", composition_data: "requires_approval" } } };
    stubFetch(vi.fn(async () => ok(searchOf([governed]))), []);
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    act(() => button("Request terms").props.onClick());
    expect(option("Full recording").findByType("input").props.checked).toBe(false);
    act(() => view!.root.findByProps({ id: "request-term-start" }).props.onChange({ target: { value: "2026-12-01" } }));
    act(() => view!.root.findByProps({ id: "request-term-end" }).props.onChange({ target: { value: "2027-11-30" } }));
    act(() => option(confirmation).findByType("input").props.onChange({ target: { checked: true } }));
    expect(button("Sign and send request").props.disabled).toBe(true);
    act(() => option("Composition, MIDI or score").findByType("input").props.onChange());
    expect(button("Sign and send request").props.disabled).toBe(false);
  });

  it("shows the source's refusal verbatim and keeps the request editable", async () => {
    const detail = "The source node answered: This catalog entry is not currently published";
    stubFetch(vi.fn(async (url) => String(url).endsWith("/federation/search") ? ok(searchOf([entry]))
      : new Response(JSON.stringify({ detail }), { status: 409 })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    act(() => button("Request terms").props.onClick());
    act(() => view!.root.findByProps({ id: "request-term-start" }).props.onChange({ target: { value: "2026-12-01" } }));
    act(() => view!.root.findByProps({ id: "request-term-end" }).props.onChange({ target: { value: "2027-11-30" } }));
    act(() => option(confirmation).findByType("input").props.onChange({ target: { checked: true } }));
    await act(async () => { view!.root.findByProps({ "aria-label": "Request terms for Paper Skies" }).props.onSubmit({ preventDefault() {} }); });
    const form = view!.root.findByProps({ "aria-label": "Request terms for Paper Skies" });
    expect(form.findByProps({ role: "alert" }).children.join("")).toBe(detail);
    expect(view!.root.findByProps({ id: "request-term-start" }).props.value).toBe("2026-12-01");
    expect(view!.root.findAllByProps({ role: "status" })).toHaveLength(0);
  });

  it("lists sent requests and refreshes one to the source's signed approval", async () => {
    const writes: string[] = [];
    const receipt = { payload: { status: "approved" }, proof: { signature: "synthetic-signature" } };
    stubFetch(vi.fn(async (url) => {
      writes.push(String(url));
      return ok({ ...outbound, status: "approved", decidedAt: "2026-11-01T12:00:00Z", decisionNote: "Approved for the stated term.", receipts: [receipt] });
    }), [outbound]);
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" organizations={organizations} canPublish={false} synthetic />); });
    const row = () => view!.root.findByProps({ "aria-label": "Request to https://publisher.example.test for publication-1" });
    const value = (term: string) => row().findAllByType("dt").find(node => node.children.includes(term))!.parent!.findByType("dd").children;
    expect(row().findByType("strong").children).toEqual(["Waiting for the source's decision"]);
    expect(value("Source")).toEqual(["https://publisher.example.test"]);
    expect(value("Receipts")).toEqual(["0 signed receipts"]);
    await act(async () => { button("Refresh status").props.onClick(); });
    expect(writes).toEqual(["/v1/federation/permission-requests/request-1/refresh"]);
    expect(row().findByType("strong").children).toEqual(["Approved by the source, signed receipt received"]);
    expect(value("Receipts")).toEqual(["1 signed receipt"]);
    expect(value("Decided")).not.toEqual(["No decision yet"]);
    expect(rendered()).toContain("Source’s note: Approved for the stated term.");
    expect(button("Download receipt JSON")).toBeDefined();
  });
});
