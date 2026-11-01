import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, expect, it, vi } from "vitest";
import { RequestPermission } from "./RightsNodeApp";

const claim = { id: "claim-1", organization: { id: "publisher-1", name: "Example Publishing · fictional" }, workKey: "iswc:T1234567894",
  workTitle: "Paper Skies", artistName: "Mara Vale (fictional)", rightType: "composition", territory: "US", verificationStatus: "verified",
  matrix: { usage: { ai_grounded_generation: "requires_approval" }, restrictions: { political: "denied" } },
  aiPolicy: { schemaVersion: "1", inputs: {}, modelScopes: {}, limits: {}, safeguards: { attribution: true, outputWatermark: false } } };
let view: ReactTestRenderer | undefined;
afterEach(() => { if (view) act(() => view!.unmount()); view = undefined; vi.unstubAllGlobals(); });
const checkbox = (text: string) => view!.root.findAllByType("label").find(node => node.children.includes(text))!.findByType("input");
const submit = () => view!.root.findAllByType("button").find(node => node.children.includes("Request permission"))!;

it("sends the declared content and AI scope for a local request once every gate is met", async () => {
  const writes: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") { writes.push({ url, body: JSON.parse(String(init.body)) }); return new Response(JSON.stringify({ status: "pending" })); }
    return new Response(JSON.stringify({ claims: [claim] }));
  }));
  await act(async () => { view = create(<RequestPermission session={{ id: "session-1", email: "buyer@example.test", expires_at: "2027-01-01" }}
    organization={{ id: "org-1", slug: "org-1", name: "Example Label · fictional", role: "member" } as any} />); });
  act(() => view!.root.findAllByType("select")[0].props.onChange({ target: { value: "claim-1" } }));
  act(() => view!.root.findByProps({ "aria-label": "License start date" }).props.onChange({ target: { value: "2026-12-01" } }));
  act(() => view!.root.findByProps({ "aria-label": "License end date" }).props.onChange({ target: { value: "2027-11-30" } }));
  expect(view!.root.findAllByType("label").find(node => node.children.includes("Political"))!
    .findAllByType("span").map((node: ReactTestInstance) => node.children.join(""))).toEqual(["(denied)"]);
  expect(submit().props.disabled).toBe(true);
  act(() => checkbox("I have reviewed every category. My selections describe this use; leaving all categories clear means none apply.").props.onChange({ target: { checked: true } }));
  expect(submit().props.disabled).toBe(true);
  act(() => checkbox("Artist and rightsholder attribution").props.onChange());
  expect(submit().props.disabled).toBe(false);
  act(() => checkbox("Political").props.onChange());
  expect(submit().props.disabled).toBe(true);
  act(() => checkbox("I have reviewed every category. My selections describe this use; leaving all categories clear means none apply.").props.onChange({ target: { checked: true } }));
  await act(async () => { view!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  expect(writes).toEqual([{ url: "/v1/permission-requests", body: { requester_org_id: "org-1", authority_claim_id: "claim-1",
    intended_usage: "ai_grounded_generation", territory: "worldwide", term_start: "2026-12-01", term_end: "2027-11-30", provenance: {},
    context: { releaseTitle: "", restrictionCategories: ["political"], aiUse: { inputAssets: ["full_mix"], modelScope: "private_single_tenant",
      acceptedSafeguards: ["attribution"], sourceDurationSeconds: null, outputDurationSeconds: null, lyricCharacters: null,
      sourceRetentionDays: null, embeddingRetentionDays: null } } } }]);
  expect(JSON.stringify(view!.toJSON())).toContain("Request sent to the verified rights authority.");
});
