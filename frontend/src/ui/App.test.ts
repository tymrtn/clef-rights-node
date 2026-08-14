import { beforeEach, describe, expect, it, vi } from "vitest";

import { readStoredEmail } from "./App";
import { checkedJson } from "../utils/http";

const values = new Map<string, string>();

beforeEach(() => {
  values.clear();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
});

describe("stored demo identity", () => {
  it("returns valid normalized email values", () => {
    values.set("rc.ownerEmail", "  rights@example.com  ");
    expect(readStoredEmail("rc.ownerEmail")).toBe("rights@example.com");
  });

  it("removes malformed legacy values instead of forwarding them", () => {
    values.set("rc.ownerEmail", "@");
    expect(readStoredEmail("rc.ownerEmail")).toBeNull();
    expect(values.has("rc.ownerEmail")).toBe(false);
  });
});

describe("checked API responses", () => {
  it("returns successful JSON", async () => {
    await expect(checkedJson(new Response('{"items":[]}', { status: 200 }), "Search")).resolves.toEqual({ items: [] });
  });

  it("rejects error JSON instead of treating it as empty success", async () => {
    const response = new Response('{"detail":"registry unavailable"}', {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
    await expect(checkedJson(response, "Search")).rejects.toThrow("Search failed (503): registry unavailable");
  });
});
