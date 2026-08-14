import { describe, expect, it } from "vitest";

import { isEmail, parseUserRole } from "./UserGate";

describe("demo identity input validation", () => {
  it.each(["@", "a@", "@example.com", "a b@example.com", "a@example"])(
    "rejects malformed email %s",
    (value) => expect(isEmail(value)).toBe(false),
  );

  it("accepts a normalized email shape", () => {
    expect(isEmail("artist@example.com")).toBe(true);
  });

  it("falls back safely for unknown persisted roles", () => {
    expect(parseUserRole("admin")).toBe("publisher");
    expect(parseUserRole(null)).toBe("publisher");
  });
});
