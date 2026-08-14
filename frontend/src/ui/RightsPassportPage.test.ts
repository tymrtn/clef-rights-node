import { describe, expect, it } from "vitest";

import { normalizePassportEditLink, restrictionDisplayState } from "./RightsPassportPage";

describe("passport restriction display", () => {
  it("never converts missing or unrecognized evidence into permission", () => {
    expect(restrictionDisplayState(undefined)).toBe("unknown");
    expect(restrictionDisplayState("")).toBe("unknown");
    expect(restrictionDisplayState("permitted")).toBe("unknown");
  });

  it.each(["allowed", "conditional", "denied"])("preserves recognized state %s", (state) => {
    expect(restrictionDisplayState(state)).toBe(state);
  });
});

describe("passport edit links", () => {
  const origin = "https://rights.example.com";

  it("accepts only same-origin detail routes with owner and key", () => {
    expect(normalizePassportEditLink("/?owner=rights%40example.com&key=work-1&view=detail", "rights@example.com", "work-1", origin)).toBe(
      "/?owner=rights%40example.com&key=work-1&view=detail",
    );
    expect(normalizePassportEditLink(`${origin}/?owner=rights%40example.com&key=work-1&view=detail`, "rights@example.com", "work-1", origin)).toBe(
      "/?owner=rights%40example.com&key=work-1&view=detail",
    );
  });

  it.each([
    "https://attacker.example/?owner=x&key=y&view=detail",
    "//attacker.example/?owner=x&key=y&view=detail",
    "javascript:alert(1)",
    "/?key=work-1&view=detail",
    "/?owner=rights%40example.com&key=work-1&view=passport",
  ])("rejects untrusted target %s", (target) => {
    expect(normalizePassportEditLink(target, "rights@example.com", "work-1", origin)).toBeNull();
  });

  it("rejects same-origin links for another owner or work", () => {
    expect(normalizePassportEditLink("/?owner=other%40example.com&key=work-1&view=detail", "rights@example.com", "work-1", origin)).toBeNull();
    expect(normalizePassportEditLink("/?owner=rights%40example.com&key=work-2&view=detail", "rights@example.com", "work-1", origin)).toBeNull();
  });
});
