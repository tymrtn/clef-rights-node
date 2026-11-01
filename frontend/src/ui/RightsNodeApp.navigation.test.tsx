import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, expect, it, vi } from "vitest";
import { RightsNodeApp } from "./RightsNodeApp";
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

vi.mock("./SandboxTour", () => ({ SandboxTour: ({ onConsole, onSetup, onSignOut }: any) => <div>
  <button onClick={() => onConsole("label", "permissions")}>Inspect label</button>
  <button onClick={() => onConsole("publisher", "permissions")}>Inspect publisher</button>
  <button onClick={onSetup}>Set up an organization</button><button onClick={onSignOut}>Sign out</button>
</div> }));
const session = { id: "guest-session", email: "sandbox-test@sandbox.invalid", expires_at: "2099-01-01" };
const context = { user: { id: "guest", email: session.email, nodeRole: "admin" },
  organizations: ["label", "publisher"].map(role => ({ id: role, slug: role, name: role, role: "owner", profile: { organizationType: role } })) };
const ok = (data: unknown) => new Response(JSON.stringify(data), { status: 200 });
let view: ReactTestRenderer;
afterEach(() => { if (view) act(() => view.unmount()); vi.unstubAllGlobals(); });
async function mount() {
  const stored = new Map([["clef.rights.session", JSON.stringify(session)]]);
  vi.stubGlobal("sessionStorage", { getItem: (key: string) => stored.get(key), setItem: (key: string, value: string) => stored.set(key, value), removeItem: (key: string) => stored.delete(key) });
  vi.stubGlobal("window", { location: { search: "" } });
  await act(async () => { view = create(<RightsNodeApp />); });
}
async function click(label: string) { await act(async () => { view.root.findAllByType("button").find(node => node.children.includes(label))!.props.onClick(); }); }
function configure() {
  const pending: { resolve: (value: Response) => void; reject: (reason: Error) => void }[] = [];
  let sessionReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === `${API_BASE}/v1/node/info`) return ok({ deploymentMode: "public_sandbox", sandboxGuestAccess: true, softwareLicense: "AGPL-3.0-only" });
    if (url === `${API_BASE}/v1/session`) {
      sessionReads++;
      if (sessionReads === 1) return ok({ ...context, organizations: [] });
      if (sessionReads <= 3) return new Promise<Response>((resolve, reject) => pending.push({ resolve, reject }));
      return ok(context);
    }
    return ok({ permissionRequests: [] });
  }));
  return pending;
}

it.each(["success", "failure"])("preserves entered setup values after an older navigation's %s", async outcome => {
  const pending = configure(); await mount(); await click("Inspect label");
  await click("Set up an organization");
  const input = () => view.root.findByProps({ placeholder: "Label, publisher, PRO, collective, or artist" });
  act(() => input().props.onChange({ target: { value: "My fictional label" } }));
  await act(async () => outcome === "success" ? pending[0].resolve(ok(context)) : pending[0].reject(new Error("Obsolete navigation error")));
  expect(input().props.value).toBe("My fictional label");
  await click("← Return to the example catalog");
  expect(JSON.stringify(view.toJSON())).not.toContain("Obsolete navigation error");
});

it("keeps the newest organization destination when requests finish in reverse order", async () => {
  const pending = configure(); await mount(); await click("Inspect label"); await click("Inspect publisher");
  await act(async () => pending[1].resolve(ok(context)));
  expect(view.root.findByType("select").props.value).toBe("publisher");
  await act(async () => pending[0].resolve(ok(context)));
  expect(view.root.findByType("select").props.value).toBe("publisher");
});

it("does not restore organization data after sign-out while navigation is pending", async () => {
  const pending = configure(); await mount(); await click("Inspect label"); await click("Sign out");
  await act(async () => pending[0].resolve(ok(context)));
  expect(JSON.stringify(view.toJSON())).toContain("Explore the example catalog");
  expect(view.root.findAllByType("select")).toHaveLength(0);
});
