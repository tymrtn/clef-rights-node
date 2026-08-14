import { beforeEach, describe, expect, it, vi } from "vitest";

import { safeStorageGet, safeStorageRemove, safeStorageSet } from "./storage";

const values = new Map<string, string>();

beforeEach(() => {
  values.clear();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
});

describe("safe browser storage", () => {
  it("reads, writes, and removes available values", () => {
    expect(safeStorageSet("local", "key", "value")).toBe(true);
    expect(safeStorageGet("local", "key")).toBe("value");
    expect(safeStorageRemove("local", "key")).toBe(true);
    expect(safeStorageGet("local", "key")).toBeNull();
  });

  it("turns access failures into non-fatal misses", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => { throw new DOMException("Denied", "SecurityError"); },
      setItem: () => { throw new DOMException("Denied", "SecurityError"); },
      removeItem: () => { throw new DOMException("Denied", "SecurityError"); },
    });
    expect(safeStorageGet("local", "key")).toBeNull();
    expect(safeStorageSet("local", "key", "value")).toBe(false);
    expect(safeStorageRemove("local", "key")).toBe(false);
  });
});
