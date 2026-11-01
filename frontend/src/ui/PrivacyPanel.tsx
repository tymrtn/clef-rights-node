import React from "react";

import { checkedJson } from "../utils/http";


export const PRIVACY_EXPORT_RESOURCES = ["clients", "catalog", "policies", "claims", "permissions", "receipts", "members", "audit"] as const;
export type PrivacyExportResource = (typeof PRIVACY_EXPORT_RESOURCES)[number];

export const ERASURE_KINDS = ["receipt_copy", "client_contact_email"] as const;
export type ErasureKind = (typeof ERASURE_KINDS)[number];

export const MAXIMUM_RETENTION_DAYS = 36500;

const RESOURCE_LABELS: Record<PrivacyExportResource, string> = {
  clients: "Managed clients",
  catalog: "Catalog works and recordings",
  policies: "Current policy records",
  claims: "Authority claims and evidence references",
  permissions: "Permission requests and decisions",
  receipts: "Signed receipts",
  members: "Organization members",
  audit: "Audit events",
};

/** Locations this API does not reach. The panel lists them inline because the procedure document ships with the node rather than a published URL. */
export const OPERATOR_FOLLOWUP = [
  "Contracts, authority documents, and catalog import batches held by the operator",
  "Permission history, publication reports, and compliance reviews",
  "Financial and settlement entries, DDEX payloads, and recorded acknowledgements",
  "Webhook payloads already accepted by a receiver, under the agreement with that receiver",
  "Exports downloaded from this panel, under the procedure of wherever the file landed",
  "Database write-ahead logs, freed table pages, and read replicas, until each is overwritten or rebuilt",
  "Encrypted backups: let them age out on their declared schedule, and replay completed erasure requests against any restore taken before the erasure ran",
] as const;

const ERASURE_KIND_LABELS: Record<ErasureKind, string> = {
  receipt_copy: "Stored receipt copy",
  client_contact_email: "Managed-client contact email",
};

export interface PrivacySettings {
  publishPublicReceipts: boolean;
  receiptRetentionDays: number | null;
  legalHold: boolean;
  version: number;
}

export interface PrivacyOverview {
  settings: PrivacySettings;
  publicReceiptFields: string[];
  audioHandling: string;
  erasureScopes: string[];
}

export interface PrivacyExportPage {
  schemaVersion: string;
  organizationId: string;
  resource: string;
  records: Record<string, unknown>[];
  nextCursor: string | null;
  exportedAt: string;
}

export interface ErasureRequest {
  id: string;
  kind: string;
  resourceId: string;
  status: string;
  requiredOrganizationIds: string[];
  approvedOrganizationIds: string[];
  createdAt: string;
  completedAt: string | null;
}

export interface ErasurePreview {
  request: ErasureRequest;
  willErase: string[];
  retained: string[];
  blockedBy: string[];
  canExecute: boolean;
  retainUntil: string | null;
  legalHold: boolean;
}

export interface ErasureExecution {
  request: ErasureRequest;
  erased: string[];
  retained: string[];
}

/** The last execution attempt for one request, kept on screen while the preview behind it refreshes. */
export type ExecutionOutcome =
  | { requestId: string; status: "erased"; erased: string[]; retained: string[] }
  | { requestId: string; status: "failed"; message: string };

export interface ReceiptDisclosure {
  /** A receipt issued before disclosure planning carries no public identifier. */
  publicReceiptId: string | null;
  publicUrl: string | null;
  published: boolean;
  withdrawn: boolean;
  privateCopyErased: boolean;
  retainUntil: string | null;
  commitmentOpening: { nonce: string; algorithm: string } | null;
}

export interface PrivacySettingsDraft {
  publishPublicReceipts: boolean;
  receiptRetentionDays: number | null;
  legalHold: boolean;
}

/** Privacy controls belong to the organization owner or administrator; a machine credential never reaches this panel. */
export function isPrivacyAdministrator(role: string): boolean {
  return role === "owner" || role === "admin";
}

export function privacyScopeKey(organizationId: string): string {
  return `organization-privacy:${organizationId}`;
}

/** A response belongs to the console only while it is the newest call for the organization still on screen. */
export function latestRequestAccepts(requestToken: number, latestRequestToken: number, requestScope: string, activeScope: string): boolean {
  return requestToken === latestRequestToken && requestScope === activeScope;
}

export function parseRetentionDays(raw: string): { ok: true; days: number | null } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (trimmed === "") return { ok: true, days: null };
  if (!/^\d+$/.test(trimmed)) return { ok: false, error: `Enter whole days from 1 to ${MAXIMUM_RETENTION_DAYS}, or leave the field empty for manual retention review.` };
  const days = Number(trimmed);
  if (days < 1 || days > MAXIMUM_RETENTION_DAYS) return { ok: false, error: `Enter whole days from 1 to ${MAXIMUM_RETENTION_DAYS}, or leave the field empty for manual retention review.` };
  return { ok: true, days };
}

export function retentionSummary(days: number | null): string {
  if (days === null) return "This organization reviews each erasure request by hand and records its own decision date.";
  return `This organization keeps a stored copy for at least ${days} day${days === 1 ? "" : "s"} after issue. When the other party selects a longer duration, that longer duration governs.`;
}

export function requiresPublicationConfirmation(savedPublishPublicReceipts: boolean, draftPublishPublicReceipts: boolean): boolean {
  return draftPublishPublicReceipts && !savedPublishPublicReceipts;
}

/** The confirmation gate runs on submit as well as on the button, because Enter in a text field submits the form. */
export function canSaveSettings(state: {
  hasSettings: boolean;
  retentionValid: boolean;
  saving: boolean;
  needsPublicationConfirmation: boolean;
  publicationConfirmed: boolean;
}): boolean {
  if (!state.hasSettings || !state.retentionValid || state.saving) return false;
  return !state.needsPublicationConfirmation || state.publicationConfirmed;
}

