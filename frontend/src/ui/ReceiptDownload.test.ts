import { afterEach, expect, it, vi } from "vitest";
import { downloadPrivateReceipt } from "./RightsNodeApp";
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("downloads the authorized signed receipt unchanged without placing a credential in a URL", async () => {
  vi.useFakeTimers();
  const receipt = { payload: { terms: "synthetic private terms" }, proof: { signature: "synthetic-signature" } };
  const fetcher = vi.fn(async () => new Response(JSON.stringify(receipt), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  let saved: Blob | undefined;
  vi.spyOn(URL, "createObjectURL").mockImplementation(blob => { saved = blob as Blob; return "blob:synthetic-download"; });
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const link = { href: "", download: "", click: vi.fn(), remove: vi.fn() };
  vi.stubGlobal("document", { createElement: () => link, body: { append: vi.fn() } });
  await downloadPrivateReceipt("receipt/1", { id: "synthetic-secret", email: "party@example.test", expires_at: "2027-01-01" });
  const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe(`${API_BASE}/v1/receipts/receipt%2F1`);
  expect(new Headers(init.headers).get("X-Session-Id")).toBe("synthetic-secret");
  expect(link.href).toBe("blob:synthetic-download");
  expect(JSON.parse(await saved!.text())).toEqual(receipt);
  expect(link.download).toBe("clef-receipt-receipt_1.json");
  expect(link.click).toHaveBeenCalledOnce();
  vi.advanceTimersByTime(1000);
  expect(revoke).toHaveBeenCalledWith("blob:synthetic-download");
});

it("does not generate a download when party authorization fails", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response('{"detail":"Party access required"}', { status: 403 })));
  const createUrl = vi.spyOn(URL, "createObjectURL");
  await expect(downloadPrivateReceipt("receipt-1", { id: "outsider-session", email: "outsider@example.test", expires_at: "2027-01-01" })).rejects.toThrow("Party access required");
  expect(createUrl).not.toHaveBeenCalled();
});
