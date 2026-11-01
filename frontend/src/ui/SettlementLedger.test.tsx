import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettlementLedgerCore } from "./RightsNodeApp";

const session = { id: "synthetic-session", email: "reviewer@example.test", expires_at: "2027-01-01" };
const permission = { id: "permission-1", settlementId: "settlement-1", receiptId: "receipt-1", directions: ["inbound"], termStart: "2026-01-01", termEnd: "2026-12-31" } as any;
const ledger = {
  id: "settlement-1", currency: "USD", minimumCommitmentMinor: 1000, royaltyRateBps: 1000,
  royaltyBasis: "net_revenue", assertionType: "provisional", ledgerDigest: "synthetic-digest",
  beneficiaries: [], entries: [], reconciliations: [],
  totals: { reserveMinor: 0, royaltyAccruedMinor: 0, obligationMinor: 1000, paymentReceivedMinor: 0, payoutMinor: 0, beneficiaries: [] },
};
const ok = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const event = { preventDefault() {} };
let view: ReactTestRenderer | undefined;

afterEach(() => { if (view) act(() => view!.unmount()); view = undefined; vi.unstubAllGlobals(); });

async function mount(props = permission) {
  await act(async () => { view = create(<SettlementLedgerCore session={session} permission={props} />); });
  return view!;
}
function setField(label: string, value: string) {
  act(() => { view!.root.findByProps({ "aria-label": label }).props.onChange({ target: { value } }); });
}
function entryForm() { return view!.root.findByProps({ "aria-label": "Financial entry amount" }).parent!; }
function royaltyForm() { return view!.root.findByProps({ "aria-label": "Royalty basis amount" }).parent!; }
function fillEntry(amount = "1000") {
  setField("Financial entry amount", amount);
  setField("External financial reference", "synthetic-bank-ref");
  setField("Financial evidence reference", "synthetic-evidence");
}
function text() { return JSON.stringify(view!.toJSON()); }

describe("settlement operations through the rendered forms", () => {
  it.each(["entry", "royalty", "reconciliation"])("retries %s with identical bytes after the server commits but the response is lost", async (kind) => {
    const requests: string[] = [];
    const effects = new Set<string>();
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
      if (init?.method !== "POST") return ok(ledger);
      requests.push(init.body);
      effects.add(JSON.parse(init.body).idempotency_key);
      if (requests.length === 1) throw new TypeError("Network response lost");
      return ok({ id: "entry-1", assertionType: "provisional" });
    }));
    await mount();
    let submit: () => Promise<void>;
    if (kind === "entry") {
      fillEntry();
      submit = () => entryForm().props.onSubmit(event);
    } else if (kind === "royalty") {
      setField("Royalty basis amount", "10000");
      setField("Royalty statement reference", "synthetic-statement");
      submit = () => royaltyForm().props.onSubmit(event);
    } else {
      submit = () => view!.root.findAllByType("button").find(button => button.children.includes("Reconcile current ledger"))!.props.onClick();
    }
    await act(submit);
    expect(text()).toContain("Retry with the same details");
    await act(submit);
    expect(requests).toHaveLength(2);
    expect(requests[1]).toBe(requests[0]);
    expect(effects.size).toBe(1);
  });

  it("blocks a changed submission while the preceding outcome is uncertain", async () => {
    const post = vi.fn(async () => { throw new TypeError("Lost response"); });
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => init?.method === "POST" ? post() : ok(ledger)));
    await mount(); fillEntry();
    await act(async () => { await entryForm().props.onSubmit(event); });
    setField("Financial entry amount", "2000");
    await act(async () => { await entryForm().props.onSubmit(event); });
    expect(post).toHaveBeenCalledTimes(1);
    expect(text()).toContain("Retry its unchanged details");
  });

  it("ignores a second click while a request is in flight", async () => {
    let finish!: (response: Response) => void;
    const post = vi.fn(() => new Promise<Response>(resolve => { finish = resolve; }));
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => init?.method === "POST" ? post() : ok(ledger)));
    await mount(); fillEntry();
    let request!: Promise<void>;
    await act(async () => {
      request = entryForm().props.onSubmit(event);
      await entryForm().props.onSubmit(event);
    });
    expect(post).toHaveBeenCalledTimes(1);
    expect(entryForm().findByType("button").props.disabled).toBe(true);
    await act(async () => { finish(ok({ id: "entry-1" })); await request; });
  });

  it("distinguishes a successful write from a failed refresh and never resubmits on refresh", async () => {
    let reads = 0;
    const writes: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
      if (init?.method === "POST") { writes.push(init.body); return ok({ id: "entry-1" }); }
      if (++reads === 2) throw new TypeError("Read unavailable");
      return ok(ledger);
    }));
    await mount(); fillEntry();
    await act(async () => { await entryForm().props.onSubmit(event); });
    expect(text()).toContain("Recorded successfully");
    expect(view!.root.findByProps({ "aria-label": "Financial entry amount" }).props.value).toBe("");
    await act(async () => { await view!.root.findAllByType("button").find(button => button.children.includes("Refresh ledger"))!.props.onClick(); });
    expect(writes).toHaveLength(1);
  });

  it("keeps newly created settlement terms visible after the first entry", async () => {
    let created = false;
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (url, init) => {
      if (init?.method === "POST" && String(url).endsWith("/settlement")) { created = true; return ok(ledger, 201); }
      if (init?.method === "POST") return ok({ id: "entry-1" });
      expect(created).toBe(true); reads++; return ok(ledger);
    }));
    await mount({ ...permission, settlementId: undefined });
    setField("Beneficiary 1 name", "Fictional Artist");
    setField("Beneficiary 1 identifier", "synthetic:artist");
    const checkbox = view!.root.findAllByType("input").find(input => input.props.type === "checkbox" && input.props.required)!;
    act(() => checkbox.props.onChange({ target: { checked: true } }));
    await act(async () => { await view!.root.findByType("form").props.onSubmit(event); });
    expect(text()).toContain("Settlement ledger");
    fillEntry();
    await act(async () => { await entryForm().props.onSubmit(event); });
    expect(reads).toBe(1);
    expect(text()).toContain("Settlement ledger");
    expect(text()).not.toContain("Define immutable settlement terms");
  });
});
