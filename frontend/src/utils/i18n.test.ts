import { beforeEach, describe, expect, it, vi } from "vitest";

import { getLocale, t } from "./i18n";

const values = new Map<string, string>();

beforeEach(() => {
  values.clear();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  });
});

describe("locale selection", () => {
  it("defaults missing and unsupported locales to English", () => {
    expect(getLocale()).toBe("en");
    values.set("rc.locale", "fr");
    expect(getLocale()).toBe("en");
  });

  it("normalizes Spanish locale casing", () => {
    values.set("rc.locale", "ES");
    expect(getLocale()).toBe("es");
    expect(t("gate.continue")).toBe("Continuar");
  });

  it("falls back to English when browser storage is unavailable", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new DOMException("Access denied", "SecurityError");
      },
    });
    expect(getLocale()).toBe("en");
    expect(t("gate.continue")).toBe("Continue");
  });
});

describe("translation fallback", () => {
  it("falls back to English and then to the untranslated key", () => {
    values.set("rc.locale", "es");
    expect(t("gate.demoWarning")).toBe("Demo identities are not credentials.");
    expect(t("missing.key")).toBe("missing.key");
  });
});