export function settingsPayload(draft: PrivacySettingsDraft, expectedVersion: number): Record<string, unknown> {
  return {
    publish_public_receipts: draft.publishPublicReceipts,
    receipt_retention_days: draft.receiptRetentionDays,
    legal_hold: draft.legalHold,
    expected_version: expectedVersion,
  };
}

export function approvalSummary(request: ErasureRequest): string {
  const required = new Set(request.requiredOrganizationIds);
  const approved = new Set(request.approvedOrganizationIds.filter((id) => required.has(id)));
  return `Approved by ${approved.size} of ${required.size} required organization${required.size === 1 ? "" : "s"}`;
}

export function organizationHasApproved(request: ErasureRequest, organizationId: string): boolean {
  return request.approvedOrganizationIds.includes(organizationId);
}

export function canExecuteErasure(preview: ErasurePreview | null, typedRequestId: string): boolean {
  if (!preview) return false;
  return preview.canExecute
    && !preview.legalHold
    && preview.blockedBy.length === 0
    && typedRequestId.trim() === preview.request.id;
}

/** A refresh of the preview leaves the last execution attempt, success or failure, on screen for the request it belongs to. */
export function executionOutcomeFor(outcome: ExecutionOutcome | null, requestId: string): ExecutionOutcome | null {
  return outcome && outcome.requestId === requestId ? outcome : null;
}

export function exportFileName(organizationId: string, resource: string, pageNumber: number): string {
  const safe = (value: string) => value.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase() || "export";
  return `clef-${safe(organizationId)}-${safe(resource)}-page-${pageNumber}.json`;
}

/**
 * The node returns the public summary as a path on the API origin. The console may be served from another origin,
 * so a path is resolved against the configured API base before it reaches an anchor.
 */
