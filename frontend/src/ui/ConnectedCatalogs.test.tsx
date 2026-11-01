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
    vi.stubGlobal("fetch", fixtureFetch(writes));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" canPublish />); });
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
    vi.stubGlobal("fetch", vi.fn(async (url, init) => String(url).endsWith("/publications") && init?.method === "POST"
      ? new Response(JSON.stringify({ detail: "The publication or policy changed. Review a fresh preview." }), { status: 409 }) : initial(url, init)));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" canPublish />); });
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
    vi.stubGlobal("fetch", vi.fn(async () => ok({ query: "Paper Skies", checkedAt: now, partial: true, truncated: false,
      sources: [{ ...source, status: "ok", entries: [entry], statement: { payload: {} } }, { id: "other-label", nodeId: "urn:other", origin: "https://other.example.test", status: "timeout", entries: [] }],
      results: [{ entry, source }] })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" canPublish={false} synthetic />); });
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
    vi.stubGlobal("fetch", vi.fn(() => ++call === 1 ? new Promise<Response>(resolve => { resolveOld = resolve; }) : Promise.resolve(empty("New catalog"))));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" canPublish={false} synthetic />); });
    act(() => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    act(() => view!.root.findByProps({ id: "connected-query" }).props.onChange({ target: { value: "New catalog" } }));
    await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    await act(async () => { resolveOld(empty("Stale query")); });
    expect(rendered()).toContain("New catalog");
    expect(rendered()).not.toContain("Stale query");
  });

  it("keeps content eligibility separate from permission for a use", async () => {
    const now = Math.floor(Date.now() / 1000);
    const source = { id: "local", nodeId: "urn:local", origin: "https://label.example.test", expiresAt: now + 60 };
    const restrictedEntry = { ...entry, policy: { ...entry.policy,
      usage: { ai_grounded_generation: "requires_approval", ads_brand: "allowed" },
      restrictions: { political: "denied", adult: "allowed", alcohol_tobacco_cannabis: "conditional" } } };
    vi.stubGlobal("fetch", vi.fn(async () => ok({ query: "Paper Skies", checkedAt: now, partial: false, truncated: false,
      sources: [{ ...source, status: "ok", entries: [restrictedEntry] }], results: [{ entry: restrictedEntry, source }] })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" canPublish={false} synthetic />); });
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
    vi.stubGlobal("fetch", vi.fn(async () => ok({ query: "Paper Skies", checkedAt: now - 100, partial: false, truncated: false,
      sources: [{ id: "local", nodeId: "urn:local", origin: "https://local.example.test", status: "ok", expiresAt: now - 1, entries: [] }], results: [] })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" canPublish={false} synthetic />); });
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
    vi.stubGlobal("fetch", vi.fn(async () => ok({ query: "Paper Skies", checkedAt: now, partial: false, truncated: false, sources, results })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" canPublish={false} synthetic />); });
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
    vi.stubGlobal("fetch", vi.fn(async (url) => ok(String(url).endsWith("/authority-claims") ? { claims: [] }
      : String(url).includes("?cursor=") ? { publications: [first, second], nextCursor: null }
      : { publications: [first], nextCursor: "publication-1" })));
    await act(async () => { view = create(<ConnectedCatalogs sessionId="session-1" organizationId="org-1" canPublish />); });
    await act(async () => { button("Load more publications").props.onClick(); });
    expect(rendered()).toContain("claim-first");
    expect(rendered()).toContain("claim-second");
    expect(view!.root.findAllByType("strong").filter(node => node.children.includes("claim-first"))).toHaveLength(1);
    expect(button("Load more publications")).toBeUndefined();
  });
});
