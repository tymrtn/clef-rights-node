import { describe, expect, it } from "vitest";

import { checkedJson } from "./http";

describe("checkedJson", () => {
  it("returns successful JSON", async () => {
    await expect(checkedJson(new Response('{"ok":true}', { status: 200 }), "Request")).resolves.toEqual({ ok: true });
  });

  it("preserves JSON error details", async () => {
    await expect(checkedJson(new Response('{"detail":"unavailable"}', { status: 503 }), "Request")).rejects.toThrow(
      "Request failed (503): unavailable",
    );
  });

  it("reports HTML and empty error responses by status", async () => {
    await expect(checkedJson(new Response("<h1>Bad gateway</h1>", { status: 502 }), "Request")).rejects.toThrow(
      "Request failed (502)",
    );
    await expect(checkedJson(new Response(null, { status: 504 }), "Request")).rejects.toThrow("Request failed (504)");
  });
});
