import { describe, expect, it } from "vitest";

import { canOrganizationManageRights, catalogSelectionFromMlcResult, createAiPolicyDefaults, createPolicyDefaults, defaultControlledRightsForOrganizationType, isAiUsageKey, isPublicSandbox, localDateTimeInputValue, organizationConsoleScopeKey, policyEditorScopeKey, requiresOrganizationSetup } from "./RightsNodeApp";
import { onboardingStateClasses } from "./OnboardingChecklist";
import { isReadinessResultCurrent, readinessStateClasses, resolveRemediationHref } from "./DeploymentReadinessPanel";

describe("deployment identity", () => {
  it("identifies only the public synthetic sandbox", () => {
    expect(isPublicSandbox({ deploymentMode: "public_sandbox" })).toBe(true);
    expect(isPublicSandbox({ deploymentMode: "adopter_staging" })).toBe(false);
    expect(isPublicSandbox(null)).toBe(false);
  });
});

describe("operator readiness presentation", () => {
  it("resolves remediation instructions against the deployed source offer", () => {
    expect(resolveRemediationHref("docs/RAILWAY_DEPLOYMENT.md#configure-email", "https://github.com/example/node/tree/v1")).toBe(
      "https://github.com/example/node/tree/v1/docs/RAILWAY_DEPLOYMENT.md#configure-email",
    );
    expect(readinessStateClasses("blocked")).toContain("red");
    expect(readinessStateClasses("ready")).toContain("emerald");
    expect(isReadinessResultCurrent("2026-08-14T12:00:00Z", Date.parse("2026-08-14T12:00:59Z"))).toBe(true);
    expect(isReadinessResultCurrent("2026-08-14T12:00:00Z", Date.parse("2026-08-14T12:01:01Z"))).toBe(false);
  });

  it("distinguishes completed and pending onboarding evidence", () => {
    expect(onboardingStateClasses("complete")).toContain("emerald");
    expect(onboardingStateClasses("pending")).toContain("blue");
  });
});

describe("MLC catalog selection", () => {
  it("normalizes observed MLC metadata into a durable work selection", () => {
    expect(catalogSelectionFromMlcResult({ mlcSongCode: "123456789", workTitle: "Northbound", artist: "Avery North" })).toEqual({
      workKey: "mlc:123456789",
      workTitle: "Northbound",
      artistName: "Avery North",
    });
  });

  it("does not allow a registry result without a durable song code to become a policy key", () => {
    expect(catalogSelectionFromMlcResult({ workTitle: "Ambiguous Work", artist: "Several Artists" })).toBeNull();
  });
});

describe("policy editor tenant scope", () => {
  it("changes the React remount key when organizations change", () => {
    expect(policyEditorScopeKey("org-a")).not.toBe(policyEditorScopeKey("org-b"));
    expect(organizationConsoleScopeKey("org-a")).not.toBe(organizationConsoleScopeKey("org-b"));
  });
});

describe("publication reporting time", () => {
  it("seeds datetime-local fields with local wall time rather than UTC text", () => {
    const instant = new Date("2026-07-15T18:37:00Z");
    expect(localDateTimeInputValue(instant, 420)).toBe("2026-07-15T11:37");
    expect(localDateTimeInputValue(instant, -120)).toBe("2026-07-15T20:37");
  });
});

describe("operator onboarding", () => {
  it("does not force a node operator to create a rights-holding organization", () => {
    expect(requiresOrganizationSetup({ user: { id: "operator", email: "operator@example.test", nodeRole: "admin" }, organizations: [] })).toBe(false);
    expect(requiresOrganizationSetup({ user: { id: "member", email: "member@example.test", nodeRole: "member" }, organizations: [] })).toBe(true);
    expect(requiresOrganizationSetup({ user: { id: "guest", email: "sandbox-123@sandbox.invalid", nodeRole: "admin" }, organizations: [] })).toBe(true);
  });

  it("uses conservative type-specific rights suggestions", () => {
    expect(defaultControlledRightsForOrganizationType("label")).toEqual(["master"]);
    expect(defaultControlledRightsForOrganizationType("publisher")).toEqual(["composition", "lyrics"]);
    expect(defaultControlledRightsForOrganizationType("pro")).toEqual(["composition", "performance"]);
    expect(defaultControlledRightsForOrganizationType("cmo")).toEqual(["composition", "performance"]);
    expect(defaultControlledRightsForOrganizationType("requester")).toEqual([]);
  });
});

describe("requester organizations", () => {
  it("cannot expose rightsholder policy and authority controls", () => {
    expect(canOrganizationManageRights({ id: "requester", slug: "requester", name: "Studio", role: "owner", profile: { organizationType: "requester" } as any })).toBe(false);
    expect(canOrganizationManageRights({ id: "label", slug: "label", name: "Label", role: "owner", profile: { organizationType: "label" } as any })).toBe(true);
  });
});

describe("organization policy defaults", () => {
  it("treats the legacy recursive-training operation as AI scope", () => {
    expect(isAiUsageKey("ai_training_recursive")).toBe(true);
    expect(isAiUsageKey("ai_grounded_generation")).toBe(true);
    expect(isAiUsageKey("derivative_remix")).toBe(false);
  });

  it("routes nuanced AI uses to review without permitting open-weight models", () => {
    const defaults = createPolicyDefaults("review_each_ai_use");
    expect(defaults.usage.ai_grounded_generation).toBe("requires_approval");
    expect(defaults.usage.ai_embedding_creation).toBe("requires_approval");
    expect(defaults.aiPolicy.inputs.stems).toBe("requires_approval");
    expect(defaults.aiPolicy.inputs.lyrics).toBe("requires_approval");
    expect(defaults.aiPolicy.modelScopes.public_or_open_weights).toBe("blocked");
  });

  it("treats blank numerical limits as terms to settle, not unlimited grants", () => {
    const policy = createAiPolicyDefaults();
    expect(policy.limits.maxSourceDurationSeconds).toBeNull();
    expect(policy.limits.embeddingRetentionDays).toBeNull();
    expect(policy.safeguards.provenanceReceipt).toBe(true);
    expect(policy.safeguards.deletionAttestation).toBe(true);
  });

  it("can start with every AI operation and source asset blocked", () => {
    const defaults = createPolicyDefaults("block_all_ai");
    expect(defaults.usage.ai_model_training).toBe("blocked");
    expect(defaults.aiPolicy.inputs.full_mix).toBe("blocked");
    expect(defaults.aiPolicy.modelScopes.private_single_tenant).toBe("blocked");
  });
});
