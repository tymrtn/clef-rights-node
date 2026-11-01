import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  deepLinkOwnerMatchesSession,
  normaliseKey,
  readStoredEmail,
  shouldSearchSongCode,
} from "./App";
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

describe("external catalog identity", () => {
  it("keeps a work and its recordings in separate namespaces", () => {
    const shared = { mlcSongCode: "MLC-1", title: "Home" };
    expect(normaliseKey(shared, "work")).toBe("mlc:MLC-1");
    expect(normaliseKey({ ...shared, isrc: "USAAA2600001" }, "recording")).toBe(
      "isrc:USAAA2600001"
    );
    expect(normaliseKey({ ...shared, isrc: "USAAA2600002" }, "recording")).toBe(
      "isrc:USAAA2600002"
    );
  });

  it("does not make an empty song-code request for artist-only search", () => {
    expect(shouldSearchSongCode({})).toBe(false);
    expect(shouldSearchSongCode({ title: "Home" })).toBe(true);
    expect(shouldSearchSongCode({ publisher: "Example Music" })).toBe(true);
  });
});

describe("owner-scoped deep links", () => {
  it("waits for the referenced organization instead of discarding the link", () => {
    expect(deepLinkOwnerMatchesSession("rights@example.com", null)).toBe(false);
    expect(deepLinkOwnerMatchesSession("rights@example.com", "other@example.com")).toBe(false);
    expect(deepLinkOwnerMatchesSession("rights@example.com", "rights@example.com")).toBe(true);
    expect(deepLinkOwnerMatchesSession(undefined, null)).toBe(true);
  });
});