export function resolveApiUrl(apiBase: string, path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${apiBase.replace(/\/+$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}

export function publicSummaryLinks(apiBase: string, disclosure: ReceiptDisclosure): { summary: string; status: string } | null {
  if (!disclosure.publicUrl) return null;
  const summary = resolveApiUrl(apiBase, disclosure.publicUrl).replace(/\/+$/, "");
  return { summary, status: `${summary}/status` };
}

/** Withdrawal acts on the receipt the operator inspected, and only while this node still serves its public summary. */
export function canWithdrawPublicSummary(disclosure: ReceiptDisclosure | null, inspectedReceiptId: string, typedReceiptId: string): boolean {
  const typed = typedReceiptId.trim();
  if (!disclosure || typed === "" || inspectedReceiptId !== typed) return false;
  return disclosure.published && !disclosure.withdrawn;
}

export function disclosureSummary(disclosure: ReceiptDisclosure): string[] {
  const lines: string[] = [];
  if (disclosure.published && !disclosure.withdrawn) lines.push("This node serves a signed public summary for this receipt.");
  if (disclosure.withdrawn) lines.push("This node stopped serving the public summary. Copies already distributed stay with whoever holds them.");
  if (!disclosure.published && !disclosure.withdrawn) lines.push("This receipt lives in authenticated records. A public summary exists once both parties enable publication before issue.");
  if (disclosure.privateCopyErased) lines.push("The stored private copy is erased. Originals exported earlier still verify against this node's signature, and the historic payload hash stays in the audit chain.");
  if (disclosure.commitmentOpening) lines.push(`Authorized parties can verify the private commitment with the ${disclosure.commitmentOpening.algorithm} opening shown below. A holder of that opening can link this public summary to the private receipt, so it stays inside the parties entitled to the private record.`);
  lines.push("The public summary states the position at issue. Read the live status endpoint for the current permission state.");
  return lines;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString() : value;
}

function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

function sessionHeaders(sessionId: string): HeadersInit {
  return { "X-Session-Id": sessionId };
}

function jsonHeaders(sessionId: string): HeadersInit {
  return { "X-Session-Id": sessionId, "Content-Type": "application/json" };
}

function privacyPath(apiBase: string, organizationId: string): string {
  return `${apiBase}/v1/organizations/${encodeURIComponent(organizationId)}/privacy`;
}

/** The erasure endpoints answer a refusal with a structured detail object naming the remaining blockers. */
export function structuredFailureDetail(body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (!detail || typeof detail !== "object") return "";
  const message = typeof (detail as { message?: unknown }).message === "string" ? (detail as { message: string }).message : "";
  const blockedBy = (detail as { blockedBy?: unknown }).blockedBy;
  const blockers = Array.isArray(blockedBy) ? blockedBy.filter((item): item is string => typeof item === "string") : [];
  if (message && blockers.length > 0) return `${message}: ${blockers.map(humanize).join(", ")}`;
  return message || blockers.map(humanize).join(", ");
}

async function checkedPrivacyJson<T>(response: Response, operation: string): Promise<T> {
  if (!response.ok) {
    const detail = structuredFailureDetail(await response.clone().json().catch(() => null));
    if (detail) throw new Error(`${operation} failed (${response.status}): ${detail}`);
  }
  return checkedJson<T>(response, operation);
}

export async function getPrivacyOverview(apiBase: string, sessionId: string, organizationId: string): Promise<PrivacyOverview> {
  const response = await fetch(privacyPath(apiBase, organizationId), { headers: sessionHeaders(sessionId) });
  return checkedJson<PrivacyOverview>(response, "Load privacy settings");
}

export async function updatePrivacySettings(apiBase: string, sessionId: string, organizationId: string, draft: PrivacySettingsDraft, expectedVersion: number): Promise<PrivacyOverview> {
  const response = await fetch(privacyPath(apiBase, organizationId), {
    method: "PUT",
    headers: jsonHeaders(sessionId),
    body: JSON.stringify(settingsPayload(draft, expectedVersion)),
  });
  return checkedJson<PrivacyOverview>(response, "Save privacy settings");
}

export async function getPrivacyExportPage(apiBase: string, sessionId: string, organizationId: string, resource: PrivacyExportResource, cursor: string | null): Promise<PrivacyExportPage> {
  const query = new URLSearchParams({ resource, limit: "100" });
  if (cursor) query.set("cursor", cursor);
  const response = await fetch(`${privacyPath(apiBase, organizationId)}/export?${query.toString()}`, { headers: sessionHeaders(sessionId) });
  return checkedJson<PrivacyExportPage>(response, "Export organization data");
}

export async function listErasureRequests(apiBase: string, sessionId: string, organizationId: string): Promise<{ requests: ErasureRequest[] }> {
  const response = await fetch(`${privacyPath(apiBase, organizationId)}/requests`, { headers: sessionHeaders(sessionId) });
  return checkedJson<{ requests: ErasureRequest[] }>(response, "Load erasure requests");
}

export async function createErasureRequest(apiBase: string, sessionId: string, organizationId: string, kind: ErasureKind, resourceId: string): Promise<ErasureRequest> {
  const response = await fetch(`${privacyPath(apiBase, organizationId)}/requests`, {
    method: "POST",
    headers: jsonHeaders(sessionId),
    body: JSON.stringify({ kind, resource_id: resourceId }),
  });
  return checkedPrivacyJson<ErasureRequest>(response, "Open erasure request");
}

export async function getErasurePreview(apiBase: string, sessionId: string, organizationId: string, requestId: string): Promise<ErasurePreview> {
  const response = await fetch(`${privacyPath(apiBase, organizationId)}/requests/${encodeURIComponent(requestId)}/preview`, { headers: sessionHeaders(sessionId) });
  return checkedJson<ErasurePreview>(response, "Preview erasure request");
}

export async function approveErasureRequest(apiBase: string, sessionId: string, organizationId: string, requestId: string): Promise<ErasureRequest> {
  const response = await fetch(`${privacyPath(apiBase, organizationId)}/requests/${encodeURIComponent(requestId)}/approve`, {
    method: "POST",
    headers: jsonHeaders(sessionId),
    body: JSON.stringify({}),
  });
  return checkedPrivacyJson<ErasureRequest>(response, "Approve erasure request");
}

export async function executeErasureRequest(apiBase: string, sessionId: string, organizationId: string, requestId: string): Promise<ErasureExecution> {
  const response = await fetch(`${privacyPath(apiBase, organizationId)}/requests/${encodeURIComponent(requestId)}/execute`, {
    method: "POST",
    headers: jsonHeaders(sessionId),
    body: JSON.stringify({ confirm_request_id: requestId }),
  });
  return checkedPrivacyJson<ErasureExecution>(response, "Erase eligible stored copies");
}

export async function withdrawPublicReceipt(apiBase: string, sessionId: string, organizationId: string, receiptId: string): Promise<{ withdrawn: boolean }> {
  const response = await fetch(`${privacyPath(apiBase, organizationId)}/receipts/${encodeURIComponent(receiptId)}/withdraw-public`, {
    method: "POST",
    headers: jsonHeaders(sessionId),
    body: JSON.stringify({}),
  });
  return checkedJson<{ withdrawn: boolean }>(response, "Withdraw the public summary");
}

export async function getReceiptDisclosure(apiBase: string, sessionId: string, receiptId: string): Promise<ReceiptDisclosure> {
  const response = await fetch(`${apiBase}/v1/receipts/${encodeURIComponent(receiptId)}/disclosure`, { headers: sessionHeaders(sessionId) });
  return checkedJson<ReceiptDisclosure>(response, "Load receipt disclosure");
}

const CARD = "rounded-xl border border-slate-200 p-4";
const FIELD = "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
const PRIMARY_BUTTON = "rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40";
const SECONDARY_BUTTON = "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-40";
const DANGER_BUTTON = "rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40";

export function PrivacyPanel({
  apiBase,
  sessionId,
  organizationId,
}: {
  apiBase: string;
  sessionId: string;
  organizationId: string;
}) {
  const scope = privacyScopeKey(organizationId);
  const activeScopeRef = React.useRef(scope);
  const overviewTokenRef = React.useRef(0);
  const requestsTokenRef = React.useRef(0);
  const exportTokenRef = React.useRef(0);
  const previewTokenRef = React.useRef(0);
  const disclosureTokenRef = React.useRef(0);

  const [overview, setOverview] = React.useState<PrivacyOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = React.useState(true);
  const [overviewError, setOverviewError] = React.useState("");

  const [publishPublicReceipts, setPublishPublicReceipts] = React.useState(false);
  const [retentionInput, setRetentionInput] = React.useState("");
  const [legalHold, setLegalHold] = React.useState(false);
  const [publicationConfirmed, setPublicationConfirmed] = React.useState(false);
  const [settingsSaving, setSettingsSaving] = React.useState(false);
  const [settingsError, setSettingsError] = React.useState("");
  const [settingsMessage, setSettingsMessage] = React.useState("");

  const [exportResource, setExportResource] = React.useState<PrivacyExportResource>("receipts");
  const [exportPage, setExportPage] = React.useState<PrivacyExportPage | null>(null);
  const [exportPageNumber, setExportPageNumber] = React.useState(0);
  const [exportLoading, setExportLoading] = React.useState(false);
  const [exportError, setExportError] = React.useState("");

  const [requests, setRequests] = React.useState<ErasureRequest[]>([]);
  const [requestsLoading, setRequestsLoading] = React.useState(true);
  const [requestsError, setRequestsError] = React.useState("");
  const [newRequestKind, setNewRequestKind] = React.useState<ErasureKind>("receipt_copy");
  const [newResourceId, setNewResourceId] = React.useState("");
  const [requestBusy, setRequestBusy] = React.useState(false);
  const [requestMessage, setRequestMessage] = React.useState("");

  const [selectedRequestId, setSelectedRequestId] = React.useState("");
  const [preview, setPreview] = React.useState<ErasurePreview | null>(null);
  const [previewLoading, setPreviewLoading] = React.useState(false);
  const [previewError, setPreviewError] = React.useState("");
  const [confirmationInput, setConfirmationInput] = React.useState("");
  const [executionOutcome, setExecutionOutcome] = React.useState<ExecutionOutcome | null>(null);

  const [receiptIdInput, setReceiptIdInput] = React.useState("");
  const [disclosure, setDisclosure] = React.useState<ReceiptDisclosure | null>(null);
  const [inspectedReceiptId, setInspectedReceiptId] = React.useState("");
  const [disclosureLoading, setDisclosureLoading] = React.useState(false);
  const [disclosureError, setDisclosureError] = React.useState("");
  const [disclosureMessage, setDisclosureMessage] = React.useState("");

  const applySettings = React.useCallback((settings: PrivacySettings) => {
    setPublishPublicReceipts(settings.publishPublicReceipts);
    setRetentionInput(settings.receiptRetentionDays === null ? "" : String(settings.receiptRetentionDays));
    setLegalHold(settings.legalHold);
    setPublicationConfirmed(false);
  }, []);

  const loadOverview = React.useCallback(async (requestScope: string) => {
    overviewTokenRef.current += 1;
    const token = overviewTokenRef.current;
    setOverviewLoading(true);
    try {
      const loaded = await getPrivacyOverview(apiBase, sessionId, organizationId);
      if (!latestRequestAccepts(token, overviewTokenRef.current, requestScope, activeScopeRef.current)) return;
      setOverview(loaded);
      applySettings(loaded.settings);
      setOverviewError("");
    } catch (caught) {
      if (!latestRequestAccepts(token, overviewTokenRef.current, requestScope, activeScopeRef.current)) return;
      setOverviewError(caught instanceof Error ? caught.message : "Could not load privacy settings.");
    } finally {
      if (latestRequestAccepts(token, overviewTokenRef.current, requestScope, activeScopeRef.current)) setOverviewLoading(false);
    }
  }, [apiBase, applySettings, organizationId, sessionId]);

  const loadRequests = React.useCallback(async (requestScope: string) => {
    requestsTokenRef.current += 1;
    const token = requestsTokenRef.current;
    setRequestsLoading(true);
    try {
      const loaded = await listErasureRequests(apiBase, sessionId, organizationId);
      if (!latestRequestAccepts(token, requestsTokenRef.current, requestScope, activeScopeRef.current)) return;
      setRequests(loaded.requests);
      setRequestsError("");
    } catch (caught) {
      if (!latestRequestAccepts(token, requestsTokenRef.current, requestScope, activeScopeRef.current)) return;
      setRequestsError(caught instanceof Error ? caught.message : "Could not load erasure requests.");
    } finally {
      if (latestRequestAccepts(token, requestsTokenRef.current, requestScope, activeScopeRef.current)) setRequestsLoading(false);
    }
  }, [apiBase, organizationId, sessionId]);

  React.useEffect(() => {
    activeScopeRef.current = scope;
    setOverview(null);
    setOverviewError("");
    setSettingsError("");
    setSettingsMessage("");
    setExportPage(null);
    setExportPageNumber(0);
    setExportError("");
    setRequests([]);
    setRequestsError("");
    setRequestMessage("");
    setSelectedRequestId("");
    setPreview(null);
    setPreviewError("");
    setConfirmationInput("");
    setExecutionOutcome(null);
    setReceiptIdInput("");
    setDisclosure(null);
    setInspectedReceiptId("");
    setDisclosureError("");
    setDisclosureMessage("");
    void loadOverview(scope);
    void loadRequests(scope);
    // The console mounts this panel under key={privacyScopeKey(organizationId)}, so switching organizations
    // discards this instance. Clearing the active scope makes every in-flight response fail its own guard,
    // which also covers a caller that renders the panel without that key.
    return () => { activeScopeRef.current = ""; };
  }, [loadOverview, loadRequests, scope]);

  const retention = parseRetentionDays(retentionInput);
  const needsPublicationConfirmation = requiresPublicationConfirmation(Boolean(overview?.settings.publishPublicReceipts), publishPublicReceipts);
  const canWithdraw = canWithdrawPublicSummary(disclosure, inspectedReceiptId, receiptIdInput);
  const links = disclosure ? publicSummaryLinks(apiBase, disclosure) : null;
  const canSave = canSaveSettings({
    hasSettings: Boolean(overview),
    retentionValid: retention.ok,
    saving: settingsSaving,
    needsPublicationConfirmation,
    publicationConfirmed,
  });

  async function saveSettings(event: React.FormEvent) {
    event.preventDefault();
    if (!overview || !retention.ok || !canSave) {
      setSettingsMessage("");
      if (needsPublicationConfirmation && !publicationConfirmed) setSettingsError("Confirm the publication change with the checkbox above before saving.");
      return;
    }
    setSettingsSaving(true);
    setSettingsMessage("");
    try {
      const saved = await updatePrivacySettings(apiBase, sessionId, organizationId, {
        publishPublicReceipts,
        receiptRetentionDays: retention.days,
        legalHold,
      }, overview.settings.version);
      setOverview(saved);
      applySettings(saved.settings);
      setSettingsError("");
      setSettingsMessage(`Saved as version ${saved.settings.version}. Publication applies to receipts issued from now on; the hold and the retention minimum are read again the next time an erasure runs.`);
    } catch (caught) {
      setSettingsError(caught instanceof Error ? caught.message : "Could not save privacy settings.");
    } finally {
      setSettingsSaving(false);
    }
  }

  async function loadExportPage(cursor: string | null, pageNumber: number) {
    const requestScope = activeScopeRef.current;
    exportTokenRef.current += 1;
    const token = exportTokenRef.current;
    setExportLoading(true);
    try {
      const page = await getPrivacyExportPage(apiBase, sessionId, organizationId, exportResource, cursor);
      if (!latestRequestAccepts(token, exportTokenRef.current, requestScope, activeScopeRef.current)) return;
      setExportPage(page);
      setExportPageNumber(pageNumber);
      setExportError("");
    } catch (caught) {
      if (!latestRequestAccepts(token, exportTokenRef.current, requestScope, activeScopeRef.current)) return;
      setExportError(caught instanceof Error ? caught.message : "Could not export this resource.");
    } finally {
      if (latestRequestAccepts(token, exportTokenRef.current, requestScope, activeScopeRef.current)) setExportLoading(false);
    }
  }

  function downloadExportPage() {
    if (!exportPage) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(exportPage, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = exportFileName(organizationId, exportPage.resource, exportPageNumber);
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function openRequest(event: React.FormEvent) {
    event.preventDefault();
    setRequestBusy(true);
    setRequestMessage("");
    try {
      const created = await createErasureRequest(apiBase, sessionId, organizationId, newRequestKind, newResourceId.trim());
      setNewResourceId("");
      setRequestsError("");
      setRequestMessage(`Opened request ${created.id}. ${approvalSummary(created)}.`);
      await loadRequests(activeScopeRef.current);
      await showPreview(created.id);
    } catch (caught) {
      setRequestsError(caught instanceof Error ? caught.message : "Could not open the erasure request.");
    } finally {
      setRequestBusy(false);
    }
  }

  /** keepOutcome refreshes the preview behind an execution attempt without erasing the result or the error it produced. */
  async function showPreview(requestId: string, options: { keepOutcome?: boolean } = {}) {
    const requestScope = activeScopeRef.current;
    previewTokenRef.current += 1;
    const token = previewTokenRef.current;
    const accepts = () => latestRequestAccepts(token, previewTokenRef.current, requestScope, activeScopeRef.current);
    setSelectedRequestId(requestId);
    setPreview(null);
    setPreviewError("");
    if (!options.keepOutcome) {
      setConfirmationInput("");
      // A fresh look at this request drops its own last attempt; an outcome on another request stays where it is.
      setExecutionOutcome((current) => (current && current.requestId === requestId ? null : current));
    }
    setPreviewLoading(true);
    try {
      const loaded = await getErasurePreview(apiBase, sessionId, organizationId, requestId);
      if (!accepts()) return;
      setPreview(loaded);
    } catch (caught) {
      if (!accepts()) return;
      setPreviewError(caught instanceof Error ? caught.message : "Could not load the erasure preview.");
    } finally {
      if (accepts()) setPreviewLoading(false);
    }
  }

  async function approveRequest(requestId: string) {
    setRequestBusy(true);
    setRequestMessage("");
    try {
      const approved = await approveErasureRequest(apiBase, sessionId, organizationId, requestId);
      setRequestsError("");
      setRequestMessage(`Recorded this organization's approval. ${approvalSummary(approved)}.`);
      await loadRequests(activeScopeRef.current);
      if (selectedRequestId === requestId) await showPreview(requestId);
    } catch (caught) {
      setRequestsError(caught instanceof Error ? caught.message : "Could not record the approval.");
    } finally {
      setRequestBusy(false);
    }
  }

  async function executeRequest(requestId: string) {
    setRequestBusy(true);
    setRequestMessage("");
    try {
      const result = await executeErasureRequest(apiBase, sessionId, organizationId, requestId);
      setExecutionOutcome({ requestId, status: "erased", erased: result.erased, retained: result.retained });
      setConfirmationInput("");
      setRequestsError("");
      setRequestMessage(`Erased ${result.erased.length} stored item${result.erased.length === 1 ? "" : "s"} for request ${requestId}.`);
    } catch (caught) {
      setExecutionOutcome({ requestId, status: "failed", message: caught instanceof Error ? caught.message : "Could not erase the stored copies." });
    } finally {
      await loadRequests(activeScopeRef.current);
      await showPreview(requestId, { keepOutcome: true });
      setRequestBusy(false);
    }
  }

  /** Every lookup carries a token so a slow answer for an earlier receipt ID never lands under a later one. */
  function beginDisclosureRequest() {
    const requestScope = activeScopeRef.current;
    disclosureTokenRef.current += 1;
    const token = disclosureTokenRef.current;
    return () => latestRequestAccepts(token, disclosureTokenRef.current, requestScope, activeScopeRef.current);
  }

  function clearDisclosure() {
    disclosureTokenRef.current += 1;
    setDisclosure(null);
    setInspectedReceiptId("");
    setDisclosureError("");
    setDisclosureMessage("");
    setDisclosureLoading(false);
  }

  async function checkDisclosure() {
    const receiptId = receiptIdInput.trim();
    if (!receiptId) return;
    const accepts = beginDisclosureRequest();
    setDisclosure(null);
    setInspectedReceiptId("");
    setDisclosureLoading(true);
    setDisclosureMessage("");
    try {
      const loaded = await getReceiptDisclosure(apiBase, sessionId, receiptId);
      if (!accepts()) return;
      setDisclosure(loaded);
      setInspectedReceiptId(receiptId);
      setDisclosureError("");
    } catch (caught) {
      if (!accepts()) return;
      setDisclosureError(caught instanceof Error ? caught.message : "Could not load the receipt disclosure.");
    } finally {
      if (accepts()) setDisclosureLoading(false);
    }
  }

  async function withdrawSummary() {
    const receiptId = receiptIdInput.trim();
    if (!canWithdraw) return;
    const accepts = beginDisclosureRequest();
    setDisclosureLoading(true);
    setDisclosureMessage("");
    try {
      await withdrawPublicReceipt(apiBase, sessionId, organizationId, receiptId);
      if (!accepts()) return;
      setDisclosureError("");
      setDisclosureMessage("This node stopped serving the public summary. Copies already distributed stay with whoever holds them.");
    } catch (caught) {
      if (accepts()) {
        setDisclosure(null);
        setInspectedReceiptId("");
        setDisclosureError(caught instanceof Error ? caught.message : "Could not withdraw the public summary.");
        setDisclosureLoading(false);
      }
      return;
    }
    try {
      const loaded = await getReceiptDisclosure(apiBase, sessionId, receiptId);
      if (!accepts()) return;
      setDisclosure(loaded);
      setInspectedReceiptId(receiptId);
    } catch (caught) {
      if (!accepts()) return;
      setDisclosure(null);
      setInspectedReceiptId("");
      setDisclosureError(`The withdrawal was recorded. Reading the current disclosure failed: ${caught instanceof Error ? caught.message : "unknown error"}`);
    } finally {
      if (accepts()) setDisclosureLoading(false);
    }
  }

  return (
    <section className="space-y-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="organization-privacy-title">
      <div>
        <h2 id="organization-privacy-title" className="text-lg font-semibold text-slate-950">Data privacy</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Owners and administrators set what this node publishes, how long it keeps stored copies, export this organization&rsquo;s records, and erase the stored copies listed in an approved request.
          Audio stays in the operator&rsquo;s existing delivery infrastructure; this node records scope and commitments.
        </p>
        <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-800">Operator follow-up outside this node</summary>
          <p className="mt-2 text-sm text-slate-600">An erasure here covers the stored copies this API owns. These locations keep their own copies until the operator acts on each one:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
            {OPERATOR_FOLLOWUP.map((item) => <li key={item}>{item}</li>)}
          </ul>
          <p className="mt-2 text-sm text-slate-600">
            The full procedure ships with this node at <code className="rounded bg-white px-1 py-0.5 font-mono text-xs text-slate-800">docs/DATA_PRIVACY.md</code> in the repository this deployment was built from.
          </p>
        </details>
      </div>

      {overviewLoading && !overview && <p className="text-sm text-slate-500">Loading privacy settings&hellip;</p>}
      {overviewError && (
        <div role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">
          {overviewError} <button type="button" onClick={() => void loadOverview(activeScopeRef.current)} className="font-medium underline">Try again</button>
        </div>
      )}

      {overview && (
        <form onSubmit={saveSettings} className={CARD} aria-busy={settingsSaving}>
          <h3 className="text-sm font-semibold text-slate-900">Publication and retention</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
            <li>Publication governs receipts issued after you save. Records already signed keep the disclosure that applied at issue.</li>
            <li>A legal hold blocks these receipt-copy and contact-email erasures from the moment you save it. Apply matching holds to other storage through your operator procedure.</li>
            <li>Retention is read again at deletion time, so a longer minimum saved today postpones a pending erasure.</li>
            <li>Shortening the retention minimum leaves the duration fixed at issue in force. The longest applicable duration governs.</li>
          </ul>

          <label className="mt-4 flex items-start gap-3 text-sm text-slate-700">
            <input type="checkbox" className="mt-1" checked={publishPublicReceipts} onChange={(event) => { setPublishPublicReceipts(event.target.checked); setPublicationConfirmed(false); }} />
            <span>
              <strong className="font-medium text-slate-900">Publish a minimal public summary for new receipts</strong>
              <span className="mt-1 block text-slate-600">Both parties enable this before issue for a public summary to exist. The published fields are fixed at issue: {overview.publicReceiptFields.join(", ")}.</span>
            </span>
          </label>

          {needsPublicationConfirmation && (
            <label className="mt-3 flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              <input type="checkbox" className="mt-1" checked={publicationConfirmed} onChange={(event) => setPublicationConfirmed(event.target.checked)} />
              <span>I confirm this organization publishes those fields for receipts issued from now on, and I understand the node keeps existing records in authenticated storage.</span>
            </label>
          )}

          <label className="mt-4 block text-sm font-medium text-slate-800" htmlFor="privacy-retention-days">
            Minimum retention for stored receipt copies (days)
            <input
              id="privacy-retention-days"
              type="text"
              inputMode="numeric"
              value={retentionInput}
              onChange={(event) => setRetentionInput(event.target.value)}
              placeholder="Leave empty for manual retention review"
              aria-describedby="privacy-retention-help"
              aria-invalid={!retention.ok}
              className={FIELD}
            />
          </label>
          <p id="privacy-retention-help" className="mt-1 text-xs text-slate-600">{retention.ok ? retentionSummary(retention.days) : retention.error}</p>

          <label className="mt-4 flex items-start gap-3 text-sm text-slate-700">
            <input type="checkbox" className="mt-1" checked={legalHold} onChange={(event) => setLegalHold(event.target.checked)} />
            <span>
              <strong className="font-medium text-slate-900">Legal hold</strong>
              <span className="mt-1 block text-slate-600">A hold blocks the erasures managed here. The node checks both parties’ holds again when an erasure runs.</span>
            </span>
          </label>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button type="submit" disabled={!canSave} className={PRIMARY_BUTTON}>Save privacy settings</button>
            <button type="button" onClick={() => void loadOverview(activeScopeRef.current)} className={SECONDARY_BUTTON}>Reload current settings</button>
            <span className="text-xs text-slate-500">Saved version {overview.settings.version}</span>
          </div>
          {settingsError && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{settingsError} Reload the current settings to see the version another administrator saved, then apply your change again.</div>}
          {settingsMessage && <p role="status" className="mt-3 text-sm text-emerald-800">{settingsMessage}</p>}
          <p className="mt-3 text-xs text-slate-500">Audio handling on this node: {overview.audioHandling}</p>
        </form>
      )}

      <div className={CARD} aria-busy={exportLoading}>
        <h3 className="text-sm font-semibold text-slate-900">Export this organization&rsquo;s records</h3>
        <p className="mt-1 text-sm text-slate-600">
          Each page returns up to 100 records for the selected resource, scoped to {organizationId}. The file carries private records; hold it under this organization&rsquo;s retention procedure. Signing keys, credential secrets, and webhook secrets stay in the operator&rsquo;s secret manager.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="block text-sm font-medium text-slate-800" htmlFor="privacy-export-resource">
            Resource
            <select
              id="privacy-export-resource"
              value={exportResource}
              onChange={(event) => { exportTokenRef.current += 1; setExportLoading(false); setExportResource(event.target.value as PrivacyExportResource); setExportPage(null); setExportPageNumber(0); setExportError(""); }}
              className={FIELD}
            >
              {PRIVACY_EXPORT_RESOURCES.map((resource) => <option key={resource} value={resource}>{RESOURCE_LABELS[resource]}</option>)}
            </select>
          </label>
          <button type="button" disabled={exportLoading} onClick={() => void loadExportPage(null, 1)} className={PRIMARY_BUTTON}>Load first page</button>
          {exportPage?.nextCursor && <button type="button" disabled={exportLoading} onClick={() => void loadExportPage(exportPage.nextCursor, exportPageNumber + 1)} className={SECONDARY_BUTTON}>Load next page</button>}
          {exportPage && <button type="button" onClick={downloadExportPage} className={SECONDARY_BUTTON}>Download this page as JSON</button>}
        </div>
        {exportLoading && <p className="mt-3 text-sm text-slate-500">Reading page {exportPageNumber + 1}&hellip;</p>}
        {exportError && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{exportError}</div>}
        {exportPage && (
          <div className="mt-3 space-y-2">
            <p role="status" className="text-sm text-slate-700">
              Page {exportPageNumber} of {RESOURCE_LABELS[exportResource]}: {exportPage.records.length} record{exportPage.records.length === 1 ? "" : "s"} · schema {exportPage.schemaVersion} · exported {formatTimestamp(exportPage.exportedAt)}
              {exportPage.nextCursor ? " · more pages remain" : " · this is the final page"}
            </p>
            <details>
              <summary className="cursor-pointer text-xs font-medium text-slate-700">Inspect this page</summary>
              <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">{JSON.stringify(exportPage.records, null, 2)}</pre>
            </details>
          </div>
        )}
      </div>

      <div className={CARD} aria-busy={requestBusy || requestsLoading}>
        <h3 className="text-sm font-semibold text-slate-900">Erasure requests</h3>
        <p className="mt-1 text-sm text-slate-600">
          A request covers one stored receipt copy with its private commitment opening, or one managed-client contact email. The preview lists the records this node keeps. Contracts, imports, delivered webhooks, downloaded exports, database residue, and backups follow the operator checklist at the top of this panel.
        </p>
        {overview && overview.erasureScopes.length > 0 && <p className="mt-2 text-xs text-slate-500">Scopes this node erases: {overview.erasureScopes.map(humanize).join(", ")}</p>}

        <form onSubmit={openRequest} className="mt-4 flex flex-wrap items-end gap-3">
          <label className="block text-sm font-medium text-slate-800" htmlFor="privacy-request-kind">
            Request kind
            <select id="privacy-request-kind" value={newRequestKind} onChange={(event) => setNewRequestKind(event.target.value as ErasureKind)} className={FIELD}>
              {ERASURE_KINDS.map((kind) => <option key={kind} value={kind}>{ERASURE_KIND_LABELS[kind]}</option>)}
            </select>
          </label>
          <label className="block text-sm font-medium text-slate-800" htmlFor="privacy-request-resource">
            {newRequestKind === "receipt_copy" ? "Receipt ID" : "Managed client ID"}
            <input id="privacy-request-resource" required value={newResourceId} onChange={(event) => setNewResourceId(event.target.value)} className={FIELD} />
          </label>
          <button type="submit" disabled={requestBusy || !newResourceId.trim()} className={PRIMARY_BUTTON}>Open erasure request</button>
        </form>
        {requestsError && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{requestsError}</div>}
        {requestMessage && <p role="status" className="mt-3 text-sm text-emerald-800">{requestMessage}</p>}

        {requestsLoading && requests.length === 0 && <p className="mt-3 text-sm text-slate-500">Loading erasure requests&hellip;</p>}
        {!requestsLoading && requests.length === 0 && <p className="mt-3 text-sm text-slate-500">This organization has no open erasure request.</p>}

        <ul className="mt-4 space-y-3">
          {requests.map((request) => {
            const outcome = executionOutcomeFor(executionOutcome, request.id);
            return (
              <li key={request.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <strong className="text-sm text-slate-900">{ERASURE_KIND_LABELS[request.kind as ErasureKind] || humanize(request.kind)}</strong>
                    <p className="mt-1 font-mono text-xs text-slate-500">{request.id}</p>
                    <p className="mt-1 text-xs text-slate-600">Target {request.resourceId} · opened {formatTimestamp(request.createdAt)}{request.completedAt ? ` · completed ${formatTimestamp(request.completedAt)}` : ""}</p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{humanize(request.status)}</span>
                </div>
                <p className="mt-2 text-xs text-slate-600">{approvalSummary(request)}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" onClick={() => void showPreview(request.id)} className={SECONDARY_BUTTON}>Show what this erases</button>
                  <button type="button" disabled={requestBusy || organizationHasApproved(request, organizationId)} onClick={() => void approveRequest(request.id)} className={SECONDARY_BUTTON}>
                    {organizationHasApproved(request, organizationId) ? "This organization approved" : "Record this organization's approval"}
                  </button>
                </div>

                {outcome?.status === "erased" && (
                  <div role="status" className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
                    <p>Erased: {outcome.erased.length > 0 ? outcome.erased.map(humanize).join(", ") : "nothing"}</p>
                    <p className="mt-1">Retained: {outcome.retained.length > 0 ? outcome.retained.map(humanize).join(", ") : "no linked records"}</p>
                    <p className="mt-1">Signatures on originals exported earlier keep verifying, and the historic payload hash stays in the audit chain.</p>
                  </div>
                )}
                {outcome?.status === "failed" && (
                  <div role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                    <p>This node erased nothing for this request: {outcome.message}</p>
                    <p className="mt-1">The refreshed preview below shows the state the node reports now.</p>
                  </div>
                )}

                {selectedRequestId === request.id && (
                  <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                    {previewLoading && <p className="text-sm text-slate-500">Loading the preview&hellip;</p>}
                    {previewError && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{previewError}</div>}
                    {preview && preview.request.id === request.id && (
                      <div className="space-y-2 text-sm text-slate-700">
                        <p><strong className="font-medium text-slate-900">This node erases:</strong> {preview.willErase.length > 0 ? preview.willErase.map(humanize).join(", ") : "nothing yet"}</p>
                        <p><strong className="font-medium text-slate-900">This node keeps:</strong> {preview.retained.length > 0 ? preview.retained.map(humanize).join(", ") : "no linked records"}</p>
                        {preview.blockedBy.length > 0 && <p className="text-amber-900"><strong className="font-medium">Waiting on:</strong> {preview.blockedBy.map(humanize).join(", ")}</p>}
                        {preview.legalHold && <p className="text-amber-900">A party organization has an active legal hold. Its administrator must resolve the retaining obligation before clearing it.</p>}
                        {preview.retainUntil && <p>Minimum retention runs until {formatTimestamp(preview.retainUntil)}.</p>}

                        <label className="block text-sm font-medium text-slate-800" htmlFor={`privacy-confirm-${request.id}`}>
                          Type or paste the request ID to confirm
                          <input
                            id={`privacy-confirm-${request.id}`}
                            value={confirmationInput}
                            onChange={(event) => setConfirmationInput(event.target.value)}
                            placeholder={request.id}
                            autoComplete="off"
                            className={FIELD}
                          />
                        </label>
                        <button type="button" disabled={requestBusy || !canExecuteErasure(preview, confirmationInput)} onClick={() => void executeRequest(request.id)} className={DANGER_BUTTON}>Erase the listed stored copies</button>
                      </div>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      <div className={CARD} aria-busy={disclosureLoading}>
        <h3 className="text-sm font-semibold text-slate-900">Public summary for one receipt</h3>
        <p className="mt-1 text-sm text-slate-600">Look up the public state of a receipt this organization is party to, share its public link, or stop this node from serving its public summary. Either party can withdraw.</p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="block text-sm font-medium text-slate-800" htmlFor="privacy-receipt-id">
            Receipt ID
            <input id="privacy-receipt-id" value={receiptIdInput} onChange={(event) => { setReceiptIdInput(event.target.value); clearDisclosure(); }} className={FIELD} />
          </label>
          <button type="button" disabled={disclosureLoading || !receiptIdInput.trim()} onClick={() => void checkDisclosure()} className={PRIMARY_BUTTON}>Check disclosure status</button>
          <button type="button" disabled={disclosureLoading || !canWithdraw} onClick={() => void withdrawSummary()} className={SECONDARY_BUTTON}>Stop serving the public summary</button>
        </div>
        {!canWithdraw && <p className="mt-2 text-xs text-slate-500">Withdrawal opens after a disclosure check reports that this node currently serves a public summary for the receipt ID in the field.</p>}
        {disclosureError && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{disclosureError}</div>}
        {disclosureMessage && <p role="status" className="mt-3 text-sm text-emerald-800">{disclosureMessage}</p>}
        {disclosure && (
          <div className="mt-3 space-y-2 text-sm text-slate-700">
            <p className="text-xs text-slate-500">Receipt <span className="font-mono">{inspectedReceiptId}</span>{disclosure.publicReceiptId ? <> · public ID <span className="font-mono">{disclosure.publicReceiptId}</span></> : " · this receipt carries no public identifier"}</p>
            {links && (
              <p className="flex flex-wrap gap-4">
                <a className="font-medium text-blue-700 underline" href={links.summary} target="_blank" rel="noreferrer">Open the public summary at issue</a>
                <a className="font-medium text-blue-700 underline" href={links.status} target="_blank" rel="noreferrer">Open the current status endpoint</a>
              </p>
            )}
            {disclosure.retainUntil && <p>Minimum retention runs until {formatTimestamp(disclosure.retainUntil)}.</p>}
            <ul className="list-disc space-y-1 pl-5">
              {disclosureSummary(disclosure).map((line) => <li key={line}>{line}</li>)}
            </ul>
            {disclosure.commitmentOpening && (
              <details className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-900">
                <summary className="cursor-pointer text-sm font-medium">Private commitment opening &middot; keep inside the parties to this receipt</summary>
                <p className="mt-2 text-xs">Algorithm {disclosure.commitmentOpening.algorithm}. Anyone holding this nonce can prove which private receipt produced the public summary, so treat it as private evidence and pass it only to a party already entitled to the private record.</p>
                <p className="mt-2 break-all font-mono text-xs">{disclosure.commitmentOpening.nonce}</p>
              </details>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
