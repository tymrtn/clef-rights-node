import { afterEach, describe, expect, it, vi } from "vitest";

import {
  approvalSummary,
  canExecuteErasure,
  canSaveSettings,
  canWithdrawPublicSummary,
  disclosureSummary,
  executeErasureRequest,
  executionOutcomeFor,
  exportFileName,
  getPrivacyExportPage,
  getPrivacyOverview,
  isPrivacyAdministrator,
  latestRequestAccepts,
  OPERATOR_FOLLOWUP,
  organizationHasApproved,
  parseRetentionDays,
  privacyScopeKey,
  publicSummaryLinks,
  requiresPublicationConfirmation,
  resolveApiUrl,
  retentionSummary,
  settingsPayload,
  structuredFailureDetail,
  updatePrivacySettings,
  type ErasurePreview,
  type ErasureRequest,
  type ExecutionOutcome,
  type ReceiptDisclosure,
} from "./PrivacyPanel";

function request(overrides: Partial<ErasureRequest> = {}): ErasureRequest {
  return {
    id: "era_01",
    kind: "receipt_copy",
    resourceId: "rcpt_01",
    status: "awaiting_approval",
    requiredOrganizationIds: ["org-authority", "org-requester"],
    approvedOrganizationIds: [],
    createdAt: "2026-09-15T10:00:00Z",
    completedAt: null,
    ...overrides,
  };
}

function preview(overrides: Partial<ErasurePreview> = {}): ErasurePreview {
  return {
    request: request(),
    willErase: ["stored_receipt_payload", "commitment_opening"],
    retained: ["audit_payload_hash"],
    blockedBy: [],
    canExecute: true,
    retainUntil: null,
    legalHold: false,
    ...overrides,
  };
}

