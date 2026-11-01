import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { UserGate } from "./UserGate";

vi.mock("./ResultsTable", () => ({ ResultsTable: (props: any) => React.createElement("results-probe", props) }));
vi.mock("./RightsDrawer", () => ({ RightsDrawer: (props: any) => React.createElement("drawer-probe", props) }));
vi.mock("./BulkEditModal", () => ({ BulkEditModal: (props: any) => React.createElement("bulk-probe", props) }));
vi.mock("./DashboardPage", () => ({ DashboardPage: () => null }));
vi.mock("./IntegrationStatus", () => ({ IntegrationStatus: () => null }));
const ok = (data: unknown) => new Response(JSON.stringify(data), { status: 200 });
const record = (key: string) => ({ key, title: key, type: "work", raw: { workTitle: key } });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
let view: ReactTestRenderer;

beforeEach(() => {
  const values = new Map([["rc.ownerEmail", "owner-a@example.test"], ["rc.userEmail", "user-a@example.test"], ["rc.role", "publisher"]]);
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  vi.stubGlobal("window", { location: { search: "", pathname: "/" } });
});
afterEach(() => { if (view) act(() => view.unmount()); vi.unstubAllGlobals(); });
async function mount() { await act(async () => { view = create(<App />); }); }
function button(id: string) { return view.root.findByProps({ id }); }
function results() { return view.root.findByType("results-probe" as any); }
function fillSearch() {
  act(() => button("rc-search-title").props.onChange({ target: { value: "Fictional Song" } }));
}

describe("catalog identity and asynchronous view changes", () => {
  it("clears catalog, selection, editor and delayed results across sign-out and sign-in", async () => {
    const late = deferred<Response>(); let searches = 0;
    vi.stubGlobal("fetch", vi.fn(async url => {
      if (String(url).startsWith("/api/catalog/faceted")) return ++searches === 1 ? ok({ items: [record("mlc:a")] }) : late.promise;
      if (String(url).startsWith("/api/rights/by-key")) return ok({ contract: { marker: "owner-a" }, matrix: {}, version: 1 });
      return ok({ items: [] });
    }));
    await mount();
    await act(async () => { button("rc-mode-managed").props.onClick(); });
    expect(results().props.rows[0].key).toBe("mlc:a");
    await act(async () => { await results().props.onOpenDrawer(record("mlc:a")); });
    expect(view.root.findByType("drawer-probe" as any).props.data.contract.marker).toBe("owner-a");
    await act(async () => { button("rc-logout").props.onClick(); });
    expect(view.root.findAllByType("drawer-probe" as any)).toHaveLength(0);
    expect(view.root.findByType("bulk-probe" as any).props.open).toBe(false);
    await act(async () => { view.root.findByType(UserGate).props.onConfirm({ ownerEmail: "owner-b@example.test", userEmail: "user-b@example.test", role: "publisher" }); });
    expect(results().props.rows).toEqual([]);
    // Start a managed lookup for B, then sign out while it is still pending.
    await act(async () => { button("rc-mode-managed").props.onClick(); });
    await act(async () => { button("rc-logout").props.onClick(); });
    await act(async () => { view.root.findByType(UserGate).props.onConfirm({ ownerEmail: "owner-c@example.test", userEmail: "user-c@example.test", role: "publisher" }); });
    await act(async () => { late.resolve(ok({ items: [record("mlc:private-b")] })); });
    expect(results().props.rows).toEqual([]);
  });

  it.each(["managed-to-external", "external-to-managed"])("ignores responses from the previous catalog mode: %s", async direction => {
    const late = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async url => {
      if (String(url).startsWith("/api/catalog/faceted")) return direction === "managed-to-external" ? late.promise : ok({ items: [record("mlc:managed")] });
      if (String(url).includes("/api/mlc/search/songcode")) return direction === "external-to-managed" ? late.promise : ok({ results: [{ mlcSongCode: "external", workTitle: "External work" }] });
      return ok({ items: [] });
    }));
    await mount();
    let search: Promise<void> | undefined;
    if (direction === "managed-to-external") {
      await act(async () => { button("rc-mode-managed").props.onClick(); });
      await act(async () => { button("rc-mode-external").props.onClick(); });
      fillSearch();
      await act(async () => { await button("rc-search-button").props.onClick(); });
      await act(async () => { late.resolve(ok({ items: [record("mlc:obsolete")] })); });
      expect(results().props.rows.map((row: any) => row.key)).toEqual(["mlc:external"]);
    } else {
      fillSearch();
      await act(async () => { search = button("rc-search-button").props.onClick(); });
      await act(async () => { button("rc-mode-managed").props.onClick(); });
      await act(async () => { late.resolve(ok({ results: [{ mlcSongCode: "obsolete", workTitle: "Old result" }] })); await search; });
      expect(results().props.rows.map((row: any) => row.key)).toEqual(["mlc:managed"]);
    }
  });

  it("a delayed save cannot overwrite or close a replacement editor", async () => {
    const late = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async url => {
      if (String(url).startsWith("/api/catalog/faceted")) return ok({ items: [record("mlc:a"), record("mlc:b")] });
      if (String(url).startsWith("/api/rights/by-key")) return ok({ contract: { marker: String(url) }, matrix: {}, version: 1 });
      if (url === "/api/rights/save") return late.promise;
      return ok({ items: [] });
    }));
    await mount();
    await act(async () => { button("rc-mode-managed").props.onClick(); });
    await act(async () => { await results().props.onOpenDrawer(record("mlc:a")); });
    let save!: Promise<boolean>;
    await act(async () => { save = view.root.findByType("drawer-probe" as any).props.onSave({ marker: "saved-a" }); });
    await act(async () => { view.root.findByType("drawer-probe" as any).props.onClose(); });
    await act(async () => { await results().props.onOpenDrawer(record("mlc:b")); });
    await act(async () => { late.resolve(ok({ contract: { marker: "saved-a" }, matrix: {}, version: 2 })); expect(await save).toBe(false); });
    const editor = view.root.findByType("drawer-probe" as any);
    expect(editor.props.row.key).toBe("mlc:b");
    expect(editor.props.data.contract.marker).toContain("mlc%3Ab");
  });
});
