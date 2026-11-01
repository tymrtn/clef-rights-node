import { describe, expect, it } from "vitest";

import {
  canSaveValidatedDraft,
  checkedCollaborationJson,
  isCurrentValidation,
  normalizeRestrictionState,
} from "./RightsDrawer";

describe("collaboration response handling", () => {
  it("returns successful refresh data", async () => {
    const response = new Response('{"items":[{"id":"approval-1"}]}', { status: 200 });
    await expect(checkedCollaborationJson(response, "Approval list refresh")).resolves.toEqual({
      items: [{ id: "approval-1" }],
    });
  });

  it("rejects a failed refresh before callers replace existing state", async () => {
    const response = new Response('{"detail":"session expired"}', {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
    await expect(checkedCollaborationJson(response, "Approval list refresh")).rejects.toThrow(
      "Approval list refresh failed (401): session expired",
    );
  });
});

describe("draft validation ordering", () => {
  it("accepts only the latest validation request", () => {
    expect(isCurrentValidation(2, 2)).toBe(true);
    expect(isCurrentValidation(1, 2)).toBe(false);
  });

  it("fails closed when validation is pending or unavailable", () => {
    expect(canSaveValidatedDraft("idle")).toBe(false);
    expect(canSaveValidatedDraft("pending")).toBe(false);
    expect(canSaveValidatedDraft("unavailable")).toBe(false);
    expect(canSaveValidatedDraft("valid")).toBe(true);
  });
});

describe("restriction evidence", () => {
  it("never turns missing or unrecognized evidence into permission", () => {
    expect(normalizeRestrictionState(undefined)).toBe("unknown");
    expect(normalizeRestrictionState("legacy_allow")).toBe("unknown");
    expect(normalizeRestrictionState("allowed")).toBe("allowed");
    expect(normalizeRestrictionState("conditional")).toBe("conditional");
    expect(normalizeRestrictionState("denied")).toBe("denied");
  });
});
