import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, expect, it, vi } from "vitest";
import { SandboxTour, type Tour, exampleApproval, scopeProbe } from "./SandboxTour";
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

function fixture(): Tour {
  return {
    version: "clef.sandbox-tour.v1", synthetic: true, title: "Paper Skies", artist: "Mara Vale (fictional)",
    identifiers: { isrc: "ZZDEM1234567", iswc: "T0000000018", source: "Fictional fixture" },
    requester: { id: "studio", name: "Example Studio · fictional" },
    sides: (["label", "publisher"] as const).map(role => ({
      role, name: role === "label" ? "Example Records · fictional" : "Example Publishing · fictional",
      orgId: role, rightType: role === "label" ? "master" : "composition", workKey: `synthetic:${role}`,
      permissionId: `request-${role}`,
      authority: { status: "verified", territory: "US", evidence: { share: "100" } },
      permission: { id: `request-${role}`, status: "pending", receiptId: null, territory: "US",
        termStart: "2026-09-18", termEnd: "2026-12-17", context: { aiUse: { inputAssets: ["stems"], sourceDurationSeconds: 30, outputDurationSeconds: 60 } } },
      request: { territory: "US", intended_usage: "ai_grounded_generation", context: { tourStep: role, aiUse: { sourceDurationSeconds: 30 } } },
      policy: { version: 1, contract: { matrix: { usage: { ai_grounded_generation: "requires_approval" } },
        aiPolicy: { inputs: { stems: "requires_approval" }, limits: { maxSourceDurationSeconds: 30 } } } },
    })),
  };
}
const ok = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
let view: ReactTestRenderer;
afterEach(() => { if (view) act(() => view.unmount()); vi.unstubAllGlobals(); });
async function mount() {
  await act(async () => { view = create(<SandboxTour session={{ id: "guest-session" }} onConsole={vi.fn()}
    onSetup={vi.fn()} onSignOut={vi.fn()} onRestart={vi.fn()} onDownload={vi.fn()} />); });
}
function text() { return JSON.stringify(view.toJSON()); }
function nodeText(node: ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map(nodeText).join("");
}
function button(label: string) {
  const matches = view.root.findAllByType("button").filter(node => nodeText(node).includes(label));
  if (!matches[0]) throw new Error(`Missing button ${label}`);
  return matches[0];
}
async function click(label: string) { await act(async () => { button(label).props.onClick(); }); }

it("prepares the example and keeps the label and publisher decisions separate", async () => {
  const tour = fixture();
  const decisions: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init) => {
    if (url.endsWith("/decide")) {
      decisions.push(url);
      expect(JSON.parse(init.body)).toEqual(exampleApproval());
      tour.sides[0].permission.status = "approved";
      tour.sides[0].permission.receiptId = "receipt-label";
      return ok({ status: "approved" });
    }
    return ok(tour);
  }));
  await mount(); await click("Review a request"); await click("recording");
  expect(decisions).toEqual([`${API_BASE}/v1/permission-requests/request-label/decide`]);
  expect(text()).toContain("Recording decision recorded");
  expect(tour.sides[1].permission.status).toBe("pending");
});

it("recovers a committed approval after a lost response without submitting again", async () => {
  const tour = fixture();
  const decide = vi.fn(async () => {
    tour.sides[0].permission.status = "approved";
    tour.sides[0].permission.receiptId = "receipt-label";
    throw new TypeError("Connection dropped");
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/decide") ? decide() : ok(tour)));
  await mount(); await click("Review a request"); await click("recording");
  expect(decide).toHaveBeenCalledTimes(1);
  expect(text()).toContain("Recording decision recorded");
  expect(text()).not.toContain("Connection dropped");
});

it.each([403, 503])("keeps a %s failure distinct from a policy rejection", async status => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === `${API_BASE}/v1/permission-requests`
    ? ok({ detail: "Request unavailable" }, status) : ok(fixture())));
  await mount(); await click("Review a request"); await click("Request model training");
  expect(text()).toContain("Request unavailable");
  expect(text()).not.toContain("Stopped by the live permission check");
});

it("shows a live policy rejection and leaves the original request unchanged", async () => {
  const tour = fixture();
  const original = JSON.stringify(tour.sides[0].request);
  vi.stubGlobal("fetch", vi.fn(async (url: string, init) => {
    if (url === `${API_BASE}/v1/permission-requests`) {
      expect(JSON.parse(init.body).intended_usage).toBe("ai_model_training");
      return ok({ detail: { message: "The published policy blocks model training", policyEvaluation: ["operation:ai_model_training:blocked"] } }, 409);
    }
    return ok(tour);
  }));
  await mount(); await click("Review a request"); await click("Request model training");
  expect(text()).toContain("Stopped by the live permission check");
  expect(JSON.stringify(tour.sides[0].request)).toBe(original);
  expect(scopeProbe(tour.sides[0], "territory").context.tourStep).toBeUndefined();
});

it("recovers an interrupted initial preparation through the same endpoint", async () => {
  let attempts = 0;
  vi.stubGlobal("fetch", vi.fn(async () => ++attempts === 1 ? ok({ detail: "Preparation interrupted" }, 503) : ok(fixture())));
  await mount(); expect(text()).toContain("Preparation interrupted");
  await click("Reload example");
  expect(text()).toContain("Paper Skies"); expect(attempts).toBe(2);
});

it("verifies the exact receipt and changes only the in-memory test copy", async () => {
  const tour = fixture();
  tour.sides[0].permission.status = "approved"; tour.sides[0].permission.receiptId = "receipt-label";
  const receipt = { payload: { permission: { territory: "US" } }, proof: { signature: "original" } };
  const verifiedPayloads: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init) => {
    if (url === `${API_BASE}/v1/receipts/receipt-label`) return ok(receipt);
    if (url === `${API_BASE}/v1/receipts/verify`) {
      const supplied = JSON.parse(init.body).receipt; verifiedPayloads.push(supplied);
      const valid = supplied.payload.permission.territory === "US";
      return ok({ valid, payloadHashValid: valid, signatureValid: true, transparencyHashValid: true });
    }
    return ok(tour);
  }));
  await mount(); await click("Verify the decision"); await click("Test an altered copy");
  expect(verifiedPayloads).toHaveLength(2);
  expect(verifiedPayloads[0]).toEqual(receipt);
  expect(verifiedPayloads[1].payload.permission.territory).toBe("worldwide");
  expect(receipt.payload.permission.territory).toBe("US");
  expect(text()).toContain("Altered copy rejected");
});