function disclosure(overrides: Partial<ReceiptDisclosure> = {}): ReceiptDisclosure {
  return {
    publicReceiptId: "pub_01",
    publicUrl: null,
    published: false,
    withdrawn: false,
    privateCopyErased: false,
    retainUntil: null,
    commitmentOpening: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("retention controls", () => {
  it("treats an empty field as manual retention review rather than immediate deletion", () => {
    expect(parseRetentionDays("")).toEqual({ ok: true, days: null });
    expect(parseRetentionDays("   ")).toEqual({ ok: true, days: null });
    expect(retentionSummary(null)).toContain("by hand");
  });

  it("accepts whole days inside the supported range", () => {
    expect(parseRetentionDays("30")).toEqual({ ok: true, days: 30 });
    expect(parseRetentionDays(" 36500 ")).toEqual({ ok: true, days: 36500 });
  });

  it("rejects zero, fractional, negative, and oversized durations", () => {
    for (const value of ["0", "-1", "12.5", "36501", "ninety"]) {
      expect(parseRetentionDays(value).ok).toBe(false);
    }
  });

  it("states that the longest selected duration governs", () => {
    expect(retentionSummary(1)).toContain("1 day ");
    expect(retentionSummary(90)).toContain("90 days");
    expect(retentionSummary(90)).toContain("longer duration governs");
  });
});

describe("public receipt publication", () => {
  it("requires an explicit confirmation only when publication is being turned on", () => {
    expect(requiresPublicationConfirmation(false, true)).toBe(true);
    expect(requiresPublicationConfirmation(true, true)).toBe(false);
    expect(requiresPublicationConfirmation(true, false)).toBe(false);
    expect(requiresPublicationConfirmation(false, false)).toBe(false);
  });

  it("sends the optimistic-concurrency version with the settings body", () => {
    expect(settingsPayload({ publishPublicReceipts: true, receiptRetentionDays: null, legalHold: false }, 4)).toEqual({
      publish_public_receipts: true,
      receipt_retention_days: null,
      legal_hold: false,
      expected_version: 4,
    });
  });
});

describe("erasure approvals", () => {
  it("counts one approval per required party", () => {
    expect(approvalSummary(request())).toBe("Approved by 0 of 2 required organizations");
    expect(approvalSummary(request({ approvedOrganizationIds: ["org-authority", "org-authority"] }))).toBe("Approved by 1 of 2 required organizations");
    expect(approvalSummary(request({ approvedOrganizationIds: ["org-authority", "org-outsider"] }))).toBe("Approved by 1 of 2 required organizations");
  });

  it("knows when the active organization has already approved", () => {
    expect(organizationHasApproved(request({ approvedOrganizationIds: ["org-authority"] }), "org-authority")).toBe(true);
    expect(organizationHasApproved(request({ approvedOrganizationIds: ["org-authority"] }), "org-requester")).toBe(false);
  });
});

describe("erasure execution gate", () => {
  it("requires the exact request ID before the final click", () => {
    expect(canExecuteErasure(preview(), "era_01")).toBe(true);
    expect(canExecuteErasure(preview(), "  era_01  ")).toBe(true);
    expect(canExecuteErasure(preview(), "era_02")).toBe(false);
    expect(canExecuteErasure(preview(), "")).toBe(false);
    expect(canExecuteErasure(null, "era_01")).toBe(false);
  });

  it("keeps the button closed while a hold, a missing approval, or the server gate applies", () => {
    expect(canExecuteErasure(preview({ legalHold: true }), "era_01")).toBe(false);
    expect(canExecuteErasure(preview({ blockedBy: ["org-requester approval"] }), "era_01")).toBe(false);
    expect(canExecuteErasure(preview({ canExecute: false }), "era_01")).toBe(false);
  });
});

describe("privacy panel visibility", () => {
  it("shows the controls to an organization owner or administrator only", () => {
    expect(isPrivacyAdministrator("owner")).toBe(true);
    expect(isPrivacyAdministrator("admin")).toBe(true);
    expect(isPrivacyAdministrator("rights_manager")).toBe(false);
    expect(isPrivacyAdministrator("member")).toBe(false);
  });
});

describe("organization scope race protection", () => {
  it("keeps only the newest response for the organization still on screen", () => {
    const first = privacyScopeKey("org-a");
    const second = privacyScopeKey("org-b");
    expect(first).not.toBe(second);
    expect(latestRequestAccepts(2, 2, second, second)).toBe(true);
    expect(latestRequestAccepts(1, 2, second, second)).toBe(false);
    expect(latestRequestAccepts(2, 2, first, second)).toBe(false);
  });
});

describe("export download", () => {
  it("names each page after the organization, resource, and page number", () => {
    expect(exportFileName("org-authority", "receipts", 2)).toBe("clef-org-authority-receipts-page-2.json");
    expect(exportFileName("Org Authority/1", "audit", 1)).toBe("clef-org-authority-1-audit-page-1.json");
  });
});

describe("receipt disclosure summary", () => {
  it("separates public withdrawal from private erasure", () => {
    expect(disclosureSummary(disclosure({ published: true, withdrawn: true })).join(" ")).toContain("Copies already distributed stay");
    expect(disclosureSummary(disclosure({ privateCopyErased: true })).join(" ")).toContain("Originals exported earlier still verify");
    expect(disclosureSummary(disclosure({ privateCopyErased: true })).join(" ")).toContain("historic payload hash stays in the audit chain");
  });

  it("always points at the live status endpoint for the current state", () => {
    expect(disclosureSummary(disclosure({ published: true })).join(" ")).toContain("live status endpoint");
  });

  it("labels the commitment opening as private evidence the panel renders below the summary", () => {
    const lines = disclosureSummary(disclosure({ published: true, commitmentOpening: { nonce: "a".repeat(64), algorithm: "CLEF-PRIVATE-RECEIPT-SHA256-1" } })).join(" ");
    expect(lines).toContain("CLEF-PRIVATE-RECEIPT-SHA256-1 opening shown below");
    expect(lines).toContain("entitled to the private record");
    expect(lines).not.toContain("shown here");
  });

  it("describes a legacy receipt that carries no public identifier", () => {
    expect(disclosureSummary(disclosure({ publicReceiptId: null })).join(" ")).toContain("lives in authenticated records");
  });
});

describe("settings save gate", () => {
  function gate(overrides: Partial<Parameters<typeof canSaveSettings>[0]> = {}) {
    return canSaveSettings({
      hasSettings: true,
      retentionValid: true,
      saving: false,
      needsPublicationConfirmation: false,
      publicationConfirmed: false,
      ...overrides,
    });
  }

  it("opens once the loaded settings and a valid retention value are in hand", () => {
    expect(gate()).toBe(true);
    expect(gate({ hasSettings: false })).toBe(false);
    expect(gate({ retentionValid: false })).toBe(false);
    expect(gate({ saving: true })).toBe(false);
  });

  it("holds a publication change until the confirmation is checked, whichever way the form is submitted", () => {
    expect(gate({ needsPublicationConfirmation: true })).toBe(false);
    expect(gate({ needsPublicationConfirmation: true, publicationConfirmed: true })).toBe(true);
  });
});

describe("execution outcome retention", () => {
  it("keeps the erased result on its own request while the preview behind it refreshes", () => {
    const outcome: ExecutionOutcome = { requestId: "era_01", status: "erased", erased: ["stored_receipt_payload"], retained: ["audit_payload_hash"] };
    expect(executionOutcomeFor(outcome, "era_01")).toBe(outcome);
    expect(executionOutcomeFor(outcome, "era_02")).toBe(null);
    expect(executionOutcomeFor(null, "era_01")).toBe(null);
  });

  it("keeps a refused execution visible instead of dropping it into a cleared preview", () => {
    const failure: ExecutionOutcome = { requestId: "era_01", status: "failed", message: "Erase eligible stored copies failed (409): legal hold active" };
    expect(executionOutcomeFor(failure, "era_01")).toBe(failure);
    expect(executionOutcomeFor(failure, "era_02")).toBe(null);
  });
});

describe("public summary links", () => {
  it("resolves an API path against the API origin rather than the console origin", () => {
    expect(resolveApiUrl("https://node.example", "/v1/public/receipts/pub_01")).toBe("https://node.example/v1/public/receipts/pub_01");
    expect(resolveApiUrl("https://node.example/", "/v1/public/receipts/pub_01")).toBe("https://node.example/v1/public/receipts/pub_01");
    expect(resolveApiUrl("/api", "/v1/public/receipts/pub_01")).toBe("/api/v1/public/receipts/pub_01");
    expect(resolveApiUrl("", "/v1/public/receipts/pub_01")).toBe("/v1/public/receipts/pub_01");
    expect(resolveApiUrl("https://node.example", "v1/public/receipts/pub_01")).toBe("https://node.example/v1/public/receipts/pub_01");
  });

  it("leaves an absolute URL from the API untouched", () => {
    expect(resolveApiUrl("https://node.example", "https://public.example/v1/public/receipts/pub_01")).toBe("https://public.example/v1/public/receipts/pub_01");
  });

  it("offers the summary at issue and the current status endpoint together", () => {
    expect(publicSummaryLinks("https://node.example", disclosure({ publicUrl: "/v1/public/receipts/pub_01", published: true }))).toEqual({
      summary: "https://node.example/v1/public/receipts/pub_01",
      status: "https://node.example/v1/public/receipts/pub_01/status",
    });
  });

  it("offers no link when this node serves no public summary", () => {
    expect(publicSummaryLinks("https://node.example", disclosure())).toBe(null);
    expect(publicSummaryLinks("https://node.example", disclosure({ withdrawn: true }))).toBe(null);
  });
});

describe("public withdrawal gate", () => {
  const published = disclosure({ published: true, publicUrl: "/v1/public/receipts/pub_01" });

  it("opens only for the inspected receipt this node currently publishes", () => {
    expect(canWithdrawPublicSummary(published, "rcpt_01", "rcpt_01")).toBe(true);
    expect(canWithdrawPublicSummary(published, "rcpt_01", "  rcpt_01  ")).toBe(true);
  });

  it("closes as soon as the typed ID stops matching the inspected receipt", () => {
    expect(canWithdrawPublicSummary(published, "rcpt_01", "rcpt_02")).toBe(false);
    expect(canWithdrawPublicSummary(published, "", "rcpt_01")).toBe(false);
    expect(canWithdrawPublicSummary(published, "rcpt_01", "")).toBe(false);
    expect(canWithdrawPublicSummary(null, "rcpt_01", "rcpt_01")).toBe(false);
  });

  it("closes for a receipt with no public summary to withdraw", () => {
    expect(canWithdrawPublicSummary(disclosure(), "rcpt_01", "rcpt_01")).toBe(false);
    expect(canWithdrawPublicSummary(disclosure({ published: true, withdrawn: true }), "rcpt_01", "rcpt_01")).toBe(false);
  });
});

describe("operator follow-up checklist", () => {
  it("names the database residue and the backup replay the API cannot reach", () => {
    const text = OPERATOR_FOLLOWUP.join(" ");
    expect(text).toContain("write-ahead logs");
    expect(text).toContain("read replicas");
    expect(text).toContain("replay completed erasure requests");
    expect(text).toContain("Webhook payloads already accepted");
  });
});

describe("privacy API calls", () => {
  function stubFetch(body: unknown, status = 200) {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
    });
    return calls;
  }

  it("authenticates with the console session header", async () => {
    const calls = stubFetch({ settings: { publishPublicReceipts: false, receiptRetentionDays: null, legalHold: false, version: 1 }, publicReceiptFields: [], audioHandling: "external", erasureScopes: [] });
    await getPrivacyOverview("https://node.example", "sess_1", "org a");
    expect(calls[0].url).toBe("https://node.example/v1/organizations/org%20a/privacy");
    expect(calls[0].init?.headers).toMatchObject({ "X-Session-Id": "sess_1" });
  });

  it("sends the settings update as the pinned snake_case body", async () => {
    const calls = stubFetch({ settings: { publishPublicReceipts: true, receiptRetentionDays: 30, legalHold: false, version: 2 }, publicReceiptFields: [], audioHandling: "external", erasureScopes: [] });
    await updatePrivacySettings("https://node.example", "sess_1", "org-1", { publishPublicReceipts: true, receiptRetentionDays: 30, legalHold: false }, 1);
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ publish_public_receipts: true, receipt_retention_days: 30, legal_hold: false, expected_version: 1 });
  });

  it("pages an export with an explicit limit and cursor", async () => {
    const calls = stubFetch({ schemaVersion: "clef.privacy-export.v1", organizationId: "org-1", resource: "receipts", records: [], nextCursor: null, exportedAt: "2026-09-15T10:00:00Z" });
    await getPrivacyExportPage("https://node.example", "sess_1", "org-1", "receipts", "cursor 2");
    expect(calls[0].url).toBe("https://node.example/v1/organizations/org-1/privacy/export?resource=receipts&limit=100&cursor=cursor+2");
  });

  it("confirms the request ID in the execute body", async () => {
    const calls = stubFetch({ request: request(), erased: ["stored_receipt_payload"], retained: ["audit_payload_hash"] });
    await executeErasureRequest("https://node.example", "sess_1", "org-1", "era_01");
    expect(calls[0].url).toBe("https://node.example/v1/organizations/org-1/privacy/requests/era_01/execute");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ confirm_request_id: "era_01" });
  });

  it("names the remaining blockers when the node refuses an execution", async () => {
    expect(structuredFailureDetail({ detail: { message: "Erasure is blocked", blockedBy: ["requester_approval", "minimum_retention"] } }))
      .toBe("Erasure is blocked: requester approval, minimum retention");
    expect(structuredFailureDetail({ detail: "legal hold active" })).toBe("");
    expect(structuredFailureDetail(null)).toBe("");

    stubFetch({ detail: { message: "Erasure is blocked", blockedBy: ["requester_approval"] } }, 409);
    await expect(executeErasureRequest("https://node.example", "sess_1", "org-1", "era_01")).rejects.toThrow(
      "Erase eligible stored copies failed (409): Erasure is blocked: requester approval",
    );
  });

  it("reports an API refusal instead of treating it as success", async () => {
    stubFetch({ detail: "legal hold active" }, 409);
    await expect(executeErasureRequest("https://node.example", "sess_1", "org-1", "era_01")).rejects.toThrow("Erase eligible stored copies failed (409): legal hold active");
  });
});
