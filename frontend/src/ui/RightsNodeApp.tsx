import React from "react";
import { safeStorageGet, safeStorageRemove, safeStorageSet } from "../utils/storage";
import { DeploymentReadinessPanel } from "./DeploymentReadinessPanel";
import { OnboardingChecklist } from "./OnboardingChecklist";
import { isPrivacyAdministrator, PrivacyPanel, privacyScopeKey } from "./PrivacyPanel";
import { SandboxTour } from "./SandboxTour";
import { ConnectedCatalogs } from "./ConnectedCatalogs";
import { AuthorityWithdrawal } from "./AuthorityWithdrawal";
import { AI_INPUT_KEYS, AI_MODEL_SCOPE_KEYS, AI_SAFEGUARD_KEYS, AI_USAGE_KEYS, ALL_AI_USAGE_KEYS, LEGACY_AI_USAGE_KEYS, RESTRICTION_KEYS, RequestScopeFields, initialRequestScope, isAiUsageKey, requestScopeComplete, requestScopeContext } from "./RequestScope";

export { isAiUsageKey };

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const SESSION_KEY = "clef.rights.session";
const ORG_KEY = "clef.rights.organization";

export function policyEditorScopeKey(organizationId: string): string {
  return `policy-editor:${organizationId}`;
}

export function organizationConsoleScopeKey(organizationId: string): string {
  return `organization-console:${organizationId}`;
}

const STANDARD_USAGE_KEYS = [
  "ads_brand",
  "ads_political",
  "ads_psa",
  "film_tv",
  "streaming_visual",
  "video_game",
  "podcast_audio",
  "ugc_creator",
  "live_performance",
  "background_music",
  "corporate_internal",
  "educational",
  "personal_noncommercial",
  "derivative_remix",
] as const;

const USAGE_KEYS = [...STANDARD_USAGE_KEYS, ...ALL_AI_USAGE_KEYS] as const;

const AI_LIMIT_KEYS = ["maxSourceDurationSeconds", "maxOutputDurationSeconds", "maxLyricCharacters", "sourceRetentionDays", "embeddingRetentionDays"] as const;
const RIGHT_TYPES = ["composition", "master", "lyrics", "performance", "voice", "likeness"] as const;
const DEFAULT_CONTROLLED_RIGHTS_BY_ORGANIZATION_TYPE: Record<string, readonly string[]> = {
  rights_holder: ["composition"],
  artist: ["composition", "master", "lyrics", "performance", "voice", "likeness"],
  label: ["master"],
  publisher: ["composition", "lyrics"],
  administrator: ["composition", "master"],
  pro: ["composition", "performance"],
  cmo: ["composition", "performance"],
  collective: ["composition", "performance"],
  requester: [],
};

export function defaultControlledRightsForOrganizationType(organizationType: string): string[] {
  return [...(DEFAULT_CONTROLLED_RIGHTS_BY_ORGANIZATION_TYPE[organizationType] || DEFAULT_CONTROLLED_RIGHTS_BY_ORGANIZATION_TYPE.rights_holder)];
}
const API_CREDENTIAL_SCOPES = [
  "directory:read",
  "registry:read",
  "rights:read",
  "permissions:read",
  "permissions:request",
  "permissions:decide",
  "permissions:assign",
  "permissions:lifecycle",
  "compliance:report",
  "compliance:review",
  "settlements:read",
  "settlements:write",
  "settlements:reconcile",
  "catalog:read",
  "catalog:write",
  "ddex:read",
  "ddex:write",
  "webhooks:read",
  "webhooks:write",
  "audit:read",
] as const;
const ORG_DECISION_ROLES = new Set(["owner", "admin", "rights_manager"]);

const LABELS: Record<string, string> = {
  ai_training_recursive: "Legacy recursive AI training",
  ai_model_training: "Foundation-model training",
  ai_model_fine_tuning: "Fine-tuning or model adaptation",
  ai_grounded_generation: "Licensed grounding for generation",
  ai_embedding_creation: "Embedding creation",
  ai_embedding_retrieval: "Embedding storage and retrieval",
  ai_source_separation: "Source separation or stem extraction",
  ai_music_transformation: "AI remix or music transformation",
  ai_lyric_analysis: "Lyric analysis",
  ai_lyric_generation: "Lyric generation or adaptation",
  ai_synthetic_voice: "Synthetic voice generation",
  full_mix: "Full mix",
  stems: "Supplied stems",
  isolated_vocals: "Isolated vocals",
  lyrics: "Lyrics",
  composition_data: "Composition, MIDI, or score data",
  reference_embeddings: "Existing reference embeddings",
  private_single_tenant: "Private, single-tenant model",
  shared_commercial_model: "Shared commercial model",
  public_or_open_weights: "Public or open-weight model",
  maxSourceDurationSeconds: "Maximum source duration (seconds)",
  maxOutputDurationSeconds: "Maximum generated output (seconds)",
  maxLyricCharacters: "Maximum lyric input (characters)",
  sourceRetentionDays: "Source retention (days)",
  embeddingRetentionDays: "Embedding retention (days)",
  provenanceReceipt: "Signed provenance receipt",
  outputWatermark: "Machine-readable output watermark",
  attribution: "Artist and rightsholder attribution",
  similarityReview: "Output similarity review",
  deletionAttestation: "Source and embedding deletion attestation",
};

type SessionCredential = { id: string; email: string; expires_at: string };
type NodeInfo = {
  federationEnabled?: boolean;
  deploymentMode: string;
  sandboxGuestAccess: boolean;
  webhookDeliveryEnabled: boolean;
  softwareLicense: string;
  sourceCodeUrl: string | null;
  sourceCodeRevision: string;
};

export function isPublicSandbox(nodeInfo: Pick<NodeInfo, "deploymentMode"> | null): boolean {
  return nodeInfo?.deploymentMode === "public_sandbox";
}
type AiPolicy = {
  schemaVersion: string;
  inputs: Record<string, string>;
  modelScopes: Record<string, string>;
  limits: Record<string, number | null>;
  safeguards: Record<string, boolean>;
};
type OrganizationProfile = {
  organizationType: string;
  defaultTerritory: string;
  controlledRightTypes: string[];
  aiPolicyPreset: string;
  policyDefaults: { matrix: { usage: Record<string, string>; restrictions: Record<string, string> }; aiPolicy: AiPolicy };
};
type Organization = { id: string; slug: string; name: string; role: string; profile?: OrganizationProfile };
type SessionContext = {
  user: { id: string; email: string; displayName?: string; nodeRole: string };
  organizations: Organization[];
};

export function requiresOrganizationSetup(context: SessionContext): boolean {
  const syntheticGuest = context.user.email.toLowerCase().endsWith("@sandbox.invalid");
  return context.organizations.length === 0 && (context.user.nodeRole !== "admin" || syntheticGuest);
}

export function canOrganizationManageRights(organization: Organization): boolean {
  return organization.profile?.organizationType !== "requester";
}
type Policy = {
  id: string;
  workKey: string;
  artistName: string;
  version: number;
  contract: any;
  matrix: { usage: Record<string, string>; restrictions: Record<string, string> };
  updatedAt: string;
};
type Claim = {
  id: string;
  rightsContractId: string;
  workKey: string;
  rightType: string;
  territory: string;
  status: string;
  evidence: Record<string, unknown>;
};
type DirectoryClaim = {
  id: string;
  organization: { id: string; name: string };
  workKey: string;
  workTitle?: string;
  artistName: string;
  rightType: string;
  territory: string;
  verificationStatus: string;
  matrix: { usage: Record<string, string>; restrictions: Record<string, string> };
  aiPolicy: AiPolicy;
};
type LicenseObligations = {
  schemaVersion: string;
  attribution: {
    required: boolean;
    creditText?: string;
    backlinkRequired: boolean;
    backlinkUrl?: string;
    placements: string[];
    metadataFields: Record<string, string>;
  };
  publicationReporting: {
    required: boolean;
    evidenceDueDaysAfterPublication?: number;
    frequency: string;
  };
};
type ReviewAssignment = {
  id: string;
  action: "assigned" | "cleared";
  reviewer?: { userId: string; email: string; displayName?: string };
  reason?: string;
  createdAt: string;
};
type ComplianceReview = {
  id: string;
  outcome: "compliant" | "noncompliant" | "inconclusive";
  note: string;
  evidence: Record<string, unknown>;
  assertionType: "authority_reviewed";
  effectOnPermission: "none";
  createdAt: string;
};
type UsageReport = {
  id: string;
  publicationUrl: string;
  publishedAt: string;
  platform?: string;
  declaredCreditText?: string;
  declaredBacklinkUrl?: string;
  metadata: Record<string, unknown>;
  evidence: Record<string, unknown>;
  assertionType: "requester_reported";
  effectOnPermission: "none";
  automatedChecks: {
    creditTextExactMatch: boolean | null;
    backlinkExactMatch: boolean | null;
    metadataExactMatches: Record<string, boolean>;
    reportedWithinDeadline: boolean | null;
    effect: "comparison_only";
  };
  currentReviewOutcome: "pending" | "compliant" | "noncompliant" | "inconclusive";
  reviews: ComplianceReview[];
  createdAt: string;
};
type Permission = {
  id: string;
  directions: string[];
  requester: { organizationId: string; organizationName?: string };
  authority: {
    claimId: string;
    organizationId: string;
    organizationName?: string;
    rightType: string;
    verificationStatus: string;
  };
  workKey: string;
  workTitle?: string;
  intendedUsage: string;
  territory: string;
  termStart?: string;
  termEnd?: string;
  context: Record<string, any>;
  provenance: Record<string, any>;
  licenseObligations: LicenseObligations;
  decisionRequirements: { exactAttributionRequired: boolean };
  status: string;
  decisionNote?: string;
  receiptId?: string;
  latestReceiptId?: string;
  settlementId?: string;
  reviewAssignment?: ReviewAssignment;
  usageReports?: UsageReport[];
  lifecycleRecords?: Array<{
    receiptId: string;
    eventType: "dispute" | "revocation" | "correction" | "expiry";
    status: string;
    reason?: string;
    priorReceiptId: string;
    replacementReceiptId?: string;
    createdAt: string;
  }>;
  requestedAt: string;
};
type SettlementBeneficiary = { id: string; name: string; identifier: string; shareBps: number; beneficiaryOrganizationId?: string };
type SettlementEntry = {
  id: string;
  kind: string;
  amountMinor: number;
  beneficiaryId?: string;
  periodStart?: string;
  periodEnd?: string;
  externalReference?: string;
  calculation?: Record<string, any>;
  createdAt: string;
};
type Settlement = {
  id: string;
  permissionRequestId: string;
  currency: string;
  minimumCommitmentMinor: number;
  minimumRecoupable: boolean;
  royaltyRateBps: number;
  royaltyBasis: string;
  status: string;
  assertionType: string;
  ledgerDigest: string;
  reconciliationCurrent: boolean;
  totals: {
    reserveMinor: number;
    royaltyAccruedMinor: number;
    obligationMinor: number;
    paymentReceivedMinor: number;
    payoutMinor: number;
    paymentVarianceMinor: number;
    payoutVarianceMinor: number;
    balanced: boolean;
    beneficiaries: Array<{ beneficiaryId: string; name: string; identifier: string; shareBps: number; obligationMinor: number; payoutMinor: number; varianceMinor: number }>;
  };
  beneficiaries: SettlementBeneficiary[];
  entries: SettlementEntry[];
  reconciliations: Array<{ id: string; receiptId: string; status: string; assertionType: string; ledgerDigest: string; createdAt: string }>;
};
type DdexAcknowledgement = {
  id: string;
  exchangeId: string;
  acknowledgementType: "transport" | "business";
  status: "received" | "processing" | "accepted" | "rejected" | "error";
  assertionType: "observed";
  effectOnPermission: "none";
  partnerMessageId?: string;
  payloadSha256?: string;
  evidence: Record<string, unknown>;
  receivedAt: string;
};
type CatalogSelection = { workKey: string; workTitle: string; artistName: string };
type CatalogClient = { id: string; name: string; externalReference: string; contactEmail?: string; createdAt: string };
type CatalogAsset = {
  id: string;
  workKey: string;
  version: number;
  itemType: "work" | "recording";
  title: string;
  artist?: string;
  territory: string;
  sourceReference?: string;
  assertionType: "catalog_metadata";
  authorityStatus: "unverified";
  client?: CatalogClient;
  assignment?: { id: string; reason: string; createdAt: string };
  createdAt: string;
};
type CatalogImportRow = {
  id: string;
  rowNumber: number;
  normalized: Record<string, any>;
  status: string;
  errors: string[];
  existingAsset?: CatalogAsset;
  resolution?: string;
  resolutionNote?: string;
  importedItemId?: string;
};
type CatalogImportBatch = {
  id: string;
  filename: string;
  fileSha256: string;
  status: string;
  summary: { total: number; counts: Record<string, number>; unresolved: number; importable: number; skipped: number };
  rows: CatalogImportRow[];
  createdAt: string;
  committedAt?: string;
  previewDigest: string;
};
type ReceiptInspection = {
  receipt: Record<string, any>;
  verification: { valid: boolean; payloadHashValid: boolean; signatureValid: boolean; transparencyHashValid: boolean; error?: string };
};
type TeamMember = { userId: string; email: string; displayName?: string; role: string; createdAt: string };
type OperatorClaim = Claim & {
  organization?: { id: string; name: string };
  artistName?: string;
  createdAt: string;
};
type AuthorityConflict = {
  id: string;
  workKey: string;
  rightType: string;
  status: string;
  basis: Record<string, any>;
  claimA: { claimId: string; organization?: { id: string; name: string }; territory?: string; status?: string; priorStatus: string; evidence?: Record<string, any> };
  claimB: { claimId: string; organization?: { id: string; name: string }; territory?: string; status?: string; priorStatus: string; evidence?: Record<string, any> };
};
type ApiCredential = {
  id: string;
  orgId: string;
  name: string;
  tokenPrefix: string;
  scopes: string[];
  status: "active" | "expired" | "revoked";
  createdAt: string;
  expiresAt: string;
  lastUsedAt?: string;
  revokedAt?: string;
};
type WebhookEndpoint = { id: string; url: string; events: string[]; secretHint: string; enabled: boolean; createdAt: string; updatedAt: string; disabledAt?: string };
type WebhookDelivery = {
  id: string;
  endpointId: string;
  event?: string;
  status: string;
  attemptCount: number;
  nextAttemptAt: string;
  lastStatusCode?: number;
  lastError?: string;
  deliveredAt?: string;
  deadLetteredAt?: string;
  createdAt: string;
  attempts: Array<{ id: string; attemptNumber: number; outcome: string; statusCode?: number; error?: string; durationMs: number; createdAt: string }>;
};
type AuditEvent = {
  id: string;
  organization?: { id: string; name: string };
  actor: { type: string; email?: string; displayName?: string; credentialId?: string; credentialName?: string; tokenPrefix?: string };
  action: string;
  resource: { type: string; id?: string };
  details: Record<string, unknown>;
  createdAt: string;
};

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function catalogSelectionFromMlcResult(result: Record<string, unknown>): CatalogSelection | null {
  const songCode = String(result.mlcSongCode || result.songCode || result.workIdentifier || "").trim();
  if (!songCode) return null;
  const workTitle = String(result.workTitle || result.title || "Untitled work").trim() || "Untitled work";
  const artistName = String(result.artist || result.primaryArtist || "").trim();
  return { workKey: `mlc:${songCode}`, workTitle, artistName };
}

async function api<T>(path: string, session?: SessionCredential, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (session) headers.set("X-Session-Id", session.id);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : body.detail?.message || body.error || message;
    } catch {
      // Keep the status-based message.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function downloadPrivateReceipt(receiptId: string, session: SessionCredential): Promise<void> {
  const receipt = await api<Record<string, unknown>>(`/v1/receipts/${encodeURIComponent(receiptId)}`, session);
  const url = URL.createObjectURL(new Blob([JSON.stringify(receipt, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `clef-receipt-${receiptId.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`;
  document.body.append(link);
  try { link.click(); }
  finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
}

function readSession(): SessionCredential | null {
  try {
    const value = safeStorageGet("session", SESSION_KEY);
    return value ? (JSON.parse(value) as SessionCredential) : null;
  } catch {
    return null;
  }
}

function humanize(value: string) {
  return LABELS[value] || value.replace(/[_.:]/g, " ").replace(/\b\w/g, (character: string) => character.toUpperCase());
}

function formatTimestamp(value?: string) {
  if (!value) return "Never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function createAiPolicyDefaults(preset: "review_each_ai_use" | "block_all_ai" = "review_each_ai_use"): AiPolicy {
  const state = preset === "review_each_ai_use" ? "requires_approval" : "blocked";
  return {
    schemaVersion: "clef.ai-policy.v1",
    inputs: Object.fromEntries(AI_INPUT_KEYS.map((key) => [key, state])),
    modelScopes: {
      private_single_tenant: state,
      shared_commercial_model: state,
      public_or_open_weights: "blocked",
    },
    limits: Object.fromEntries(AI_LIMIT_KEYS.map((key) => [key, null])),
    safeguards: Object.fromEntries(AI_SAFEGUARD_KEYS.map((key) => [key, true])),
  };
}

export function createPolicyDefaults(preset: "review_each_ai_use" | "block_all_ai" = "review_each_ai_use") {
  const usage = Object.fromEntries(USAGE_KEYS.map((key) => [key, "blocked"]));
  const aiState = preset === "review_each_ai_use" ? "requires_approval" : "blocked";
  AI_USAGE_KEYS.forEach((key) => { usage[key] = aiState; });
  return {
    usage,
    restrictions: Object.fromEntries(RESTRICTION_KEYS.map((key) => [key, "conditional"])),
    aiPolicy: createAiPolicyDefaults(preset),
  };
}

function Badge({ children, tone = "gray" }: { children: React.ReactNode; tone?: "gray" | "green" | "amber" | "red" | "blue" }) {
  const styles = {
    gray: "bg-slate-100 text-slate-700",
    green: "bg-emerald-100 text-emerald-800",
    amber: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-800",
    blue: "bg-blue-100 text-blue-800",
  };
  return <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${styles[tone]}`}>{children}</span>;
}

function Panel({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      {description && <p className="mt-1 text-sm text-slate-600">{description}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function LegalNotice({ nodeInfo, children }: { nodeInfo: NodeInfo | null; children?: React.ReactNode }) {
  return (
    <footer className="mx-auto max-w-7xl px-6 pb-10 text-xs leading-5 text-slate-500">
      {children && <p>{children}</p>}
      <p className={children ? "mt-2" : undefined}>
        Clef Rights Node is free software under the{" "}
        <a className="font-medium text-slate-700 underline" href="https://www.gnu.org/licenses/agpl-3.0.html" rel="noreferrer" target="_blank">GNU AGPL v3</a>
        {" "}and comes without warranty.
        {nodeInfo?.sourceCodeUrl ? <>{" "}<a className="font-medium text-slate-700 underline" href={nodeInfo.sourceCodeUrl} rel="noreferrer" target="_blank">Corresponding source for {nodeInfo.sourceCodeRevision}</a>.</> : <> {nodeInfo ? `Development revision: ${nodeInfo.sourceCodeRevision}. Configure SOURCE_CODE_URL before a public deployment.` : "Source metadata is temporarily unavailable."}</>}
      </p>
    </footer>
  );
}

function DeploymentBanner({ nodeInfo }: { nodeInfo: NodeInfo | null }) {
  if (!isPublicSandbox(nodeInfo)) return null;
  return (
    <aside className="border-b border-amber-300 bg-amber-50 px-6 py-3 text-sm text-amber-950" role="status">
      <div className="mx-auto max-w-7xl">
        <strong>Public sandbox · fictional examples.</strong>{" "}
        Explore with fictional names, identifiers and terms. Sessions expire and records may be reset. Registry, payment and model connections are isolated for this demonstration.{" "}
        {nodeInfo?.sourceCodeUrl ? <a className="font-medium underline" href={nodeInfo.sourceCodeUrl} rel="noreferrer" target="_blank">Inspect source revision {nodeInfo.sourceCodeRevision}</a> : <>Running source revision {nodeInfo?.sourceCodeRevision || "unknown"}.</>}
      </div>
    </aside>
  );
}

function SignIn({ onAuthenticated, nodeInfo }: { onAuthenticated: (credential: SessionCredential) => void; nodeInfo: NodeInfo | null }) {
  const [email, setEmail] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [devLink, setDevLink] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function requestLink(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setStatus("");
    try {
      const response = await api<{ sent: boolean; devLink?: string }>("/auth/invite", undefined, {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setStatus(response.sent ? "Check your inbox for a single-use sign-in link." : "Development link created.");
      setDevLink(response.devLink || null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not request a sign-in link.");
    } finally {
      setBusy(false);
    }
  }

  async function enterSandbox() {
    setBusy(true);
    setStatus("");
    try {
      const response = await api<{ session: SessionCredential }>("/v1/sandbox/session", undefined, { method: "POST" });
      safeStorageSet("session", SESSION_KEY, JSON.stringify(response.session));
      onAuthenticated(response.session);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not start a sandbox session.");
    } finally {
      setBusy(false);
    }
  }

  React.useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return;
    let cancelled = false;
    setBusy(true);
    api<{ session: SessionCredential }>(`/auth/validate?token=${encodeURIComponent(token)}`)
      .then((response) => {
        if (cancelled) return;
        safeStorageSet("session", SESSION_KEY, JSON.stringify(response.session));
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete("token");
        window.history.replaceState({}, "", `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`);
        onAuthenticated(response.session);
      })
      .catch((error) => !cancelled && setStatus(error instanceof Error ? error.message : "Sign-in link failed."))
      .finally(() => !cancelled && setBusy(false));
    return () => {
      cancelled = true;
    };
  }, [onAuthenticated]);

  return (
    <div className="min-h-screen bg-slate-50">
    <DeploymentBanner nodeInfo={nodeInfo} />
    <main className="mx-auto grid min-h-[calc(100vh-5rem)] max-w-6xl items-center gap-12 px-6 py-12 lg:grid-cols-2">
      <div>
        <Badge tone="blue">Clef Rights Node</Badge>
        <h1 className="mt-5 text-5xl font-semibold tracking-tight text-slate-950">Catalog controls for the AI licensing era.</h1>
        <p className="mt-5 max-w-xl text-lg leading-8 text-slate-600">
          Labels, publishers, PROs, CMOs, collectives, and rights administrators can manage represented catalogs, route licensing decisions, track provenance, and account for royalties.
        </p>
        <div className="mt-8 grid gap-3 text-sm text-slate-700 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4"><strong>Your catalog:</strong> connect recordings, compositions and the rights you administer.</div>
          <div className="rounded-xl border border-slate-200 bg-white p-4"><strong>Your artists:</strong> keep their conditions attached to each AI-use request.</div>
          <div className="rounded-xl border border-slate-200 bg-white p-4"><strong>Your decisions:</strong> assign reviewers and carry the agreed terms into a signed receipt.</div>
        </div>
      </div>
      {nodeInfo?.sandboxGuestAccess ? <section className="rounded-3xl border border-amber-200 bg-white p-8 shadow-xl shadow-slate-200/50">
        <h2 className="text-2xl font-semibold text-slate-950">Take a catalog from request to approval.</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">Explore a fictional label and publisher, review an AI-use request and verify the signed decision. Your anonymous session comes with a prepared catalog; you can also try the full setup flow.</p>
        <button type="button" disabled={busy} onClick={() => void enterSandbox()} className="mt-6 w-full rounded-xl bg-slate-950 px-4 py-3 font-medium text-white hover:bg-slate-800 disabled:opacity-50">{busy ? "Starting…" : "Explore the example catalog"}</button>
        {status && <p className="mt-4 text-sm text-slate-600" role="status">{status}</p>}
      </section> : <form onSubmit={requestLink} className="rounded-3xl border border-slate-200 bg-white p-8 shadow-xl shadow-slate-200/50">
        <h2 className="text-2xl font-semibold text-slate-950">Sign in to your node</h2>
        <p className="mt-2 text-sm text-slate-600">We’ll send a short-lived, single-use link to the address below. The server creates the session after the link is verified.</p>
        <label className="mt-6 block text-sm font-medium text-slate-800" htmlFor="signin-email">Email address</label>
        <input id="signin-email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100" placeholder="you@organization.com" />
        <button disabled={busy} className="mt-4 w-full rounded-xl bg-slate-950 px-4 py-3 font-medium text-white hover:bg-slate-800 disabled:opacity-50">{busy ? "Working…" : "Send secure link"}</button>
        {status && <p className="mt-4 text-sm text-slate-600" role="status">{status}</p>}
        {devLink && <a className="mt-3 block text-sm font-medium text-blue-700 underline" href={devLink}>Open development sign-in link</a>}
      </form>}
    </main>
    <LegalNotice nodeInfo={nodeInfo} />
    </div>
  );
}

function OrganizationSetup({ session, onCreated }: { session: SessionCredential; onCreated: () => void }) {
  const [step, setStep] = React.useState(1);
  const [name, setName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [organizationType, setOrganizationType] = React.useState("rights_holder");
  const [territory, setTerritory] = React.useState("worldwide");
  const [controlledRights, setControlledRights] = React.useState<string[]>(() => defaultControlledRightsForOrganizationType("rights_holder"));
  const [aiPreset, setAiPreset] = React.useState<"review_each_ai_use" | "block_all_ai">("review_each_ai_use");
  const [error, setError] = React.useState("");
  const isRequester = organizationType === "requester";
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (step < 3 && !(step === 2 && isRequester)) {
      setError("");
      setStep((current) => current + 1);
      return;
    }
    try {
      await api("/v1/organizations", session, {
        method: "POST",
        body: JSON.stringify({
          name,
          slug,
          organization_type: organizationType,
          default_territory: territory,
          controlled_right_types: controlledRights,
          ai_policy_preset: aiPreset,
        }),
      });
      onCreated();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Could not create organization.";
      setError(message);
      if (message.toLowerCase().includes("slug")) setStep(1);
    }
  }
  function toggleRight(right: string) {
    setControlledRights((current) => current.includes(right) ? current.filter((item) => item !== right) : [...current, right]);
  }
  const titles = ["Name the organization", isRequester ? "Set its requester scope" : "Set its authority scope", "Choose a conservative AI baseline"];
  const descriptions = [
    "A rights holder can publish policies and decide requests. A producer, agency, or AI company can register as a requester without claiming rights.",
    isRequester ? "A requester can search verified authority and submit scoped uses without declaring control of a catalog." : "These defaults guide new claims and policies. They do not prove that the organization controls a right.",
    "The baseline is copied into each new work policy. Every field can be changed before that policy is published.",
  ];
  const setupSteps = isRequester && step > 1 ? [1, 2] : [1, 2, 3];
  return (
    <div className="mx-auto max-w-2xl py-16">
      <div className="mb-5 flex gap-2">{setupSteps.map((item) => <Badge key={item} tone={item === step ? "blue" : item < step ? "green" : "gray"}>Step {item}</Badge>)}</div>
      <Panel title={titles[step - 1]} description={descriptions[step - 1]}>
        <form onSubmit={submit} className="space-y-4">
          {step === 1 && <>
            <label className="block text-sm font-medium text-slate-800">Organization name<input required value={name} onChange={(event) => { setName(event.target.value); if (!slug) setSlug(event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); }} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3" placeholder="Label, publisher, PRO, collective, or artist" /></label>
            <label className="block text-sm font-medium text-slate-800">Node slug<input required value={slug} onChange={(event) => setSlug(event.target.value.toLowerCase())} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3" placeholder="organization-slug" pattern="[a-z0-9_-]+" /></label>
          </>}
          {step === 2 && <>
            <label className="block text-sm font-medium text-slate-800">Organization type<select value={organizationType} onChange={(event) => { const value = event.target.value; setOrganizationType(value); setControlledRights(defaultControlledRightsForOrganizationType(value)); }} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3">{[["rights_holder", "Rights holder"], ["artist", "Artist"], ["label", "Label"], ["publisher", "Publisher"], ["administrator", "Rights administrator"], ["pro", "Performing rights organization (PRO)"], ["cmo", "Collective management organization (CMO)"], ["collective", "Rights collective"], ["requester", "Requester / producer"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="mt-2 block text-xs font-normal text-slate-500">Selecting a type applies suggested rights. Review them before continuing; the selection never proves authority.</span></label>
            <label className="block text-sm font-medium text-slate-800">Default territory<input required value={territory} onChange={(event) => setTerritory(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3" placeholder="worldwide, US, CA, or another declared territory" /></label>
            {isRequester ? <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-slate-700"><strong>No rights claim is created.</strong><p className="mt-1">This organization can request permission and inspect its receipts. It cannot publish or approve authority without later joining a rights-holding organization.</p></div> : <fieldset><legend className="mb-2 text-sm font-medium text-slate-800">Rights this organization expects to administer</legend><div className="grid gap-2 sm:grid-cols-3">{RIGHT_TYPES.map((right) => <label key={right} className="flex items-center gap-2 rounded-xl border border-slate-200 p-3 text-sm"><input type="checkbox" checked={controlledRights.includes(right)} onChange={() => toggleRight(right)} />{humanize(right)}</label>)}</div><p className="mt-2 text-xs text-slate-500">Each authority claim still requires evidence and operator review.</p></fieldset>}
          </>}
          {step === 3 && <fieldset><legend className="sr-only">AI policy baseline</legend><div className="space-y-3">
            <label className={`block cursor-pointer rounded-2xl border p-4 ${aiPreset === "review_each_ai_use" ? "border-blue-500 bg-blue-50" : "border-slate-200"}`}><div className="flex gap-3"><input type="radio" name="ai-preset" value="review_each_ai_use" checked={aiPreset === "review_each_ai_use"} onChange={() => setAiPreset("review_each_ai_use")} /><div><strong>Review every AI request</strong><Badge tone="blue">Recommended</Badge><p className="mt-1 text-sm text-slate-600">Training, grounding, embeddings, stems, lyrics, and generated outputs require a scoped license. Public or open-weight models remain blocked.</p></div></div></label>
            <label className={`block cursor-pointer rounded-2xl border p-4 ${aiPreset === "block_all_ai" ? "border-blue-500 bg-blue-50" : "border-slate-200"}`}><div className="flex gap-3"><input type="radio" name="ai-preset" value="block_all_ai" checked={aiPreset === "block_all_ai"} onChange={() => setAiPreset("block_all_ai")} /><div><strong>Block all AI use</strong><p className="mt-1 text-sm text-slate-600">Every AI operation and source asset starts blocked. A work policy must be edited before any AI request can proceed.</p></div></div></label>
          </div></fieldset>}
          <div className="flex gap-3">{step > 1 && <button type="button" onClick={() => { setError(""); setStep((current) => current - 1); }} className="rounded-xl border border-slate-300 px-5 py-3 font-medium">Back</button>}<button disabled={step === 2 && !isRequester && controlledRights.length === 0} className="flex-1 rounded-xl bg-blue-700 px-4 py-3 font-medium text-white disabled:opacity-40">{isRequester && step === 2 ? "Create requester organization" : step === 3 ? "Create organization with these defaults" : "Continue"}</button></div>
          {error && <p className="text-sm text-red-700">{error}</p>}
        </form>
      </Panel>
    </div>
  );
}

function MlcCatalogSearch({ session, organization, onSelect }: { session: SessionCredential; organization: Organization; onSelect: (selection: CatalogSelection) => void }) {
  const [authorized, setAuthorized] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [writer, setWriter] = React.useState("");
  const [results, setResults] = React.useState<Record<string, any>[]>([]);
  const [message, setMessage] = React.useState("");
  React.useEffect(() => {
    void api<{ mlc: Array<{ name: string; authorized: boolean }> }>("/v1/integrations/capabilities")
      .then((data) => setAuthorized(Boolean(data.mlc.find((item) => item.name === "catalog_lookup")?.authorized)))
      .catch((error) => setMessage(error.message));
  }, []);
  async function search(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      const response = await api<{ results: Record<string, any>[] }>(`/v1/organizations/${organization.id}/catalog/mlc/search/works`, session, { method: "POST", body: JSON.stringify({ title: title || null, writer_lastname: writer || null }) });
      setResults(response.results);
      if (response.results.length === 0) setMessage("No works matched this search in The MLC.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "The MLC search failed."); }
  }
  return <details className="rounded-xl border border-slate-200 bg-slate-50 p-4"><summary className="cursor-pointer font-medium text-slate-900">Find a musical work in The MLC</summary>{authorized ? <div className="mt-4 space-y-3"><form onSubmit={search} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]"><input value={title} onChange={(event) => setTitle(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2" placeholder="Work title" /><input value={writer} onChange={(event) => setWriter(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2" placeholder="Writer last name" /><button disabled={!title && !writer} className="rounded-lg bg-slate-900 px-4 py-2 font-medium text-white disabled:opacity-40">Search The MLC</button></form><p className="text-xs text-slate-500">The MLC supplies work references and publishing claims in a U.S. administrative context. DSP-supplied recording metadata is processed as received. Your organization supplies master ownership, controlled-share and territorial authority evidence for each decision.</p><div className="space-y-2">{results.map((result, index) => { const selection = catalogSelectionFromMlcResult(result); const workTitle = selection?.workTitle || String(result.workTitle || result.title || "Untitled work"); const songCode = selection?.workKey.replace(/^mlc:/, "") || ""; const artist = selection?.artistName || String(result.artist || result.primaryArtist || ""); return <div key={`${songCode || workTitle}-${index}`} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3"><div><strong>{workTitle}</strong><p className="text-xs text-slate-600">{artist || "Artist not supplied"} · {songCode || "No durable song code returned by The MLC"}</p></div><button type="button" disabled={!selection} onClick={() => selection && onSelect(selection)} className="rounded-lg border border-blue-300 px-3 py-2 text-sm font-medium text-blue-800 disabled:opacity-40">Use this work</button></div>; })}</div></div> : <p className="mt-3 text-sm text-slate-600">The MLC catalog lookup is disabled. Add the operator-managed credentials for The MLC and `catalog_lookup` capability, or enter a durable identifier manually below.</p>}{message && <p className="mt-3 text-sm text-slate-600">{message}</p>}</details>;
}

function Policies({ session, organization }: { session: SessionCredential; organization: Organization }) {
  const organizationDefaults = React.useMemo(() => {
    const fallback = createPolicyDefaults((organization.profile?.aiPolicyPreset as "review_each_ai_use" | "block_all_ai") || "review_each_ai_use");
    const saved = organization.profile?.policyDefaults;
    return saved ? { usage: saved.matrix.usage, restrictions: saved.matrix.restrictions, aiPolicy: saved.aiPolicy } : fallback;
  }, [organization.profile]);
  const [policies, setPolicies] = React.useState<Policy[]>([]);
  const [catalogAssets, setCatalogAssets] = React.useState<CatalogAsset[]>([]);
  const [workKey, setWorkKey] = React.useState("");
  const [workTitle, setWorkTitle] = React.useState("");
  const [artistName, setArtistName] = React.useState("");
  const [version, setVersion] = React.useState(0);
  const [usage, setUsage] = React.useState<Record<string, string>>(() => ({ ...organizationDefaults.usage }));
  const [restrictions, setRestrictions] = React.useState<Record<string, string>>(() => ({ ...organizationDefaults.restrictions }));
  const [aiPolicy, setAiPolicy] = React.useState<AiPolicy>(() => structuredClone(organizationDefaults.aiPolicy));
  const [message, setMessage] = React.useState("");

  const load = React.useCallback(async () => {
    const [policyResponse, catalogResponse] = await Promise.all([
      api<{ policies: Policy[] }>(`/v1/organizations/${organization.id}/rights`, session),
      api<{ assets: CatalogAsset[] }>(`/v1/organizations/${organization.id}/catalog/assets`, session),
    ]);
    setPolicies(policyResponse.policies);
    setCatalogAssets(catalogResponse.assets);
  }, [organization.id, session]);
  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);

  function edit(policy: Policy) {
    setWorkKey(policy.workKey);
    setWorkTitle(policy.contract?.metadata?.workTitle || "");
    setArtistName(policy.artistName);
    setVersion(policy.version);
    setUsage({ ...policy.matrix.usage });
    setRestrictions({ ...policy.matrix.restrictions });
    setAiPolicy(structuredClone(policy.contract?.aiPolicy || createAiPolicyDefaults("block_all_ai")));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function reset() {
    setWorkKey("");
    setWorkTitle("");
    setArtistName("");
    setVersion(0);
    setUsage({ ...organizationDefaults.usage });
    setRestrictions({ ...organizationDefaults.restrictions });
    setAiPolicy(structuredClone(organizationDefaults.aiPolicy));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      await api(`/v1/organizations/${organization.id}/rights/${encodeURIComponent(workKey)}`, session, {
        method: "PUT",
        body: JSON.stringify({
          artist_name: artistName,
          expected_version: version,
          contract: { policyVersion: "clef.rights-policy.v2", matrix: { usage, restrictions }, aiPolicy, metadata: { workTitle } },
        }),
      });
      setMessage("Policy published as a new immutable version.");
      reset();
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Policy save failed.");
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1.25fr_.75fr]">
      <Panel title={version ? `Edit policy v${version}` : "Publish a rights policy"} description="Declare every use and restriction. Omitted categories are blocked, and each publication creates an immutable version.">
          {!version && <MlcCatalogSearch session={session} organization={organization} onSelect={(selection) => { setWorkKey(selection.workKey); setWorkTitle(selection.workTitle); if (selection.artistName) setArtistName(selection.artistName); }} />}
        <form onSubmit={save} className="mt-6 space-y-6">
          {!version && catalogAssets.length > 0 && <label className="block text-sm font-medium text-slate-800">Start from the managed catalog<select value="" onChange={(event) => { const asset = catalogAssets.find((item) => item.id === event.target.value); if (asset) { setWorkKey(asset.workKey); setWorkTitle(asset.title); setArtistName(asset.artist || ""); } }} className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2"><option value="">Choose a catalog work or enter one below</option>{catalogAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.title} — {asset.artist || "Artist not supplied"} ({asset.workKey}; v{asset.version})</option>)}</select><span className="mt-1 block text-xs font-normal text-slate-500">Catalog selection fills metadata only. Publishing a policy still does not prove authority.</span></label>}
          <div className="grid gap-3 sm:grid-cols-3">
            <input required disabled={version > 0} value={workKey} onChange={(event) => setWorkKey(event.target.value)} className="rounded-xl border border-slate-300 px-3 py-2 disabled:bg-slate-100" placeholder="Work key (e.g. mlc:12345)" />
            <input required value={workTitle} onChange={(event) => setWorkTitle(event.target.value)} className="rounded-xl border border-slate-300 px-3 py-2" placeholder="Work title" />
            <input required value={artistName} onChange={(event) => setArtistName(event.target.value)} className="rounded-xl border border-slate-300 px-3 py-2" placeholder="Artist / creator name" />
          </div>
          <Matrix title="Non-AI uses covered by this policy" keys={STANDARD_USAGE_KEYS} values={usage} options={["blocked", "requires_approval", "allowed"]} onChange={setUsage} />
          <Matrix title="AI operations" keys={AI_USAGE_KEYS} values={usage} options={["blocked", "requires_approval", "allowed"]} onChange={setUsage} />
          <Matrix title="Legacy AI compatibility" keys={LEGACY_AI_USAGE_KEYS} values={usage} options={["blocked", "requires_approval", "allowed"]} onChange={setUsage} />
          <p className="-mt-4 text-xs leading-5 text-slate-500">Legacy recursive training remains explicit for older integrations. It is still an AI operation and requires the same scoped request and safeguards.</p>
          <AiPolicyEditor value={aiPolicy} onChange={setAiPolicy} />
          <Matrix title="Context restrictions" keys={RESTRICTION_KEYS} values={restrictions} options={["allowed", "conditional", "denied"]} onChange={setRestrictions} />
          <div className="flex gap-3"><button className="rounded-xl bg-blue-700 px-5 py-2.5 font-medium text-white">{version ? "Publish next version" : "Publish policy"}</button>{version > 0 && <button type="button" onClick={reset} className="rounded-xl border border-slate-300 px-5 py-2.5">Cancel</button>}</div>
          {message && <p className="text-sm text-slate-700">{message}</p>}
        </form>
      </Panel>
      <Panel title="Published policies" description="An edit creates a new version. If another member publishes first, the stale edit is rejected.">
        <div className="space-y-3">
          {policies.length === 0 && <p className="text-sm text-slate-500">No policy has been published by this organization.</p>}
          {policies.map((policy) => <button key={policy.id} onClick={() => edit(policy)} className="w-full rounded-xl border border-slate-200 p-4 text-left hover:border-blue-300"><div className="flex justify-between gap-2"><strong>{policy.contract?.metadata?.workTitle || policy.workKey}</strong><Badge tone="blue">v{policy.version}</Badge></div><p className="mt-1 text-sm text-slate-600">{policy.artistName} · {policy.workKey}</p><p className="mt-2 text-xs text-slate-500">Grounded generation: {policy.matrix.usage.ai_grounded_generation || "blocked"} · Embeddings: {policy.matrix.usage.ai_embedding_creation || "blocked"}</p></button>)}
        </div>
      </Panel>
    </div>
  );
}

function Matrix({ title, keys, values, options, onChange }: { title: string; keys: readonly string[]; values: Record<string, string>; options: string[]; onChange: React.Dispatch<React.SetStateAction<Record<string, string>>> }) {
  return <fieldset><legend className="mb-3 font-medium text-slate-900">{title}</legend><div className="grid gap-2 sm:grid-cols-2">{keys.map((key) => <label key={key} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm"><span>{humanize(key)}</span><select value={values[key]} onChange={(event) => onChange((current) => ({ ...current, [key]: event.target.value }))} className="rounded-md border border-slate-300 px-2 py-1">{options.map((option) => <option key={option}>{option}</option>)}</select></label>)}</div></fieldset>;
}

function AiPolicyEditor({ value, onChange }: { value: AiPolicy; onChange: React.Dispatch<React.SetStateAction<AiPolicy>> }) {
  const setInputs: React.Dispatch<React.SetStateAction<Record<string, string>>> = (next) => onChange((current) => ({ ...current, inputs: typeof next === "function" ? next(current.inputs) : next }));
  const setScopes: React.Dispatch<React.SetStateAction<Record<string, string>>> = (next) => onChange((current) => ({ ...current, modelScopes: typeof next === "function" ? next(current.modelScopes) : next }));
  return <section className="space-y-5 rounded-2xl border border-blue-200 bg-blue-50/40 p-4"><div><h3 className="font-medium text-slate-950">AI license scope</h3><p className="mt-1 text-sm text-slate-600">Operation permission is only the first gate. Declare which source materials, model environments, limits, and controls a license may cover.</p></div><Matrix title="Source materials supplied to the AI system" keys={AI_INPUT_KEYS} values={value.inputs} options={["blocked", "requires_approval", "allowed"]} onChange={setInputs} /><Matrix title="Model environment" keys={AI_MODEL_SCOPE_KEYS} values={value.modelScopes} options={["blocked", "requires_approval", "allowed"]} onChange={setScopes} /><fieldset><legend className="font-medium text-slate-900">Numerical license limits</legend><p className="mt-1 text-xs text-slate-500">A blank value means the limit must be settled in the individual license. It never means unlimited.</p><div className="mt-3 grid gap-3 sm:grid-cols-2">{AI_LIMIT_KEYS.map((key) => <label key={key} className="text-sm text-slate-700">{humanize(key)}<input type="number" min="0" value={value.limits[key] ?? ""} onChange={(event) => onChange((current) => ({ ...current, limits: { ...current.limits, [key]: event.target.value === "" ? null : Number(event.target.value) } }))} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" placeholder="Set per license" /></label>)}</div></fieldset><fieldset><legend className="font-medium text-slate-900">Controls required in every approved AI license</legend><div className="mt-3 grid gap-2 sm:grid-cols-2">{AI_SAFEGUARD_KEYS.map((key) => <label key={key} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"><input type="checkbox" checked={value.safeguards[key]} onChange={(event) => onChange((current) => ({ ...current, safeguards: { ...current.safeguards, [key]: event.target.checked } }))} />{humanize(key)}</label>)}</div></fieldset></section>;
}

export function Catalog({ session, organization }: { session: SessionCredential; organization: Organization }) {
  const [clients, setClients] = React.useState<CatalogClient[]>([]);
  const [assets, setAssets] = React.useState<CatalogAsset[]>([]);
  const [imports, setImports] = React.useState<CatalogImportBatch[]>([]);
  const [batch, setBatch] = React.useState<CatalogImportBatch | null>(null);
  const [clientName, setClientName] = React.useState("");
  const [clientReference, setClientReference] = React.useState("");
  const [clientEmail, setClientEmail] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [confirmImport, setConfirmImport] = React.useState(false);
  const [resolutionNotes, setResolutionNotes] = React.useState<Record<string, string>>({});
  const [assignmentClients, setAssignmentClients] = React.useState<Record<string, string>>({});
  const [assignmentReasons, setAssignmentReasons] = React.useState<Record<string, string>>({});
  const [message, setMessage] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const busyRef = React.useRef(false);
  const batchSequence = React.useRef(0);
  React.useEffect(() => () => { batchSequence.current += 1; }, [organization.id, session.id]);
  function startWrite() {
    if (busyRef.current) return false;
    busyRef.current = true; batchSequence.current += 1; setBusy(true); setMessage(""); return true;
  }
  function endWrite() { busyRef.current = false; setBusy(false); }


  const load = React.useCallback(async () => {
    const [clientResponse, assetResponse, importResponse] = await Promise.all([
      api<{ clients: CatalogClient[] }>(`/v1/organizations/${organization.id}/catalog/clients`, session),
      api<{ assets: CatalogAsset[] }>(`/v1/organizations/${organization.id}/catalog/assets`, session),
      api<{ imports: CatalogImportBatch[] }>(`/v1/organizations/${organization.id}/catalog/imports`, session),
    ]);
    setClients(clientResponse.clients);
    setAssets(assetResponse.assets);
    setImports(importResponse.imports);
  }, [organization.id, session]);

  const loadBatch = React.useCallback(async (batchId: string) => {
    const current = ++batchSequence.current;
    const response = await api<CatalogImportBatch>(`/v1/organizations/${organization.id}/catalog/imports/${batchId}`, session);
    if (current !== batchSequence.current) return;
    setBatch(response); setResolutionNotes({}); setConfirmImport(false);
  }, [organization.id, session]);

  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);

  async function createClient(event: React.FormEvent) {
    event.preventDefault();
    if (!startWrite()) return;
    try {
      await api(`/v1/organizations/${organization.id}/catalog/clients`, session, { method: "POST", body: JSON.stringify({ name: clientName, external_reference: clientReference, contact_email: clientEmail || null }) });
      setClientName(""); setClientReference(""); setClientEmail(""); setMessage("Managed client created. Its reference can now be used in CSV imports.");
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not create the managed client."); }
    finally { endWrite(); }
  }

  async function downloadTemplate() {
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/v1/organizations/${organization.id}/catalog/import-template`, { headers: { "X-Session-Id": session.id } });
      if (!response.ok) throw new Error(`Template request failed (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = "clef-catalog-template.csv"; anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not download the template."); }
  }

  async function previewImport(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    if (!startWrite()) return;
    try {
      const body = new FormData(); body.append("file", file);
      const response = await api<CatalogImportBatch>(`/v1/organizations/${organization.id}/catalog/imports/csv`, session, { method: "POST", body });
      setBatch(response); setConfirmImport(false); setMessage(response.status === "committed" ? "This exact file was already committed; no duplicate records were created." : "Preview created. Review every flagged row before committing.");
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not preview the catalog."); }
    finally { endWrite(); }
  }

  async function resolve(row: CatalogImportRow, resolution: "skip" | "new_version") {
    if (!batch) return;
    const note = (resolutionNotes[row.id] || "").trim();
    if (!note) return;
    if (!startWrite()) return;
    try {
      await api(`/v1/organizations/${organization.id}/catalog/imports/${batch.id}/rows/${row.id}/resolution`, session, { method: "POST", body: JSON.stringify({ resolution, note, expected_preview_digest: batch.previewDigest }) });
      await loadBatch(batch.id);
      setMessage(resolution === "skip" ? `Row ${row.rowNumber} will be skipped.` : `Row ${row.rowNumber} will become a new immutable catalog version.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not resolve the conflict."); }
    finally { endWrite(); }
  }

  async function refreshImport() {
    if (!batch || !startWrite()) return;
    try {
      const response = await api<CatalogImportBatch>(`/v1/organizations/${organization.id}/catalog/imports/${batch.id}/refresh`, session,
        { method: "POST", body: JSON.stringify({ expected_preview_digest: batch.previewDigest }) });
      setBatch(response); setConfirmImport(false); setResolutionNotes({});
      setMessage("Preview refreshed against the current catalog and client list. Review flagged rows and confirm the import again.");
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not refresh this preview."); }
    finally { endWrite(); }
  }

  async function commitImport() {
    if (!batch || !confirmImport) return;
    if (!startWrite()) return;
    try {
      const response = await api<CatalogImportBatch>(`/v1/organizations/${organization.id}/catalog/imports/${batch.id}/commit`, session, { method: "POST", body: JSON.stringify({ confirm_import: true, expected_preview_digest: batch.previewDigest }) });
      setBatch(response); setConfirmImport(false); setMessage(`${response.summary.counts.imported || 0} catalog records committed. Catalog metadata remains separate from authority evidence.`);
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not commit the catalog."); }
    finally { endWrite(); }
  }

  async function assign(asset: CatalogAsset) {
    const reason = (assignmentReasons[asset.id] || "").trim();
    if (!reason) return;
    if (!startWrite()) return;
    try {
      const selectedClient = assignmentClients[asset.id] ?? asset.client?.id ?? "";
      await api(`/v1/organizations/${organization.id}/catalog/assets/${asset.id}/assignment`, session, { method: "POST", body: JSON.stringify({ client_id: selectedClient || null, reason }) });
      setAssignmentReasons((current) => ({ ...current, [asset.id]: "" })); setMessage(`Assignment history appended for ${asset.title}.`); await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not change the client assignment."); }
    finally { endWrite(); }
  }

  return <div className="space-y-6">
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 text-sm text-slate-700"><strong className="text-slate-950">Bring your catalog and the evidence behind its rights into one workflow.</strong><p className="mt-1">Import identifiers and metadata, publish the creator’s conditions, and submit the mandate for each right and territory. Verified authority enables scoped approvals.</p></section>
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title="1. Create managed clients" description="Use a stable client reference from your royalty or contract system to connect imported records with the right artist or songwriter. References are stored lowercase and matched without case.">
        <form onSubmit={createClient} className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm font-medium text-slate-800">Client or artist name
            <input required value={clientName} onChange={(event) => setClientName(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal" placeholder="For example: Mara Vale" />
          </label>
          <label className="text-sm font-medium text-slate-800">Client reference
            <input required value={clientReference} onChange={(event) => setClientReference(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal" placeholder="For example: artist-0042" />
          </label>
          <label className="text-sm font-medium text-slate-800 sm:col-span-2">Client contact email (optional)
            <input type="email" value={clientEmail} onChange={(event) => setClientEmail(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal" placeholder="artist@example.com" />
          </label>
          <button disabled={busy} className="rounded-xl bg-slate-950 px-4 py-2.5 font-medium text-white sm:col-span-2 disabled:opacity-40">Create managed client</button>
        </form><div className="mt-4 space-y-2">{clients.length === 0 && <p className="text-sm text-slate-500">No managed clients yet. Create these before importing rows that use client_reference.</p>}{clients.map((client) => <div key={client.id} className="flex items-center justify-between rounded-lg border border-slate-200 p-3 text-sm"><div><strong>{client.name}</strong><p className="text-xs text-slate-500">{client.externalReference}{client.contactEmail ? ` · ${client.contactEmail}` : ""}</p></div><Badge>managed client</Badge></div>)}</div></Panel>
      <Panel title="2. Preview a catalog CSV" description="The preview checks identifiers, client references, duplicate rows and conflicts. Review the results, then confirm which records to add."><div className="flex flex-wrap gap-2"><button type="button" onClick={downloadTemplate} className="rounded-lg border border-blue-300 px-3 py-2 text-sm font-medium text-blue-800">Download CSV template</button><Badge tone="blue">10,000 rows maximum</Badge><Badge>10 MB maximum</Badge></div><form onSubmit={previewImport} className="mt-4 space-y-3"><input aria-label="Catalog CSV" type="file" accept=".csv,text/csv" required onChange={(event) => setFile(event.target.files?.[0] || null)} className="block w-full rounded-xl border border-slate-300 bg-white p-3 text-sm" /><button disabled={!file || busy} className="rounded-xl bg-blue-700 px-4 py-2.5 font-medium text-white disabled:opacity-40">Upload and preview</button></form><div className="mt-5"><h3 className="text-sm font-medium text-slate-900">Recent imports</h3><div className="mt-2 space-y-2">{imports.length === 0 && <p className="text-sm text-slate-500">No catalog files have been staged.</p>}{imports.slice(0, 5).map((item) => <button key={item.id} disabled={busy} onClick={() => void loadBatch(item.id).catch(error => setMessage(error.message))} className="flex w-full items-center justify-between rounded-lg border border-slate-200 p-3 text-left text-sm"><span><strong>{item.filename}</strong><span className="ml-2 text-xs text-slate-500">{item.summary.total} rows</span></span><Badge tone={item.status === "committed" ? "green" : item.summary.unresolved ? "amber" : "blue"}>{item.status}</Badge></button>)}</div></div></Panel>
    </div>
    {!batch && <Panel title="3. Review and commit" description="After upload, inspect every row here. Invalid rows must be corrected; catalog conflicts require a written skip or immutable-version decision before commit."><p className="text-sm text-slate-500">No preview selected. Upload a CSV above or reopen a recent import.</p></Panel>}
    {batch && <Panel title={`3. Review ${batch.filename}`} description={`SHA-256 ${batch.fileSha256}. Exact-file replays return this batch instead of creating duplicates.`}><div className="flex flex-wrap gap-2"><Badge tone={batch.status === "committed" ? "green" : "blue"}>{batch.status}</Badge><Badge>{batch.summary.total} rows</Badge><Badge tone={batch.summary.unresolved ? "amber" : "green"}>{batch.summary.unresolved} unresolved</Badge><Badge tone="blue">{batch.summary.importable} importable</Badge><Badge>{batch.summary.skipped} skipped</Badge></div>{batch.status === "preview" && <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm"><button type="button" disabled={busy} onClick={() => void refreshImport()} className="font-medium text-blue-800 disabled:opacity-40">Refresh preview</button><p className="mt-1 text-slate-600">Recheck the same file after a catalog or client change. Previous row decisions stay in the audit history; refreshed rows require a new review.</p></div>}<div className="mt-4 space-y-3">{batch.rows.map((row) => <article key={row.id} className={`rounded-xl border p-4 ${row.status === "invalid" || row.status === "conflict" ? "border-amber-300 bg-amber-50/40" : "border-slate-200"}`}><div className="flex flex-wrap items-start justify-between gap-2"><div><strong>Row {row.rowNumber} · {row.normalized.title || "Untitled"}</strong><p className="mt-1 break-all text-xs text-slate-500">{row.normalized.work_key || "No durable identifier"} · {row.normalized.client_reference || "unassigned"}</p></div><Badge tone={row.status === "imported" ? "green" : row.status === "conflict" || row.status === "invalid" ? "amber" : row.status.startsWith("resolved") ? "blue" : "gray"}>{humanize(row.status)}</Badge></div>{row.errors.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-amber-900">{row.errors.map((error) => <li key={error}>{error}</li>)}</ul>}{row.existingAsset && <p className="mt-3 text-sm text-slate-600">Existing v{row.existingAsset.version}: {row.existingAsset.title} · {row.existingAsset.artist || "Artist not supplied"} · managed client {row.existingAsset.client?.name || "Unassigned"} · source {row.existingAsset.sourceReference || "not supplied"}</p>}{row.status === "conflict" && <div className="mt-3 space-y-2"><textarea aria-label={`Resolution note for row ${row.rowNumber}`} value={resolutionNotes[row.id] || ""} onChange={(event) => setResolutionNotes((current) => ({ ...current, [row.id]: event.target.value }))} className="min-h-20 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm" placeholder="Record the evidence for skipping this row or creating a corrected version." /><div className="flex flex-wrap gap-2"><button disabled={busy || !(resolutionNotes[row.id] || "").trim()} onClick={() => void resolve(row, "new_version")} className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Create immutable next version</button><button disabled={busy || !(resolutionNotes[row.id] || "").trim()} onClick={() => void resolve(row, "skip")} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium disabled:opacity-40">Skip this row</button></div></div>}{row.resolutionNote && <p className="mt-2 text-xs text-slate-500">Resolution: {row.resolutionNote}</p>}</article>)}</div>{batch.status === "preview" && <div className="mt-5 rounded-xl border border-slate-300 bg-slate-50 p-4"><label className="flex items-start gap-3 text-sm"><input type="checkbox" checked={confirmImport} onChange={(event) => setConfirmImport(event.target.checked)} className="mt-1" /><span><strong>Commit these catalog records as immutable versions.</strong><span className="mt-1 block text-slate-600">I reviewed these catalog records. Rights and territorial authority will be established through separate evidence review.</span></span></label><button disabled={busy || !confirmImport || batch.summary.unresolved > 0} onClick={() => void commitImport()} className="mt-4 rounded-xl bg-emerald-700 px-5 py-2.5 font-medium text-white disabled:opacity-40">Commit catalog</button>{batch.summary.unresolved > 0 && <p className="mt-2 text-xs text-amber-800">Add missing clients, then refresh the preview. Correct invalid file contents in your CSV and upload the revised file; review catalog conflicts above.</p>}</div>}</Panel>}
    <Panel title="4. Managed catalog" description="This list shows the latest version of each work or recording. A change of managed client adds a dated assignment, preserving the earlier history."><div className="grid gap-3 lg:grid-cols-2">{assets.length === 0 && <p className="text-sm text-slate-500">No catalog records have been committed.</p>}{assets.map((asset) => <article key={asset.id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div><strong>{asset.title}</strong><p className="mt-1 text-sm text-slate-600">{asset.artist || "Artist not supplied"} · {humanize(asset.itemType)} · {asset.territory}</p><p className="mt-1 break-all font-mono text-xs text-slate-500">{asset.workKey}</p></div><Badge tone="blue">v{asset.version}</Badge></div><div className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">Catalog metadata · rights reviewed separately under Authority</div><p className="mt-3 text-sm"><span className="text-slate-500">Managed client:</span> {asset.client?.name || "Unassigned"}</p><details className="mt-3"><summary className="cursor-pointer text-sm font-medium text-blue-800">Append a client assignment</summary><div className="mt-3 space-y-2"><select aria-label={`Managed client for ${asset.title}`} value={assignmentClients[asset.id] ?? asset.client?.id ?? ""} onChange={(event) => setAssignmentClients((current) => ({ ...current, [asset.id]: event.target.value }))} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"><option value="">Unassigned</option>{clients.map((client) => <option key={client.id} value={client.id}>{client.name} · {client.externalReference}</option>)}</select><textarea aria-label={`Assignment reason for ${asset.title}`} value={assignmentReasons[asset.id] || ""} onChange={(event) => setAssignmentReasons((current) => ({ ...current, [asset.id]: event.target.value }))} className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Required reason: contract change, administration transfer, or correction" /><button disabled={busy || !(assignmentReasons[asset.id] || "").trim()} onClick={() => void assign(asset)} className="rounded-lg border border-blue-300 px-3 py-2 text-sm font-medium text-blue-800 disabled:opacity-40">Append assignment</button></div></details></article>)}</div></Panel>
    {message && <p role="status" className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">{message}</p>}
  </div>;
}

function Authority({ session, organization }: { session: SessionCredential; organization: Organization }) {
  const controlledRightTypes = organization.profile?.controlledRightTypes?.length ? organization.profile.controlledRightTypes : [...RIGHT_TYPES];
  const [claims, setClaims] = React.useState<Claim[]>([]);
  const [policies, setPolicies] = React.useState<Policy[]>([]);
  const [policyId, setPolicyId] = React.useState("");
  const [rightType, setRightType] = React.useState(controlledRightTypes[0] || "composition");
  const [territory, setTerritory] = React.useState(organization.profile?.defaultTerritory || "worldwide");
  const [source, setSource] = React.useState("");
  const [reference, setReference] = React.useState("");
  const [evidenceUri, setEvidenceUri] = React.useState("");
  const [documentSha256, setDocumentSha256] = React.useState("");
  const [share, setShare] = React.useState("");
  const [message, setMessage] = React.useState("");
  const load = React.useCallback(async () => {
    const [claimResponse, policyResponse] = await Promise.all([
      api<{ claims: Claim[] }>(`/v1/organizations/${organization.id}/authority-claims`, session),
      api<{ policies: Policy[] }>(`/v1/organizations/${organization.id}/rights`, session),
    ]);
    setClaims(claimResponse.claims); setPolicies(policyResponse.policies);
  }, [organization.id, session]);
  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api("/v1/authority-claims", session, { method: "POST", body: JSON.stringify({ org_id: organization.id, rights_contract_id: policyId, right_type: rightType, territory, evidence: { source: source.trim(), reference: reference.trim(), share: share.trim() || undefined, evidenceUri: evidenceUri || undefined, documentSha256: documentSha256 || undefined } }) });
      setMessage("Authority claim sent to the node operator for evidence review."); setSource(""); setShare(""); setReference(""); setEvidenceUri(""); setDocumentSha256(""); await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Claim failed."); }
  }
  const inputClass = "mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal";
  return <div className="grid gap-6 lg:grid-cols-2">
    <Panel title="Submit an authority claim" description="Identify the right, territory, controlled share, and supporting record. A node operator reviews the evidence before verifying the claim.">
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm font-medium text-slate-800">Published policy
          <select required value={policyId} onChange={(event) => setPolicyId(event.target.value)} className={inputClass}>
            <option value="">Select a published policy</option>
            {policies.map((policy) => <option key={policy.id} value={policy.id}>{policy.contract?.metadata?.workTitle || policy.workKey} — {policy.artistName} ({policy.workKey})</option>)}
          </select>
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm font-medium text-slate-800">Right administered
            <select value={rightType} onChange={(event) => setRightType(event.target.value)} className={inputClass}>{controlledRightTypes.map((item) => <option key={item} value={item}>{humanize(item)}</option>)}</select>
          </label>
          <label className="block text-sm font-medium text-slate-800">Territory
            <input required value={territory} onChange={(event) => setTerritory(event.target.value)} className={inputClass} placeholder="US, CA, or worldwide" />
          </label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm font-medium text-slate-800">Evidence source
            <input required maxLength={120} value={source} onChange={(event) => setSource(event.target.value)} className={inputClass} placeholder="e.g. signed recording agreement" />
          </label>
          <label className="block text-sm font-medium text-slate-800">Registry or document reference
            <input required maxLength={500} value={reference} onChange={(event) => setReference(event.target.value)} className={inputClass} placeholder="Your document or registry reference" />
          </label>
        </div>
        <label className="block text-sm font-medium text-slate-800">Controlled share (%) — optional
          <input type="number" min="0" max="100" step="any" value={share} onChange={(event) => setShare(event.target.value)} className={inputClass} aria-describedby="authority-share-help" placeholder="Enter the share supported by your evidence" />
        </label>
        <p id="authority-share-help" className="text-xs leading-5 text-slate-500">Enter the share your organization administers for this right and territory. Leave it blank when the evidence does not establish a percentage; the operator reviews it as an unspecified share.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm font-medium text-slate-800">Evidence location — optional
            <input type="text" inputMode="url" value={evidenceUri} onChange={(event) => setEvidenceUri(event.target.value)} className={inputClass} placeholder="https:// or urn:" />
          </label>
          <label className="block text-sm font-medium text-slate-800">Document SHA-256 — optional
            <input value={documentSha256} onChange={(event) => setDocumentSha256(event.target.value)} className={`${inputClass} font-mono`} placeholder="64 hexadecimal characters" />
          </label>
        </div>
        <p className="text-xs leading-5 text-slate-500">Keep private contracts in your document system. A stable location and SHA-256 fingerprint let the operator identify the exact artifact reviewed.</p>
        <button className="rounded-xl bg-blue-700 px-5 py-2.5 font-medium text-white">Send for review</button>
        {message && <p role="status" className="text-sm text-slate-600">{message}</p>}
      </form>
    </Panel>
    <Panel title="Authority record" description="Only a verified claim can receive or approve a permission request.">
      <div className="space-y-3">
        {claims.length === 0 && <p className="text-sm text-slate-500">No authority claim has been submitted.</p>}
        {claims.map((claim) => <div key={claim.id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-center justify-between"><strong>{policies.find(policy => policy.id === claim.rightsContractId)?.contract?.metadata?.workTitle || claim.workKey}</strong><Badge tone={claim.status === "verified" ? "green" : claim.status === "rejected" || claim.status === "revoked" ? "red" : "amber"}>{claim.status}</Badge></div><p className="mt-2 text-sm text-slate-600">{humanize(claim.rightType)} · {claim.territory}</p><p className="mt-1 break-all font-mono text-xs text-slate-500">{claim.workKey}</p>{["verified", "self_asserted", "disputed"].includes(claim.status) && <AuthorityWithdrawal key={`${session.id}:${organization.id}:${claim.id}`} apiBase={API_BASE} sessionId={session.id} organizationId={organization.id} claimId={claim.id} onChanged={load} />}</div>)}
      </div>
    </Panel>
  </div>;
}

export function RequestPermission({ session, organization }: { session: SessionCredential; organization: Organization }) {
  const [claims, setClaims] = React.useState<DirectoryClaim[]>([]);
  const [selectedId, setSelectedId] = React.useState("");
  const [usage, setUsage] = React.useState("ai_grounded_generation");
  const [territory, setTerritory] = React.useState(organization.profile?.defaultTerritory || "worldwide");
  const [termStart, setTermStart] = React.useState("");
  const [termEnd, setTermEnd] = React.useState("");
  const [scope, setScope] = React.useState(initialRequestScope);
  const [message, setMessage] = React.useState("");
  React.useEffect(() => void api<{ claims: DirectoryClaim[] }>("/v1/directory/authority-claims", session).then((data) => setClaims(data.claims)).catch((error) => setMessage(error.message)), [session]);
  const selected = claims.find((claim) => claim.id === selectedId);
  const requiredSafeguards = selected ? AI_SAFEGUARD_KEYS.filter((key) => selected.aiPolicy?.safeguards?.[key]) : [];
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!scope.contentConfirmed) { setMessage("Confirm the content categories before submitting."); return; }
    if (!selected) return;
    try {
      const response = await api<{ status: string }>("/v1/permission-requests", session, { method: "POST", body: JSON.stringify({ requester_org_id: organization.id, authority_claim_id: selected.id, intended_usage: usage, territory, term_start: termStart || null, term_end: termEnd || null, context: requestScopeContext(scope, usage), provenance: {} }) });
      setMessage(response.status === "approved" ? "Approved automatically under the published policy; a signed receipt was issued." : "Request sent to the verified rights authority.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Request failed."); }
  }
  return <Panel title="Request permission" description="Select a verified claim, then state the operation, source material, model environment, territory, and term. The receipt preserves that exact scope."><form onSubmit={submit} className="space-y-4"><select required value={selectedId} onChange={(event) => { setSelectedId(event.target.value); setScope((current) => ({ ...current, acceptedSafeguards: [], contentConfirmed: false })); }} className="w-full rounded-xl border border-slate-300 px-3 py-2"><option value="">Select a verified work and authority</option>{claims.map((claim) => <option key={claim.id} value={claim.id}>{claim.workTitle || claim.workKey} — {claim.organization.name} ({claim.rightType}; {claim.workKey})</option>)}</select>{selected && <div className="rounded-xl bg-slate-50 p-4 text-sm"><div className="flex justify-between"><span>Published rule for {humanize(usage)}</span><Badge tone={selected.matrix.usage[usage] === "allowed" ? "green" : selected.matrix.usage[usage] === "blocked" ? "red" : "amber"}>{selected.matrix.usage[usage]}</Badge></div><p className="mt-2 text-slate-600">This claim covers {humanize(selected.rightType)} in {selected.territory}. Master, composition, lyrics, performance, voice, or likeness permission may still be required.</p></div>}<div className="grid gap-3 md:grid-cols-2"><select value={usage} onChange={(event) => setUsage(event.target.value)} className="rounded-xl border border-slate-300 px-3 py-2"><optgroup label="AI operations">{AI_USAGE_KEYS.map((item) => <option key={item} value={item}>{humanize(item)}</option>)}</optgroup><optgroup label="Other uses">{STANDARD_USAGE_KEYS.map((item) => <option key={item} value={item}>{humanize(item)}</option>)}</optgroup><optgroup label="Legacy compatibility">{LEGACY_AI_USAGE_KEYS.map((item) => <option key={item} value={item}>{humanize(item)}</option>)}</optgroup></select><input required value={territory} onChange={(event) => setTerritory(event.target.value)} className="rounded-xl border border-slate-300 px-3 py-2" aria-label="Requested territory" placeholder="Country codes, e.g. US, CA; or worldwide" /><input required type="text" inputMode="numeric" pattern="\d{4}-\d{2}-\d{2}" aria-label="License start date" placeholder="Start date · YYYY-MM-DD" value={termStart} onChange={(event) => setTermStart(event.target.value)} className="rounded-xl border border-slate-300 px-3 py-2" /><input required type="text" inputMode="numeric" pattern="\d{4}-\d{2}-\d{2}" aria-label="License end date" placeholder="End date · YYYY-MM-DD" value={termEnd} onChange={(event) => setTermEnd(event.target.value)} className="rounded-xl border border-slate-300 px-3 py-2" /></div><RequestScopeFields usage={usage} value={scope} onChange={setScope} label={humanize} requiredSafeguards={requiredSafeguards} policy={selected && { restrictions: selected.matrix.restrictions }} /><button disabled={!requestScopeComplete(scope, usage, requiredSafeguards) || !selected || !termStart || !termEnd || selected.matrix.usage[usage] === "blocked"} className="rounded-xl bg-blue-700 px-5 py-2.5 font-medium text-white disabled:cursor-not-allowed disabled:opacity-40">Request permission</button>{message && <p className="text-sm text-slate-600">{message}</p>}</form></Panel>;
}

function PermissionScope({ permission }: { permission: Permission }) {
  const aiUse = permission.context?.aiUse as Record<string, any> | undefined;
  const evaluation = permission.context?.policyEvaluation as { state?: string; reasons?: string[] } | undefined;
  const term = permission.termStart && permission.termEnd ? `${permission.termStart} through ${permission.termEnd}` : "Not declared — approval is blocked";
  return <section className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm"><h3 className="font-medium text-slate-900">Declared license scope</h3><dl className="mt-3 grid gap-3 sm:grid-cols-3"><div><dt className="text-xs uppercase tracking-wide text-slate-500">Term</dt><dd className={!permission.termStart || !permission.termEnd ? "font-medium text-red-700" : "text-slate-800"}>{term}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-500">Project</dt><dd>{permission.context?.releaseTitle || "Not supplied"}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-500">Policy evaluation</dt><dd>{evaluation?.state ? humanize(evaluation.state) : "Not recorded"}</dd></div></dl><p className="mt-3"><strong>Content categories:</strong> {Array.isArray(permission.context?.restrictionCategories) ? (permission.context.restrictionCategories.map(humanize).join(", ") || "Requester declares none apply") : "Declaration needed for content restrictions"}</p>{aiUse && <div className="mt-4 border-t border-slate-200 pt-3"><dl className="grid gap-3 sm:grid-cols-2"><div><dt className="text-xs uppercase tracking-wide text-slate-500">Source material</dt><dd>{(aiUse.inputAssets || []).map(humanize).join(", ") || "Not declared"}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-500">Model environment</dt><dd>{humanize(aiUse.modelScope || "not_declared")}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-500">Durations</dt><dd>Source {aiUse.sourceDurationSeconds ?? "unset"}s · output {aiUse.outputDurationSeconds ?? "unset"}s · lyrics {aiUse.lyricCharacters ?? "unset"} characters</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-500">Retention</dt><dd>Source {aiUse.sourceRetentionDays ?? "unset"} days · embeddings {aiUse.embeddingRetentionDays ?? "unset"} days</dd></div><div className="sm:col-span-2"><dt className="text-xs uppercase tracking-wide text-slate-500">Accepted controls</dt><dd>{(aiUse.acceptedSafeguards || []).map(humanize).join(", ") || "None declared"}</dd></div></dl></div>}{evaluation?.reasons?.length ? <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-slate-600">Policy evaluation trace</summary><p className="mt-2 break-words text-xs text-slate-500">{evaluation.reasons.join(" · ")}</p></details> : null}{Object.keys(permission.provenance || {}).length > 0 && <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-slate-600">Submitted provenance</summary><pre className="mt-2 overflow-auto text-xs text-slate-600">{JSON.stringify(permission.provenance, null, 2)}</pre></details>}</section>;
}

function DdexAcknowledgementEvidence({ session, exchangeId }: { session: SessionCredential; exchangeId: string }) {
  const [rows, setRows] = React.useState<DdexAcknowledgement[]>([]);
  const [acknowledgementType, setAcknowledgementType] = React.useState("transport");
  const [status, setStatus] = React.useState("received");
  const [partnerMessageId, setPartnerMessageId] = React.useState("");
  const [evidenceReference, setEvidenceReference] = React.useState("");
  const [payload, setPayload] = React.useState("");
  const [message, setMessage] = React.useState("");

  const load = React.useCallback(async () => {
    setRows(await api<DdexAcknowledgement[]>(`/v1/ddex/exchanges/${exchangeId}/acknowledgements`, session));
  }, [exchangeId, session]);

  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      await api<DdexAcknowledgement>(`/v1/ddex/exchanges/${exchangeId}/acknowledgements`, session, {
        method: "POST",
        body: JSON.stringify({
          acknowledgement_type: acknowledgementType,
          status,
          partner_message_id: partnerMessageId || null,
          media_type: payload ? "application/xml" : null,
          payload: payload || null,
          evidence: evidenceReference ? { reference: evidenceReference } : {},
          idempotency_key: `ddex-ack-${crypto.randomUUID()}`,
        }),
      });
      setPartnerMessageId("");
      setEvidenceReference("");
      setPayload("");
      setMessage("Observed partner evidence appended. The permission record was not changed.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Acknowledgement could not be recorded.");
    }
  }

  return <section className="rounded-lg border border-slate-200 bg-white p-4"><h3 className="text-sm font-medium text-slate-950">Partner acknowledgement evidence</h3><p className="mt-1 text-xs text-slate-600">Record what the transport or counterparty returned. This append-only observation never grants permission and does not prove legal authority.</p><form onSubmit={submit} className="mt-3 space-y-3"><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm text-slate-700">Evidence type<select value={acknowledgementType} onChange={(event) => setAcknowledgementType(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"><option value="transport">Transport acknowledgement</option><option value="business">Business acknowledgement</option></select></label><label className="text-sm text-slate-700">Observed status<select value={status} onChange={(event) => setStatus(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"><option value="received">Received</option><option value="processing">Processing</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option><option value="error">Error</option></select></label><label className="text-sm text-slate-700">Partner message ID<input value={partnerMessageId} onChange={(event) => setPartnerMessageId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="text-sm text-slate-700">Evidence reference<input value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} placeholder="SFTP receipt, ticket, or immutable URI" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label></div><label className="block text-sm text-slate-700">Raw response payload (optional)<textarea value={payload} onChange={(event) => setPayload(event.target.value)} className="mt-1 min-h-24 w-full rounded-lg border border-slate-300 p-3 font-mono text-xs" /></label><button disabled={!partnerMessageId && !evidenceReference && !payload} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Append observed evidence</button></form>{message && <p className="mt-3 text-sm text-slate-700">{message}</p>}{rows.length > 0 && <div className="mt-4 space-y-2">{rows.map((row) => <article key={row.id} className="rounded-lg border border-slate-200 p-3 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><span><Badge>{humanize(row.acknowledgementType)}</Badge><Badge tone={row.status === "accepted" || row.status === "received" ? "green" : row.status === "rejected" || row.status === "error" ? "red" : "amber"}>{row.status}</Badge></span><span className="text-slate-500">{formatTimestamp(row.receivedAt)}</span></div><p className="mt-2 text-slate-700">Partner message {row.partnerMessageId || "not supplied"} · permission effect: none</p>{row.payloadSha256 && <p className="mt-1 break-all font-mono text-slate-500">SHA-256 {row.payloadSha256}</p>}</article>)}</div>}</section>;
}

function DdexMwlExport({ session, permission }: { session: SessionCredential; permission: Permission }) {
  const [authorized, setAuthorized] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [workTitle, setWorkTitle] = React.useState(permission.workTitle || permission.workKey);
  const [workIdentifier, setWorkIdentifier] = React.useState(permission.workKey);
  const [role, setRole] = React.useState("owner");
  const [rightsType, setRightsType] = React.useState("MechanicalRight");
  const [useType, setUseType] = React.useState("UserMakeAvailableUserProvided");
  const [distribution, setDistribution] = React.useState("Internet");
  const [rightShare, setRightShare] = React.useState("100");
  const [royaltyPercentage, setRoyaltyPercentage] = React.useState("100");
  const [confirmed, setConfirmed] = React.useState(false);
  const [xml, setXml] = React.useState("");
  const [exchangeId, setExchangeId] = React.useState("");
  const [filename, setFilename] = React.useState("ddex-mwl.xml");
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    void api<{ ddex: Array<{ name: string; authorized: boolean }> }>("/v1/integrations/capabilities")
      .then((result) => setAuthorized(Boolean(result.ddex.find((item) => item.name === "permission_request_exchange")?.authorized)))
      .catch((error) => setMessage(error.message));
  }, []);
  const ineligibleScope = permission.intendedUsage === "derivative_remix" || permission.intendedUsage.startsWith("ai_");
  const canRequest = permission.directions.includes("outbound");
  const canDecide = permission.directions.includes("inbound") && ["approved", "rejected"].includes(permission.status);
  async function exportXml(kind: "license-request" | "license-decision") {
    setBusy(true); setMessage(""); setXml("");
    try {
      const response = await fetch(`${API_BASE}/v1/permission-requests/${permission.id}/ddex/mwl/${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Session-Id": session.id },
        body: JSON.stringify({
          work_title: workTitle,
          work_identifier: workIdentifier,
          rights_controller_role: role,
          iswc: permission.workKey.startsWith("iswc:") ? permission.workKey.slice(5) : null,
          territory: "US",
          rights_type: rightsType,
          use_type: useType,
          distribution_channel_type: distribution || null,
          right_share_percentage: rightShare,
          royalty_rate_calculation_type: "NegotiatedRoyaltyRate",
          royalty_percentage: royaltyPercentage,
          percentage_type: "PercentageOfNetRevenue",
          confirm_composition_only_scope: confirmed,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.message || `DDEX export failed (${response.status})`);
      }
      const generated = await response.text();
      const disposition = response.headers.get("Content-Disposition") || "";
      const name = disposition.match(/filename="([^"]+)"/)?.[1] || "ddex-mwl.xml";
      setXml(generated); setFilename(name); setExchangeId(response.headers.get("X-Clef-DDEX-Exchange-Id") || "");
      setMessage(`Schema-valid ${response.headers.get("X-Clef-DDEX-Profile") || "MWL"} XML generated and retained with its SHA-256 digest.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "DDEX export failed."); }
    finally { setBusy(false); }
  }
  function downloadXml() {
    const url = URL.createObjectURL(new Blob([xml], { type: "application/xml" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
  }
  if (permission.authority.rightType !== "composition") return null;
  return <details className="mt-4 rounded-xl border border-blue-200 bg-blue-50/30 p-4"><summary className="cursor-pointer text-sm font-medium text-slate-950">DDEX MWL exchange · US musical-work rights</summary><div className="mt-4 space-y-4">{ineligibleScope && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><strong>This Clef scope cannot be exported through MWL.</strong><p className="mt-1">Derivative-remix and AI permissions contain rights and conditions MWL does not represent. Keep the Clef receipt as the governing artifact.</p></div>}{!authorized && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><strong>DDEX exchange is not authorized on this node.</strong><p className="mt-1">The operator must install the pinned MWL schemas, configure both DPIDs and party names, confirm implementation terms, and enable the bilateral capability. A DDEX membership is not required merely to implement the standard.</p></div>}<div className="grid gap-3 sm:grid-cols-2"><label className="text-sm text-slate-700">Musical-work title<input required value={workTitle} onChange={(event) => setWorkTitle(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" /></label><label className="text-sm text-slate-700">Work identifier<input required value={workIdentifier} onChange={(event) => setWorkIdentifier(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" /></label><label className="text-sm text-slate-700">Controller role<select value={role} onChange={(event) => setRole(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"><option value="owner">Owner</option><option value="agent">Agent</option></select></label><label className="text-sm text-slate-700">Musical-work right<select value={rightsType} onChange={(event) => setRightsType(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"><option>MechanicalRight</option><option>PerformingRight</option><option>PrintRight</option><option>SynchronizationRight</option></select></label><label className="text-sm text-slate-700">MWL use type<select value={useType} onChange={(event) => setUseType(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"><option>AsPerContract</option><option>Podcast</option><option>NonInteractiveStream</option><option>OnDemandStream</option><option>PermanentDownload</option><option>Stream</option><option>UserMakeAvailableLabelProvided</option><option>UserMakeAvailableUserProvided</option><option>Webcast</option></select></label><label className="text-sm text-slate-700">Distribution channel<select value={distribution} onChange={(event) => setDistribution(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"><option>Internet</option><option>InternetAndMobile</option><option>MobileTelephone</option><option>Physical</option><option>Broadcast</option><option>AsPerContract</option></select></label><label className="text-sm text-slate-700">Controlled share (%)<input type="number" min="0" max="100" step="0.0001" value={rightShare} onChange={(event) => setRightShare(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" /></label><label className="text-sm text-slate-700">Royalty percentage<input type="number" min="0" max="100" step="0.0001" value={royaltyPercentage} onChange={(event) => setRoyaltyPercentage(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" /></label></div><label className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-3 text-sm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1" /><span><strong>Export US musical-work scope only.</strong><span className="mt-1 block text-slate-600">I understand this XML does not convey master, derivative, lyric, voice, likeness, or AI rights and still requires a configured bilateral exchange partner.</span></span></label><div className="flex flex-wrap gap-2">{canRequest && <button disabled={busy || !authorized || ineligibleScope || !confirmed || !workTitle || !workIdentifier} onClick={() => void exportXml("license-request")} className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Generate license request XML</button>}{canDecide && <button disabled={busy || !authorized || ineligibleScope || !confirmed || !workTitle || !workIdentifier} onClick={() => void exportXml("license-decision")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Generate {permission.status} decision XML</button>}</div>{message && <p className="text-sm text-slate-700">{message}</p>}{xml && <section className="rounded-lg border border-emerald-200 bg-emerald-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><Badge tone="green">schema valid</Badge><span className="ml-2 text-xs text-slate-600">Exchange {exchangeId}</span></div><button onClick={downloadXml} className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm font-medium text-emerald-900">Download XML</button></div><details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-slate-700">Inspect generated XML</summary><pre className="mt-2 max-h-96 overflow-auto rounded-lg bg-white p-3 text-xs text-slate-700">{xml}</pre></details></section>}{exchangeId && <DdexAcknowledgementEvidence session={session} exchangeId={exchangeId} />}</div></details>;
}

function ReceiptVerification({ inspection }: { inspection: ReceiptInspection }) {
  const { receipt, verification } = inspection;
  const payload = receipt.payload || {};
  return <section className={`mt-3 rounded-xl border p-4 text-sm ${verification.valid ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium text-slate-950">Independent receipt verification</h3><Badge tone={verification.valid ? "green" : "red"}>{verification.valid ? "Valid Ed25519 receipt" : "Verification failed"}</Badge></div><dl className="mt-3 grid gap-3 sm:grid-cols-4"><div><dt className="text-xs uppercase tracking-wide text-slate-500">Payload hash</dt><dd>{verification.payloadHashValid ? "Valid" : "Invalid"}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-500">Signature</dt><dd>{verification.signatureValid ? "Valid" : "Invalid"}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-500">Transparency entry</dt><dd>{verification.transparencyHashValid ? `Valid · #${receipt.transparency?.sequence}` : "Invalid"}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-500">Issued</dt><dd>{payload.issuedAt || "Unknown"}</dd></div></dl><p className="mt-3 break-all text-xs text-slate-600">Receipt {payload.receiptId} · key {receipt.proof?.keyId} · payload SHA-256 {receipt.proof?.payloadHash}</p>{verification.error && <p className="mt-2 text-sm text-red-700">{verification.error}</p>}</section>;
}


type BeneficiaryDraft = { name: string; identifier: string; shareBps: string };

function financialIdempotencyKey(prefix: string): string {
  return clientOperationKey(prefix);
}

export function SettlementLedgerCore({ session, permission }: { session: SessionCredential; permission: Permission }) {
  const [settlement, setSettlement] = React.useState<Settlement | null>(null);
  const settlementIdRef = React.useRef(permission.settlementId);
  const financialBusyRef = React.useRef(false);
  const [financialBusy, setFinancialBusy] = React.useState(false);
  const pendingFinancialRequest = React.useRef<{ fingerprint: string; body: string } | null>(null);
  const [loading, setLoading] = React.useState(Boolean(permission.settlementId));
  const [currency, setCurrency] = React.useState("USD");
  const [minimumMinor, setMinimumMinor] = React.useState("0");
  const [royaltyRateBps, setRoyaltyRateBps] = React.useState("1000");
  const [royaltyBasis, setRoyaltyBasis] = React.useState("net_revenue");
  const [minimumRecoupable, setMinimumRecoupable] = React.useState(true);
  const [termsConfirmed, setTermsConfirmed] = React.useState(false);
  const [beneficiaryDrafts, setBeneficiaryDrafts] = React.useState<BeneficiaryDraft[]>([{ name: "", identifier: "", shareBps: "10000" }]);
  const [entryKind, setEntryKind] = React.useState(permission.directions.includes("inbound") ? "payment_received" : "reserve");
  const [entryAmount, setEntryAmount] = React.useState("");
  const [entryBeneficiary, setEntryBeneficiary] = React.useState("");
  const [externalReference, setExternalReference] = React.useState("");
  const [evidenceReference, setEvidenceReference] = React.useState("");
  const [basisAmount, setBasisAmount] = React.useState("");
  const [periodStart, setPeriodStart] = React.useState(permission.termStart || "");
  const [periodEnd, setPeriodEnd] = React.useState(permission.termEnd || "");
  const [statementReference, setStatementReference] = React.useState("");
  const [reconciliationNote, setReconciliationNote] = React.useState("");
  const [reconciliationInspections, setReconciliationInspections] = React.useState<Record<string, ReceiptInspection>>({});
  const [message, setMessage] = React.useState("");
  const inbound = permission.directions.includes("inbound");
  const outbound = permission.directions.includes("outbound");

  const load = React.useCallback(async () => {
    if (!settlementIdRef.current && !permission.settlementId) { setSettlement(null); setLoading(false); return; }
    setLoading(true);
    try {
      setSettlement(await api<Settlement>(`/v1/permission-requests/${permission.id}/settlement`, session));
    } finally {
      setLoading(false);
    }
  }, [permission.id, permission.settlementId, session]);

  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);

  function updateBeneficiary(index: number, field: keyof BeneficiaryDraft, value: string) {
    setBeneficiaryDrafts((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: value } : row));
  }

  async function createTerms(event: React.FormEvent) {
    event.preventDefault();
    if (financialBusyRef.current) return;
    const minimum = Number(minimumMinor);
    const rate = Number(royaltyRateBps);
    const beneficiaries = beneficiaryDrafts.map((row) => ({ name: row.name.trim(), identifier: row.identifier.trim(), share_bps: Number(row.shareBps) }));
    if (![minimum, rate, ...beneficiaries.map((row) => row.share_bps)].every(Number.isSafeInteger)) { setMessage("Money and shares must use whole minor units and basis points."); return; }
    if (beneficiaries.reduce((sum, row) => sum + row.share_bps, 0) !== 10000) { setMessage("Beneficiary shares must total exactly 10,000 basis points."); return; }
    financialBusyRef.current = true;
    setFinancialBusy(true);
    try {
      const created = await api<Settlement>(`/v1/permission-requests/${permission.id}/settlement`, session, {
        method: "POST",
        body: JSON.stringify({ currency, minimum_commitment_minor: minimum, minimum_recoupable: minimumRecoupable, royalty_rate_bps: rate, royalty_basis: royaltyBasis, beneficiaries, terms: {}, confirm_immutable_terms: termsConfirmed }),
      });
      settlementIdRef.current = created.id;
      setSettlement(created);
      setMessage("Immutable settlement terms recorded. They remain provisional until a grant, external payment evidence, beneficiary payouts, and reconciliation exist.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          const existing = await api<Settlement>(`/v1/permission-requests/${permission.id}/settlement`, session);
          settlementIdRef.current = existing.id;
          setSettlement(existing);
          setMessage("Settlement terms already exist. Review the recorded terms below.");
        } catch { setMessage(error.message); }
      } else setMessage(error instanceof Error ? error.message : "Could not record settlement terms.");
    } finally { financialBusyRef.current = false; setFinancialBusy(false); }
  }

  async function recordFinancialOperation<T>(
    path: string,
    payload: Record<string, unknown>,
    onRecorded: (result: T) => void,
  ) {
    if (financialBusyRef.current) return;
    const fingerprint = JSON.stringify({ path, payload });
    if (pendingFinancialRequest.current && pendingFinancialRequest.current.fingerprint !== fingerprint) {
      setMessage("A previous submission still needs confirmation. Retry its unchanged details before recording another entry.");
      return;
    }
    if (!pendingFinancialRequest.current) {
      pendingFinancialRequest.current = {
        fingerprint,
        body: JSON.stringify({ ...payload, idempotency_key: financialIdempotencyKey("settlement") }),
      };
    }
    financialBusyRef.current = true;
    setFinancialBusy(true);
    try {
      const result = await api<T>(path, session, { method: "POST", body: pendingFinancialRequest.current.body });
      pendingFinancialRequest.current = null;
      onRecorded(result);
      try { await load(); }
      catch { setMessage("Recorded successfully. The refreshed ledger could not be loaded; use Refresh ledger to view it."); }
    } catch (error) {
      // Validation failures can be corrected. Ambiguous failures retain the exact
      // operation and key, so a retry cannot append a second immutable record.
      if (error instanceof ApiError && [400, 422].includes(error.status)) pendingFinancialRequest.current = null;
      const detail = error instanceof Error ? error.message : "Could not confirm the financial record.";
      setMessage(pendingFinancialRequest.current ? `${detail} Retry with the same details to confirm this submission.` : detail);
    } finally { financialBusyRef.current = false; setFinancialBusy(false); }
  }

  async function appendEntry(event: React.FormEvent) {
    event.preventDefault();
    if (!settlement) return;
    const amount = Number(entryAmount);
    if (!Number.isSafeInteger(amount) || amount <= 0) { setMessage("Enter a positive whole amount in currency minor units."); return; }
    await recordFinancialOperation(`/v1/settlements/${settlement.id}/entries`, {
          kind: entryKind,
          amount_minor: amount,
          beneficiary_id: ["payout", "payout_reversal"].includes(entryKind) ? entryBeneficiary : null,
          external_reference: externalReference.trim() || null,
          evidence: entryKind === "reserve" ? {} : { reference: evidenceReference.trim() || externalReference.trim() },
      }, () => {
      setEntryAmount(""); setExternalReference(""); setEvidenceReference("");
      setMessage(`${humanize(entryKind)} appended. Existing ledger records were not changed.`);
      });
  }

  async function calculateRoyalty(event: React.FormEvent) {
    event.preventDefault();
    if (!settlement) return;
    const amount = Number(basisAmount);
    if (!Number.isSafeInteger(amount) || amount <= 0) { setMessage("Enter a positive whole revenue amount in currency minor units."); return; }
    await recordFinancialOperation(`/v1/settlements/${settlement.id}/royalty-calculations`,
      { basis_amount_minor: amount, period_start: periodStart, period_end: periodEnd, external_reference: statementReference.trim(), evidence: { reference: statementReference.trim() } }, () => {
      setBasisAmount(""); setStatementReference("");
      setMessage("Royalty accrual calculated with exact integer rounding and appended to the ledger.");
      });
  }

  async function reconcile() {
    if (!settlement) return;
    await recordFinancialOperation<{ assertionType: string; status: string }>(`/v1/settlements/${settlement.id}/reconciliations`,
      { evidence: reconciliationNote.trim() ? { note: reconciliationNote.trim() } : {} }, (result) => {
      setMessage(result.assertionType === "paid" ? "Reconciled: obligation, received payment, and every beneficiary payout match exactly." : "Reconciliation recorded as provisional: one or more balances still differ.");
      setReconciliationNote("");
      });
  }

  async function inspectReconciliation(receiptId: string) {
    try {
      const receipt = await api<Record<string, any>>(`/v1/receipts/${receiptId}`, session);
      const verification = await api<ReceiptInspection["verification"]>("/v1/receipts/verify", undefined, { method: "POST", body: JSON.stringify({ receipt }) });
      setReconciliationInspections((current) => ({ ...current, [receiptId]: { receipt, verification } }));
    } catch (error) { setMessage(error instanceof Error ? error.message : "Reconciliation receipt verification failed."); }
  }

  async function downloadReconciliation(receiptId: string) {
    try { await downloadPrivateReceipt(receiptId, session); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Receipt download failed."); }
  }

  if (loading) return <section className="mt-4 rounded-xl border border-slate-200 p-4 text-sm text-slate-500">Loading settlement ledger…</section>;
  if (!settlement) return <section className="mt-4 rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-medium text-slate-950">Settlement ledger</h3><button type="button" disabled={financialBusy || loading} onClick={() => void load().catch(() => setMessage("Could not refresh the ledger. Try again."))} className="mt-2 text-sm font-medium text-blue-700 underline disabled:opacity-40">Refresh ledger</button><p className="mt-1 text-sm text-slate-600">A reserve or proposed fee is provisional. It never grants permission.</p></div><Badge tone="amber">not configured</Badge></div>{inbound ? <details className="mt-3"><summary className="cursor-pointer text-sm font-medium text-blue-800">Define immutable settlement terms</summary><form onSubmit={createTerms} className="mt-3 space-y-3 rounded-xl bg-slate-50 p-4"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><label className="text-sm">Currency<input required maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="text-sm">Minimum · minor units<input required type="number" min="0" value={minimumMinor} onChange={(event) => setMinimumMinor(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="text-sm">Royalty rate · basis points<input required type="number" min="0" max="10000" value={royaltyRateBps} onChange={(event) => setRoyaltyRateBps(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="text-sm">Royalty basis<select value={royaltyBasis} onChange={(event) => setRoyaltyBasis(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"><option value="net_revenue">Net revenue</option><option value="gross_revenue">Gross revenue</option><option value="net_receipts">Net receipts</option></select></label></div><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={minimumRecoupable} onChange={(event) => setMinimumRecoupable(event.target.checked)} />Minimum is recoupable against royalties</label><fieldset><legend className="text-sm font-medium">Beneficiaries · shares must total 10,000 bps</legend><div className="mt-2 space-y-2">{beneficiaryDrafts.map((row, index) => <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_10rem_auto]"><input required aria-label={`Beneficiary ${index + 1} name`} value={row.name} onChange={(event) => updateBeneficiary(index, "name", event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Artist or owner" /><input required aria-label={`Beneficiary ${index + 1} identifier`} value={row.identifier} onChange={(event) => updateBeneficiary(index, "identifier", event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="IPI, party ID, or contract ID" /><input required aria-label={`Beneficiary ${index + 1} share`} type="number" min="1" max="10000" value={row.shareBps} onChange={(event) => updateBeneficiary(index, "shareBps", event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Share bps" /><button type="button" disabled={beneficiaryDrafts.length === 1} onClick={() => setBeneficiaryDrafts((current) => current.filter((_, rowIndex) => rowIndex !== index))} className="rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-40">Remove</button></div>)}</div><button type="button" onClick={() => setBeneficiaryDrafts((current) => [...current, { name: "", identifier: "", shareBps: "" }])} className="mt-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">Add beneficiary</button></fieldset><label className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-slate-700"><input required type="checkbox" checked={termsConfirmed} onChange={(event) => setTermsConfirmed(event.target.checked)} className="mt-1" />I reviewed the currency, minimum, royalty basis, and complete split. These terms cannot be edited; a correction requires a replacement permission.</label><button disabled={financialBusy || !termsConfirmed} className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Record settlement terms</button></form></details> : <p className="mt-3 text-sm text-slate-500">The verified authority must define the fee, royalty basis, and complete beneficiary split.</p>}{message && <p className="mt-3 text-sm text-slate-700">{message}</p>}</section>;

  const authorityEntryKinds = ["payment_received", "payment_reversal", "payout", "payout_reversal", "royalty_adjustment_increase", "royalty_adjustment_decrease"];
  const entryKinds = inbound ? authorityEntryKinds : ["reserve", "reserve_release"];
  const latestReconciliation = settlement.reconciliations[settlement.reconciliations.length - 1];
  return <section className="mt-4 rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-medium text-slate-950">Settlement ledger</h3><button type="button" disabled={financialBusy || loading} onClick={() => void load().catch(() => setMessage("Could not refresh the ledger. Try again."))} className="mt-2 text-sm font-medium text-blue-700 underline disabled:opacity-40">Refresh ledger</button><p className="mt-1 text-sm text-slate-600">{settlement.minimumCommitmentMinor.toLocaleString()} {settlement.currency} minor-unit minimum · {(settlement.royaltyRateBps / 100).toLocaleString()}% of {humanize(settlement.royaltyBasis)}</p></div><Badge tone={settlement.assertionType === "paid" ? "green" : "amber"}>{settlement.assertionType}</Badge></div><dl className="mt-4 grid gap-3 sm:grid-cols-5">{[["Reserved", settlement.totals.reserveMinor], ["Royalty", settlement.totals.royaltyAccruedMinor], ["Obligation", settlement.totals.obligationMinor], ["Payment", settlement.totals.paymentReceivedMinor], ["Payouts", settlement.totals.payoutMinor]].map(([label, amount]) => <div key={String(label)}><dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt><dd className="font-medium text-slate-900">{Number(amount).toLocaleString()} <span className="text-xs font-normal text-slate-500">{settlement.currency} minor</span></dd></div>)}</dl><div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs uppercase text-slate-500"><tr><th className="py-2">Beneficiary</th><th>Share</th><th>Owed</th><th>Paid out</th><th>Variance</th></tr></thead><tbody>{settlement.totals.beneficiaries.map((row) => <tr key={row.beneficiaryId} className="border-t border-slate-100"><td className="py-2">{row.name}<span className="ml-1 text-xs text-slate-500">{row.identifier}</span></td><td>{row.shareBps / 100}%</td><td>{row.obligationMinor.toLocaleString()}</td><td>{row.payoutMinor.toLocaleString()}</td><td className={row.varianceMinor === 0 ? "text-emerald-700" : "text-amber-700"}>{row.varianceMinor.toLocaleString()}</td></tr>)}</tbody></table></div><p className="mt-3 break-all text-xs text-slate-500">Ledger SHA-256 {settlement.ledgerDigest}{latestReconciliation ? ` · latest reconciliation ${latestReconciliation.status}${settlement.reconciliationCurrent ? "" : " (stale after later entries)"}` : " · not reconciled"}</p>{latestReconciliation && <div className="mt-3 flex flex-wrap gap-2"><button onClick={() => inspectReconciliation(latestReconciliation.receiptId)} className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-900">Verify reconciliation receipt</button><button type="button" onClick={() => void downloadReconciliation(latestReconciliation.receiptId)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium">Download reconciliation receipt</button></div>}{latestReconciliation && reconciliationInspections[latestReconciliation.receiptId] && <ReceiptVerification inspection={reconciliationInspections[latestReconciliation.receiptId]} />}{entryKinds.length > 0 && <details className="mt-4 rounded-xl bg-slate-50 p-3"><summary className="cursor-pointer text-sm font-medium">Append financial evidence</summary><p className="mt-2 text-xs text-slate-600">Amounts use currency minor units. External references identify bank records, statements, or payout evidence; secrets do not belong here.</p>{inbound && permission.receiptId && <form onSubmit={calculateRoyalty} className="mt-3 grid gap-2 rounded-lg border border-slate-200 bg-white p-3 sm:grid-cols-2 lg:grid-cols-5"><input required type="number" min="1" aria-label="Royalty basis amount" value={basisAmount} onChange={(event) => setBasisAmount(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Revenue · minor units" /><input required aria-label="Royalty period start" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Period start YYYY-MM-DD" /><input required aria-label="Royalty period end" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Period end YYYY-MM-DD" /><input required aria-label="Royalty statement reference" value={statementReference} onChange={(event) => setStatementReference(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Statement evidence reference" /><button disabled={financialBusy} className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Calculate royalty</button></form>}<form onSubmit={appendEntry} className="mt-3 grid gap-2 rounded-lg border border-slate-200 bg-white p-3 sm:grid-cols-2 lg:grid-cols-6"><select value={entryKind} onChange={(event) => setEntryKind(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2">{entryKinds.map((kind) => <option key={kind} value={kind}>{humanize(kind)}</option>)}</select><input required type="number" min="1" aria-label="Financial entry amount" value={entryAmount} onChange={(event) => setEntryAmount(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Amount · minor units" />{["payout", "payout_reversal"].includes(entryKind) ? <select required aria-label="Payout beneficiary" value={entryBeneficiary} onChange={(event) => setEntryBeneficiary(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2"><option value="">Select beneficiary</option>{settlement.beneficiaries.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.identifier}</option>)}</select> : <span className="hidden lg:block" />}<input required={entryKind !== "reserve"} aria-label="External financial reference" value={externalReference} onChange={(event) => setExternalReference(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="External transaction reference" /><input required={entryKind !== "reserve"} aria-label="Financial evidence reference" value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Evidence digest or record ID" /><button disabled={financialBusy} className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Append entry</button></form></details>}{inbound && permission.receiptId && <div className="mt-4 flex flex-wrap items-center gap-2"><input value={reconciliationNote} onChange={(event) => setReconciliationNote(event.target.value)} className="min-w-72 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Reconciliation review note · optional" /><button disabled={financialBusy} onClick={reconcile} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white">Reconcile current ledger</button></div>}{settlement.entries.length > 0 && <details className="mt-4"><summary className="cursor-pointer text-xs font-medium text-slate-600">Immutable entry history · {settlement.entries.length}</summary><div className="mt-2 space-y-2">{settlement.entries.map((entry) => <div key={entry.id} className="flex flex-wrap justify-between gap-2 rounded-lg bg-slate-50 p-2 text-xs"><span>{humanize(entry.kind)} · {entry.amountMinor.toLocaleString()} {settlement.currency}{entry.periodStart ? ` · ${entry.periodStart} to ${entry.periodEnd}` : ""}</span><span className="text-slate-500">{entry.externalReference || "internal reserve"} · {formatTimestamp(entry.createdAt)}</span></div>)}</div></details>}{message && <p className="mt-3 text-sm text-slate-700">{message}</p>}</section>;
}


function SettlementLedger({ session, permission }: { session: SessionCredential; permission: Permission }) {
  return <><DdexMwlExport session={session} permission={permission} /><SettlementLedgerCore key={`${session.id}:${permission.id}`} session={session} permission={permission} /></>;
}


const ATTRIBUTION_PLACEMENTS = ["description", "metadata", "on_screen", "liner_notes", "credits_page", "other"] as const;

function clientOperationKey(prefix: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${suffix}`;
}

export function localDateTimeInputValue(date: Date, timezoneOffsetMinutes = date.getTimezoneOffset()): string {
  return new Date(date.getTime() - timezoneOffsetMinutes * 60_000).toISOString().slice(0, 16);
}

function parseObject(value: string): Record<string, unknown> {
  const parsed = value.trim() ? JSON.parse(value) : {};
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Enter a JSON object with field names and values.");
  return parsed as Record<string, unknown>;
}

function parseStringObject(value: string): Record<string, string> {
  const parsed = parseObject(value);
  const entries = Object.entries(parsed);
  if (entries.some(([key, item]) => !key.trim() || typeof item !== "string" || !item.trim())) {
    throw new Error("Every required metadata field needs a non-empty string value.");
  }
  return Object.fromEntries(entries.map(([key, item]) => [key.trim(), (item as string).trim()]));
}

function AssignmentAndDecision({ session, permission, members, onChanged }: { session: SessionCredential; permission: Permission; members: TeamMember[]; onChanged: () => Promise<void> }) {
  const exactAttributionRequired = permission.decisionRequirements?.exactAttributionRequired === true;
  const [reviewerUserId, setReviewerUserId] = React.useState(permission.reviewAssignment?.reviewer?.userId || "");
  const [assignmentReason, setAssignmentReason] = React.useState("");
  const [decisionNote, setDecisionNote] = React.useState("");
  const [attributionRequired, setAttributionRequired] = React.useState(exactAttributionRequired);
  const [creditText, setCreditText] = React.useState("");
  const [backlinkRequired, setBacklinkRequired] = React.useState(false);
  const [backlinkUrl, setBacklinkUrl] = React.useState("");
  const [placements, setPlacements] = React.useState<string[]>(exactAttributionRequired ? ["description"] : []);
  const [metadataFields, setMetadataFields] = React.useState("{}");
  const [reportingRequired, setReportingRequired] = React.useState(exactAttributionRequired);
  const [evidenceDueDays, setEvidenceDueDays] = React.useState("30");
  const [reportingFrequency, setReportingFrequency] = React.useState("once");
  const [message, setMessage] = React.useState("");

  React.useEffect(() => {
    setReviewerUserId(permission.reviewAssignment?.action === "assigned" ? permission.reviewAssignment.reviewer?.userId || "" : "");
  }, [permission.reviewAssignment?.id, permission.reviewAssignment?.action, permission.reviewAssignment?.reviewer?.userId]);

  const assignment = permission.reviewAssignment;
  const assignedElsewhere = assignment?.action === "assigned" && assignment.reviewer?.email?.toLowerCase() !== session.email.toLowerCase();
  const decisionMembers = members.filter((member) => ["owner", "admin", "rights_manager"].includes(member.role));
  let metadataValid = true;
  try { parseStringObject(metadataFields); } catch { metadataValid = false; }
  const approvalReady = Boolean(
    decisionNote.trim()
      && permission.termStart
      && permission.termEnd
      && !assignedElsewhere
      && metadataValid
      && (!attributionRequired || (creditText.trim() && placements.length > 0))
      && (!backlinkRequired || backlinkUrl.trim())
      && (!reportingRequired || Number(evidenceDueDays) > 0),
  );

  async function assignReviewer(clear = false) {
    if (!assignmentReason.trim()) { setMessage("Record why this case is being assigned or returned to the queue."); return; }
    if (!clear && !reviewerUserId) { setMessage("Choose a rights administrator before assigning the case."); return; }
    try {
      await api(`/v1/permission-requests/${permission.id}/review-assignments`, session, {
        method: "POST",
        body: JSON.stringify({ reviewer_user_id: clear ? null : reviewerUserId, reason: assignmentReason.trim() }),
      });
      setAssignmentReason("");
      setMessage(clear ? "Case returned to the shared rights queue." : "Case routed to the named rights administrator.");
      await onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Reviewer assignment failed."); }
  }

  async function decide(decision: "approved" | "rejected") {
    if (!decisionNote.trim()) { setMessage("Record the approval scope or rejection rationale before deciding."); return; }
    try {
      const body: Record<string, unknown> = { decision, note: decisionNote.trim() };
      if (decision === "approved") {
        body.obligations = {
          attribution: {
            required: attributionRequired,
            credit_text: creditText.trim() || null,
            backlink_required: backlinkRequired,
            backlink_url: backlinkUrl.trim() || null,
            placements,
            metadata_fields: parseStringObject(metadataFields),
          },
          publication_reporting_required: reportingRequired,
          publication_evidence_due_days: reportingRequired ? Number(evidenceDueDays) : null,
          usage_reporting_frequency: reportingRequired ? reportingFrequency : "once",
        };
      }
      await api(`/v1/permission-requests/${permission.id}/decide`, session, { method: "POST", body: JSON.stringify(body) });
      setMessage(`Request ${decision}.`);
      setDecisionNote("");
      await onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Decision failed."); }
  }

  function togglePlacement(value: string) {
    setPlacements((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  }

  return <section className="mt-4 rounded-xl border border-blue-200 bg-blue-50/40 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-medium text-slate-950">Administrative review</h3><p className="mt-1 text-xs text-slate-600">Route the case, settle the exact terms, then sign the authority decision.</p></div>{assignment?.action === "assigned" ? <Badge tone="blue">Assigned to {assignment.reviewer?.displayName || assignment.reviewer?.email || "named reviewer"}</Badge> : <Badge tone="amber">Shared queue</Badge>}</div><div className="mt-3 grid gap-2 sm:grid-cols-[minmax(12rem,1fr)_minmax(16rem,2fr)_auto_auto]"><select aria-label={`Reviewer for ${permission.workKey}`} value={reviewerUserId} onChange={(event) => setReviewerUserId(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><option value="">Choose rights administrator</option>{decisionMembers.map((member) => <option key={member.userId} value={member.userId}>{member.displayName || member.email} · {humanize(member.role)}</option>)}</select><input aria-label={`Assignment reason for ${permission.workKey}`} value={assignmentReason} onChange={(event) => setAssignmentReason(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" placeholder="Assignment or queue-routing reason" /><button onClick={() => assignReviewer(false)} className="rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm font-medium">Assign</button><button disabled={assignment?.action !== "assigned"} onClick={() => assignReviewer(true)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium disabled:opacity-40">Clear</button></div>{assignment?.reason && <p className="mt-2 text-xs text-slate-600">Latest routing reason: {assignment.reason}</p>}{assignedElsewhere && <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">This case is assigned to {assignment?.reviewer?.displayName || assignment?.reviewer?.email}. Only that reviewer can decide it until the assignment is cleared.</p>}<label className="mt-4 block text-sm font-medium text-slate-700">Decision note<textarea aria-label={`Decision note for ${permission.workKey}`} value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} className="mt-1 min-h-24 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal" placeholder="State the approved scope, conditions, or rejection rationale." /></label><details open={exactAttributionRequired} className="mt-3 rounded-xl border border-slate-200 bg-white p-3"><summary className="cursor-pointer text-sm font-medium text-slate-900">Credit, backlink, metadata, and reporting terms</summary><p className="mt-2 text-xs text-slate-600">These exact obligations are embedded in the signed grant. They are enforceable terms only to the extent supported by the underlying agreement and applicable law.</p><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={attributionRequired} disabled={exactAttributionRequired} onChange={(event) => { setAttributionRequired(event.target.checked); if (event.target.checked) setReportingRequired(true); }} className="mt-1" />Attribution is required{exactAttributionRequired ? " by policy" : ""}</label><label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={backlinkRequired} onChange={(event) => setBacklinkRequired(event.target.checked)} className="mt-1" />Backlink is required</label><label className="text-sm sm:col-span-2">Exact credit text<input value={creditText} onChange={(event) => setCreditText(event.target.value)} required={attributionRequired} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="Written and performed by … · licensed through …" /></label><label className="text-sm sm:col-span-2">Exact backlink URL<input type="url" value={backlinkUrl} onChange={(event) => setBacklinkUrl(event.target.value)} required={backlinkRequired} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="https://rightsholder.example/work" /></label></div><fieldset className="mt-3"><legend className="text-sm font-medium">Required credit placements</legend><div className="mt-2 flex flex-wrap gap-3">{ATTRIBUTION_PLACEMENTS.map((placement) => <label key={placement} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={placements.includes(placement)} onChange={() => togglePlacement(placement)} />{humanize(placement)}</label>)}</div></fieldset><label className="mt-3 block text-sm">Required metadata fields · JSON object<textarea value={metadataFields} onChange={(event) => setMetadataFields(event.target.value)} className={`mt-1 min-h-20 w-full rounded-lg border px-3 py-2 font-mono text-xs ${metadataValid ? "border-slate-300" : "border-red-400"}`} placeholder={'{"artist_credit":"Artist Name","license_id":"…"}'} /></label><div className="mt-3 grid gap-3 sm:grid-cols-3"><label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={reportingRequired} disabled={attributionRequired} onChange={(event) => setReportingRequired(event.target.checked)} className="mt-1" />Publication evidence required</label><label className="text-sm">Due after publication · days<input type="number" min="1" max="3650" disabled={!reportingRequired} value={evidenceDueDays} onChange={(event) => setEvidenceDueDays(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 disabled:bg-slate-100" /></label><label className="text-sm">Reporting frequency<select disabled={!reportingRequired} value={reportingFrequency} onChange={(event) => setReportingFrequency(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 disabled:bg-slate-100"><option value="once">Once</option><option value="monthly">Monthly</option><option value="quarterly">Quarterly</option><option value="annual">Annual</option></select></label></div></details><div className="mt-3 flex flex-wrap gap-2"><button disabled={!approvalReady} onClick={() => decide("approved")} className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40">Approve and sign terms</button><button disabled={!decisionNote.trim() || assignedElsewhere} onClick={() => decide("rejected")} className="rounded-lg bg-red-700 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40">Reject</button></div>{message && <p className="mt-3 text-sm text-slate-700">{message}</p>}</section>;
}

function LicenseObligationsSummary({ permission }: { permission: Permission }) {
  if (!permission.receiptId) return null;
  const obligations = permission.licenseObligations;
  const attribution = obligations?.attribution;
  const reporting = obligations?.publicationReporting;
  const hasTerms = attribution?.required || attribution?.backlinkRequired || Object.keys(attribution?.metadataFields || {}).length > 0 || reporting?.required;
  return <section className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50/40 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium text-slate-950">Signed license obligations</h3><Badge tone="green">embedded in grant</Badge></div>{hasTerms ? <div className="mt-3 space-y-2 text-sm text-slate-700">{attribution?.required && <p><strong>Credit:</strong> {attribution.creditText} · {attribution.placements.map(humanize).join(", ")}</p>}{attribution?.backlinkRequired && <p><strong>Backlink:</strong> <a className="break-all text-blue-700 underline" href={attribution.backlinkUrl} target="_blank" rel="noreferrer">{attribution.backlinkUrl}</a></p>}{Object.keys(attribution?.metadataFields || {}).length > 0 && <p><strong>Metadata:</strong> {Object.entries(attribution.metadataFields).map(([key, value]) => `${key}=${value}`).join(" · ")}</p>}{reporting?.required && <p><strong>Publication reporting:</strong> {humanize(reporting.frequency)} · evidence due within {reporting.evidenceDueDaysAfterPublication} days of publication.</p>}</div> : <p className="mt-2 text-sm text-slate-600">The signed grant records no attribution, backlink, metadata, or publication-reporting obligation.</p>}</section>;
}

function UsageReportReview({ session, report, disabled, onChanged }: { session: SessionCredential; report: UsageReport; disabled: boolean; onChanged: () => Promise<void> }) {
  const [outcome, setOutcome] = React.useState("compliant");
  const [note, setNote] = React.useState("");
  const [evidenceReference, setEvidenceReference] = React.useState("");
  const [idempotencyKey, setIdempotencyKey] = React.useState(() => clientOperationKey(`compliance-review:${report.id}`));
  const [message, setMessage] = React.useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api(`/v1/permission-usage-reports/${report.id}/reviews`, session, {
        method: "POST",
        body: JSON.stringify({ outcome, note: note.trim(), evidence: evidenceReference.trim() ? { reference: evidenceReference.trim() } : {}, idempotency_key: idempotencyKey }),
      });
      setNote(""); setEvidenceReference(""); setIdempotencyKey(clientOperationKey(`compliance-review:${report.id}`));
      setMessage("Authority review appended. The grant status was not changed automatically.");
      await onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Compliance review failed."); }
  }
  return <form onSubmit={submit} className="mt-3 grid gap-2 rounded-lg border border-slate-200 bg-white p-3 sm:grid-cols-[10rem_1fr_1fr_auto]"><select value={outcome} onChange={(event) => setOutcome(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm"><option value="compliant">Compliant</option><option value="noncompliant">Noncompliant</option><option value="inconclusive">Inconclusive</option></select><input required value={note} onChange={(event) => setNote(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Review finding and rationale" /><input value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Evidence URL, digest, or record ID" /><button disabled={disabled || !note.trim()} className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Append review</button>{message && <p className="text-sm text-slate-700 sm:col-span-4">{message}</p>}</form>;
}

function Comparison({ label, value }: { label: string; value: boolean | null }) {
  return <span className="inline-flex items-center gap-1 text-xs text-slate-600">{label}<Badge tone={value === true ? "green" : value === false ? "red" : "blue"}>{value === true ? "exact" : value === false ? "mismatch" : "not required"}</Badge></span>;
}

function PermissionCompliance({ session, permission, onChanged }: { session: SessionCredential; permission: Permission; onChanged: () => Promise<void> }) {
  const obligations = permission.licenseObligations;
  const [publicationUrl, setPublicationUrl] = React.useState("");
  const [publishedAt, setPublishedAt] = React.useState(() => localDateTimeInputValue(new Date()));
  const [platform, setPlatform] = React.useState("");
  const [creditText, setCreditText] = React.useState(obligations?.attribution?.creditText || "");
  const [backlinkUrl, setBacklinkUrl] = React.useState(obligations?.attribution?.backlinkUrl || "");
  const [metadata, setMetadata] = React.useState(JSON.stringify(obligations?.attribution?.metadataFields || {}, null, 2));
  const [evidenceReference, setEvidenceReference] = React.useState("");
  const [idempotencyKey, setIdempotencyKey] = React.useState(() => clientOperationKey(`usage-report:${permission.id}`));
  const [message, setMessage] = React.useState("");
  const assignedElsewhere = permission.reviewAssignment?.action === "assigned" && permission.reviewAssignment.reviewer?.email?.toLowerCase() !== session.email.toLowerCase();
  let metadataValid = true;
  try { parseObject(metadata); } catch { metadataValid = false; }

  async function submitUsage(event: React.FormEvent) {
    event.preventDefault();
    try {
      const timestamp = new Date(publishedAt);
      if (Number.isNaN(timestamp.valueOf())) throw new Error("Enter a valid publication date and time.");
      await api(`/v1/permission-requests/${permission.id}/usage-reports`, session, {
        method: "POST",
        body: JSON.stringify({ publication_url: publicationUrl.trim(), published_at: timestamp.toISOString(), platform: platform.trim() || null, declared_credit_text: creditText.trim() || null, declared_backlink_url: backlinkUrl.trim() || null, metadata: parseObject(metadata), evidence: evidenceReference.trim() ? { reference: evidenceReference.trim() } : {}, idempotency_key: idempotencyKey }),
      });
      setPublicationUrl(""); setPlatform(""); setEvidenceReference(""); setIdempotencyKey(clientOperationKey(`usage-report:${permission.id}`));
      setMessage("Publication evidence appended for authority review.");
      await onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Publication report failed."); }
  }

  if (!permission.receiptId) return null;
  const outbound = permission.directions.includes("outbound");
  const inbound = permission.directions.includes("inbound");
  const reports = permission.usageReports || [];
  return <section className="mt-4 rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="font-medium text-slate-950">Publication and credit evidence</h3><p className="mt-1 text-xs text-slate-600">Requester reports and authority reviews are append-only assertions. A review never changes the signed grant automatically.</p></div>{obligations?.publicationReporting?.required && <Badge tone="amber">reporting required</Badge>}</div>{outbound && <details open={obligations?.publicationReporting?.required} className="mt-3 rounded-xl bg-slate-50 p-3"><summary className="cursor-pointer text-sm font-medium">Report a publication or licensed use</summary><form onSubmit={submitUsage} className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-sm sm:col-span-2">Publication URL<input required type="url" value={publicationUrl} onChange={(event) => setPublicationUrl(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="https://platform.example/release" /></label><label className="text-sm">Publication date and time<input required type="datetime-local" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="text-sm">Platform<input value={platform} onChange={(event) => setPlatform(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="YouTube, Spotify, campaign site…" /></label><label className="text-sm sm:col-span-2">Credit actually displayed<textarea value={creditText} onChange={(event) => setCreditText(event.target.value)} className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="text-sm sm:col-span-2">Backlink actually displayed<input type="url" value={backlinkUrl} onChange={(event) => setBacklinkUrl(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="text-sm">Metadata actually delivered · JSON<textarea value={metadata} onChange={(event) => setMetadata(event.target.value)} className={`mt-1 min-h-24 w-full rounded-lg border px-3 py-2 font-mono text-xs ${metadataValid ? "border-slate-300" : "border-red-400"}`} /></label><label className="text-sm">Evidence reference<textarea value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} className="mt-1 min-h-24 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="Screenshot digest, archive URL, platform report ID…" /></label><button disabled={!metadataValid} className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 sm:col-span-2">Append publication report</button></form></details>}<div className="mt-3 space-y-3">{reports.length === 0 && <p className="text-sm text-slate-500">No publication evidence has been reported.</p>}{reports.map((report) => <article key={report.id} className="rounded-xl bg-slate-50 p-3"><div className="flex flex-wrap items-start justify-between gap-2"><div><a href={report.publicationUrl} target="_blank" rel="noreferrer" className="break-all text-sm font-medium text-blue-700 underline">{report.publicationUrl}</a><p className="mt-1 text-xs text-slate-500">{report.platform || "Platform not stated"} · published {formatTimestamp(report.publishedAt)} · reported {formatTimestamp(report.createdAt)}</p></div><Badge tone={report.currentReviewOutcome === "compliant" ? "green" : report.currentReviewOutcome === "noncompliant" ? "red" : "amber"}>{humanize(report.currentReviewOutcome)}</Badge></div><div className="mt-2 flex flex-wrap gap-3"><Comparison label="Credit" value={report.automatedChecks.creditTextExactMatch} /><Comparison label="Backlink" value={report.automatedChecks.backlinkExactMatch} /><Comparison label="Reporting deadline" value={report.automatedChecks.reportedWithinDeadline} />{Object.entries(report.automatedChecks.metadataExactMatches).map(([key, value]) => <Comparison key={key} label={`Metadata ${key}`} value={value} />)}</div>{report.declaredCreditText && <p className="mt-2 text-sm text-slate-700"><strong>Reported credit:</strong> {report.declaredCreditText}</p>}{report.declaredBacklinkUrl && <p className="mt-1 break-all text-sm text-slate-700"><strong>Reported backlink:</strong> {report.declaredBacklinkUrl}</p>}{report.reviews.length > 0 && <div className="mt-3 space-y-2">{report.reviews.map((review) => <div key={review.id} className="rounded-lg border border-slate-200 bg-white p-2 text-sm"><Badge tone={review.outcome === "compliant" ? "green" : review.outcome === "noncompliant" ? "red" : "amber"}>{humanize(review.outcome)}</Badge><span className="ml-2">{review.note}</span><p className="mt-1 text-xs text-slate-500">Authority assertion · no automatic permission effect · {formatTimestamp(review.createdAt)}</p></div>)}</div>}{inbound && <UsageReportReview session={session} report={report} disabled={Boolean(assignedElsewhere)} onChanged={onChanged} />}</article>)}</div>{message && <p className="mt-3 text-sm text-slate-700">{message}</p>}</section>;
}


function Permissions({ session, organization }: { session: SessionCredential; organization: Organization }) {
  const [permissions, setPermissions] = React.useState<Permission[]>([]);
  const [members, setMembers] = React.useState<TeamMember[]>([]);
  const [lifecycleReasons, setLifecycleReasons] = React.useState<Record<string, string>>({});
  const [replacementReceiptIds, setReplacementReceiptIds] = React.useState<Record<string, string>>({});
  const [receiptInspections, setReceiptInspections] = React.useState<Record<string, ReceiptInspection>>({});
  const [message, setMessage] = React.useState("");
  const load = React.useCallback(async () => {
    const [permissionData, memberData] = await Promise.all([
      api<{ permissionRequests: Permission[] }>(`/v1/organizations/${organization.id}/permission-requests`, session),
      api<{ members: TeamMember[] }>(`/v1/organizations/${organization.id}/members`, session),
    ]);
    setPermissions(permissionData.permissionRequests);
    setMembers(memberData.members);
  }, [organization.id, session]);
  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);
  async function inspectReceipt(receiptId: string) {
    try {
      const receipt = await api<Record<string, any>>(`/v1/receipts/${receiptId}`, session);
      const verification = await api<ReceiptInspection["verification"]>("/v1/receipts/verify", undefined, { method: "POST", body: JSON.stringify({ receipt }) });
      setReceiptInspections((current) => ({ ...current, [receiptId]: { receipt, verification } }));
    } catch (error) { setMessage(error instanceof Error ? error.message : "Receipt verification failed."); }
  }
  async function downloadReceipt(receiptId: string) {
    try {
      await downloadPrivateReceipt(receiptId, session);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Receipt download failed."); }
  }
  async function recordLifecycle(permissionId: string, eventType: "dispute" | "revocation" | "correction") {
    const reason = (lifecycleReasons[permissionId] || "").trim();
    if (!reason) { setMessage("Record a concrete reason before changing a grant’s status."); return; }
    const replacementReceiptId = (replacementReceiptIds[permissionId] || "").trim();
    if (eventType === "correction" && !replacementReceiptId) { setMessage("A correction must identify the replacement grant receipt."); return; }
    try {
      await api(`/v1/permission-requests/${permissionId}/lifecycle-events`, session, {
        method: "POST",
        body: JSON.stringify({ event_type: eventType, reason, replacement_receipt_id: eventType === "correction" ? replacementReceiptId : null }),
      });
      setMessage(`${humanize(eventType)} recorded in a new signed transparency entry.`);
      setLifecycleReasons((current) => ({ ...current, [permissionId]: "" }));
      setReplacementReceiptIds((current) => ({ ...current, [permissionId]: "" }));
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Status update failed."); }
  }
  return <Panel title="Permission ledger" description="The requester and authority share the same record. Decisions and later status changes are immutable signed receipts, not edits to history."><div className="space-y-3">{permissions.length === 0 && <p className="text-sm text-slate-500">No permission request has been recorded.</p>}{permissions.map((permission) => {
    const reason = (lifecycleReasons[permission.id] || "").trim();
    const authorityCanChangeStatus = permission.directions.includes("inbound") && ["approved", "disputed"].includes(permission.status);
    const partyCanDispute = permission.status === "approved";
    const statusTone = permission.status === "approved" ? "green" : ["rejected", "revoked"].includes(permission.status) ? "red" : permission.status === "corrected" ? "blue" : "amber";
    return <article key={permission.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><strong>{permission.workTitle || permission.workKey}</strong><p className="text-sm text-slate-600">{humanize(permission.intendedUsage)} · {permission.territory} · {permission.workKey}</p></div><div className="flex gap-2">{permission.directions.map((direction) => <Badge key={direction} tone="blue">{direction}</Badge>)}<Badge tone={statusTone}>{permission.status}</Badge></div></div><p className="mt-3 text-xs text-slate-500">Requester: {permission.requester.organizationName} · Authority: {permission.authority.organizationName} ({permission.authority.rightType})</p><PermissionScope permission={permission} />{permission.decisionNote && <p className="mt-2 text-sm text-slate-700">{permission.decisionNote}</p>}{permission.status === "pending" && permission.directions.includes("inbound") && <AssignmentAndDecision session={session} permission={permission} members={members} onChanged={load} />}<div className="mt-3 flex flex-wrap gap-2">{permission.receiptId && <><button onClick={() => inspectReceipt(permission.receiptId!)} className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-900">Verify grant receipt</button><button onClick={() => downloadReceipt(permission.receiptId!)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium">Download grant JSON</button></>}</div>{permission.receiptId && receiptInspections[permission.receiptId] && <ReceiptVerification inspection={receiptInspections[permission.receiptId]} />}<LicenseObligationsSummary permission={permission} /><PermissionCompliance session={session} permission={permission} onChanged={load} /><SettlementLedger session={session} permission={permission} />{(permission.lifecycleRecords || []).length > 0 && <section className="mt-4 rounded-xl border border-slate-200 p-3"><h3 className="text-sm font-medium text-slate-900">Signed status history</h3><div className="mt-2 space-y-2">{permission.lifecycleRecords!.map((record) => <div key={record.receiptId} className="rounded-lg bg-slate-50 p-3 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div><Badge tone={record.status === "revoked" ? "red" : record.status === "corrected" ? "blue" : "amber"}>{record.status}</Badge><span className="ml-2">{record.reason}</span></div><button onClick={() => inspectReceipt(record.receiptId)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium">Verify {humanize(record.eventType)} receipt</button></div>{record.replacementReceiptId && <p className="mt-2 break-all text-xs text-slate-500">Replacement grant: {record.replacementReceiptId}</p>}{receiptInspections[record.receiptId] && <ReceiptVerification inspection={receiptInspections[record.receiptId]} />}</div>)}</div></section>}{(partyCanDispute || authorityCanChangeStatus) && <details className="mt-4 rounded-xl border border-amber-200 bg-amber-50/50 p-3"><summary className="cursor-pointer text-sm font-medium text-slate-900">Dispute, revoke, or correct this grant</summary><p className="mt-2 text-xs text-slate-600">The original receipt remains valid as historical evidence. This action creates a new signed record linked to it.</p><textarea aria-label={`Status change reason for ${permission.workKey}`} value={lifecycleReasons[permission.id] || ""} onChange={(event) => setLifecycleReasons((current) => ({ ...current, [permission.id]: event.target.value }))} className="mt-3 min-h-20 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" placeholder="State the concrete reason and relevant evidence." />{authorityCanChangeStatus && <input aria-label={`Replacement receipt for ${permission.workKey}`} value={replacementReceiptIds[permission.id] || ""} onChange={(event) => setReplacementReceiptIds((current) => ({ ...current, [permission.id]: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" placeholder="Replacement grant receipt ID · required only for correction" />}<div className="mt-3 flex flex-wrap gap-2">{partyCanDispute && <button disabled={!reason} onClick={() => recordLifecycle(permission.id, "dispute")} className="rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-medium disabled:opacity-40">Open dispute</button>}{authorityCanChangeStatus && <><button disabled={!reason} onClick={() => recordLifecycle(permission.id, "revocation")} className="rounded-lg bg-red-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Revoke grant</button><button disabled={!reason || !(replacementReceiptIds[permission.id] || "").trim()} onClick={() => recordLifecycle(permission.id, "correction")} className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Record correction</button></>}</div></details>}</article>;
  })}{message && <p className="text-sm text-slate-600">{message}</p>}</div></Panel>;
}

function Team({ session, organization }: { session: SessionCredential; organization: Organization }) {
  const [members, setMembers] = React.useState<TeamMember[]>([]);
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState("rights_manager");
  const [message, setMessage] = React.useState("");
  const canAdminister = organization.role === "owner" || organization.role === "admin";
  const load = React.useCallback(async () => {
    const response = await api<{ members: TeamMember[] }>(`/v1/organizations/${organization.id}/members`, session);
    setMembers(response.members);
  }, [organization.id, session]);
  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);
  async function addMember(event: React.FormEvent) {
    event.preventDefault();
    try {
      const result = await api<{ email: string; role: string; signInUrl: string }>(`/v1/organizations/${organization.id}/members`, session, { method: "POST", body: JSON.stringify({ email, role }) });
      setMessage(`${result.email} added as ${humanize(result.role)}. They can sign in at ${result.signInUrl}.`);
      setEmail("");
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not add team member."); }
  }
  return <div className="grid gap-6 lg:grid-cols-2"><Panel title="Organization team" description="Membership controls who can view the ledger, manage policies, or make rights decisions. It does not change node-operator status."><div className="space-y-3">{members.map((member) => <div key={member.userId} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 p-4"><div><strong>{member.displayName || member.email}</strong><p className="text-sm text-slate-600">{member.email}</p></div><Badge tone={member.role === "owner" || member.role === "admin" ? "blue" : "gray"}>{humanize(member.role)}</Badge></div>)}{members.length === 0 && <p className="text-sm text-slate-500">No organization memberships found.</p>}</div></Panel><Panel title="Add a colleague or client" description="Rights managers can publish policies and decide requests. Members can inspect records and submit outbound requests, but cannot make rights decisions.">{canAdminister ? <form onSubmit={addMember} className="space-y-3"><label className="block text-sm font-medium text-slate-800">Email address<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" placeholder="artist-or-colleague@example.com" /></label><label className="block text-sm font-medium text-slate-800">Organization role<select value={role} onChange={(event) => setRole(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2"><option value="rights_manager">Rights manager</option><option value="member">Member</option><option value="admin">Organization administrator</option></select></label><button className="rounded-xl bg-blue-700 px-5 py-2.5 font-medium text-white">Add team member</button></form> : <p className="text-sm text-slate-600">Only an organization owner or administrator can add members.</p>}{message && <p className="mt-3 text-sm text-slate-600">{message}</p>}</Panel></div>;
}

function AuditTrail({ session, path, refreshKey = 0, title = "Audit trail", description = "Successful state changes are retained as append-only records with the responsible human, machine credential, policy, or node process." }: { session: SessionCredential; path: string; refreshKey?: number; title?: string; description?: string }) {
  const [events, setEvents] = React.useState<AuditEvent[]>([]);
  const [message, setMessage] = React.useState("");
  const load = React.useCallback(async () => {
    const response = await api<{ events: AuditEvent[] }>(path, session);
    setEvents(response.events);
  }, [path, refreshKey, session]);
  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);
  return <Panel title={title} description={description}><div className="space-y-3">{events.length === 0 && <p className="text-sm text-slate-500">No auditable state change has been recorded.</p>}{events.map((event) => {
    const actor = event.actor.credentialName || event.actor.displayName || event.actor.email || humanize(event.actor.type);
    return <article key={event.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><strong>{humanize(event.action)}</strong><p className="mt-1 text-sm text-slate-600">{actor} · {humanize(event.actor.type)}</p></div><time className="text-xs text-slate-500">{formatTimestamp(event.createdAt)}</time></div><p className="mt-2 break-all text-xs text-slate-500">{humanize(event.resource.type)}{event.resource.id ? ` · ${event.resource.id}` : ""}{event.organization ? ` · ${event.organization.name}` : ""}</p>{Object.keys(event.details || {}).length > 0 && <details className="mt-2"><summary className="cursor-pointer text-xs font-medium text-slate-600">Recorded details</summary><pre className="mt-2 overflow-x-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">{JSON.stringify(event.details, null, 2)}</pre></details>}</article>;
  })}{message && <p className="text-sm text-red-700">{message}</p>}</div></Panel>;
}

function WebhookOperations({ session, organization, canAdminister, onAuditChange }: { session: SessionCredential; organization: Organization; canAdminister: boolean; onAuditChange: () => void }) {
  const [endpoints, setEndpoints] = React.useState<WebhookEndpoint[]>([]);
  const [deliveries, setDeliveries] = React.useState<WebhookDelivery[]>([]);
  const [availableEvents, setAvailableEvents] = React.useState<string[]>([]);
  const [url, setUrl] = React.useState("");
  const [events, setEvents] = React.useState<string[]>(["permission_request.created", "permission_request.approved", "settlement.reconciliation.recorded"]);
  const [issuedSecret, setIssuedSecret] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [deliveryUnavailable, setDeliveryUnavailable] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const load = React.useCallback(async () => {
    if (!canAdminister) return;
    const [endpointResponse, eventResponse, deliveryResponse] = await Promise.all([
      api<{ endpoints: WebhookEndpoint[] }>(`/v1/organizations/${organization.id}/webhooks`, session),
      api<{ events: string[] }>(`/v1/organizations/${organization.id}/webhooks/events`, session),
      api<{ deliveries: WebhookDelivery[] }>(`/v1/organizations/${organization.id}/webhook-deliveries?limit=100`, session),
    ]);
    setEndpoints(endpointResponse.endpoints); setAvailableEvents(eventResponse.events); setDeliveries(deliveryResponse.deliveries);
  }, [canAdminister, organization.id, session]);
  React.useEffect(() => void load().catch((error) => {
    if (error instanceof ApiError && error.status === 403) setDeliveryUnavailable(true);
    setMessage(error instanceof Error ? error.message : "Webhook delivery is unavailable.");
  }), [load]);
  function toggleEvent(event: string) {
    setEvents((current) => current.includes(event) ? current.filter((item) => item !== event) : [...current.filter((item) => item !== "*"), event]);
  }
  async function createEndpoint(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage(""); setIssuedSecret("");
    try {
      const result = await api<WebhookEndpoint & { signingSecret: string }>(`/v1/organizations/${organization.id}/webhooks`, session, { method: "POST", body: JSON.stringify({ url, events }) });
      setIssuedSecret(result.signingSecret); setUrl(""); setMessage("Endpoint created. Copy its signing secret before leaving this screen."); await load(); onAuditChange();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not create webhook endpoint."); }
    finally { setBusy(false); }
  }
  async function updateEndpoint(endpoint: WebhookEndpoint, enabled: boolean) {
    setBusy(true); setMessage("");
    try { await api(`/v1/organizations/${organization.id}/webhooks/${endpoint.id}`, session, { method: "PATCH", body: JSON.stringify({ enabled }) }); setMessage(enabled ? "Webhook endpoint enabled." : "Webhook endpoint disabled; queued deliveries will not be sent."); await load(); onAuditChange(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not update webhook endpoint."); }
    finally { setBusy(false); }
  }
  async function rotateSecret(endpoint: WebhookEndpoint) {
    setBusy(true); setMessage(""); setIssuedSecret("");
    try { const result = await api<WebhookEndpoint & { signingSecret: string }>(`/v1/organizations/${organization.id}/webhooks/${endpoint.id}/rotate-secret`, session, { method: "POST" }); setIssuedSecret(result.signingSecret); setMessage("Signing secret rotated. Update the receiver before another delivery attempt."); await load(); onAuditChange(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not rotate the webhook secret."); }
    finally { setBusy(false); }
  }
  async function testEndpoint(endpoint: WebhookEndpoint) {
    setBusy(true); setMessage("");
    try { await api(`/v1/organizations/${organization.id}/webhooks/${endpoint.id}/test`, session, { method: "POST" }); setMessage("Test delivery queued. The worker will send it asynchronously; refresh shortly to inspect the attempt."); await load(); onAuditChange(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not queue the test delivery."); }
    finally { setBusy(false); }
  }
  async function retryDelivery(delivery: WebhookDelivery) {
    setBusy(true); setMessage("");
    try { await api(`/v1/organizations/${organization.id}/webhook-deliveries/${delivery.id}/retry`, session, { method: "POST" }); setMessage("Delivery queued for one manual retry; prior attempts remain intact."); await load(); onAuditChange(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not retry the delivery."); }
    finally { setBusy(false); }
  }
  if (deliveryUnavailable) return <Panel title="Outbound webhooks disabled" description="This synthetic public sandbox cannot send events to partner systems."><p className="text-sm text-slate-600">Deploy an adopter-owned node to configure signed delivery endpoints. The sandbox keeps its records local to this evaluation environment.</p></Panel>;
  if (!canAdminister) return <Panel title="Outbound webhooks" description="Durable webhooks notify label systems after committed rights events."><p className="text-sm text-slate-600">Only an organization owner or administrator can view endpoint URLs, signing configuration, and delivery attempts.</p></Panel>;
  return <div className="space-y-6"><div className="grid gap-6 xl:grid-cols-2"><Panel title="Outbound webhooks" description="The business transaction and delivery outbox commit together. A separate worker signs each request, retries transient failures, and preserves every attempt."><form onSubmit={createEndpoint} className="space-y-4"><label className="block text-sm font-medium text-slate-800">HTTPS receiver URL<input type="url" required value={url} onChange={(event) => setUrl(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" placeholder="https://rights.example.com/webhooks/clef" /></label><fieldset><legend className="text-sm font-medium text-slate-800">Subscribed events</legend><div className="mt-2 flex items-center gap-2 rounded-lg border border-slate-200 p-3 text-sm"><input type="checkbox" checked={events.length === 1 && events[0] === "*"} onChange={(event) => setEvents(event.target.checked ? ["*"] : [])} />All supported events</div><details className="mt-2 rounded-lg border border-slate-200 p-3"><summary className="cursor-pointer text-sm font-medium">Choose individual events · {events[0] === "*" ? "all" : events.length} selected</summary><div className="mt-3 grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2">{availableEvents.map((item) => <label key={item} className="flex items-start gap-2 text-xs"><input type="checkbox" checked={events.includes(item)} onChange={() => toggleEvent(item)} />{item}</label>)}</div></details></fieldset><button disabled={busy || events.length === 0} className="rounded-xl bg-blue-700 px-5 py-2.5 font-medium text-white disabled:opacity-40">Create endpoint</button>{issuedSecret && <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4"><strong className="text-sm text-amber-950">Copy the signing secret now</strong><p className="mt-1 text-xs text-amber-900">Clef stores only AES-GCM ciphertext and a four-character hint. The plaintext will not appear again.</p><textarea readOnly value={issuedSecret} aria-label="Webhook signing secret" className="mt-3 min-h-20 w-full rounded-lg border border-amber-300 bg-white p-3 font-mono text-xs" /><button type="button" onClick={() => navigator.clipboard?.writeText(issuedSecret)} className="mt-2 rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-medium">Copy secret</button></div>}</form></Panel><Panel title="Configured endpoints" description="Redirects and private, local, or reserved network targets fail closed. Secret rotation takes effect on the next attempt."><div className="space-y-3">{endpoints.length === 0 && <p className="text-sm text-slate-500">No webhook endpoint has been configured.</p>}{endpoints.map((endpoint) => <article key={endpoint.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><strong className="break-all">{endpoint.url}</strong><p className="mt-1 text-xs text-slate-500">Secret ending {endpoint.secretHint} · {endpoint.events.length === 1 && endpoint.events[0] === "*" ? "all events" : `${endpoint.events.length} events`}</p></div><Badge tone={endpoint.enabled ? "green" : "red"}>{endpoint.enabled ? "enabled" : "disabled"}</Badge></div><div className="mt-3 flex flex-wrap gap-2"><button disabled={busy || !endpoint.enabled} onClick={() => void testEndpoint(endpoint)} className="rounded-lg border border-blue-300 px-3 py-2 text-sm font-medium text-blue-800 disabled:opacity-40">Queue test</button><button disabled={busy} onClick={() => void rotateSecret(endpoint)} className="rounded-lg border border-amber-300 px-3 py-2 text-sm font-medium text-amber-900 disabled:opacity-40">Rotate secret</button><button disabled={busy} onClick={() => void updateEndpoint(endpoint, !endpoint.enabled)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium disabled:opacity-40">{endpoint.enabled ? "Disable" : "Enable"}</button></div></article>)}</div></Panel></div><Panel title="Delivery outbox" description="Successful, retrying, and dead-lettered deliveries remain inspectable. Manual retry appends another attempt; it never erases the failure history."><div className="mb-3 flex justify-end"><button onClick={() => void load()} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium">Refresh deliveries</button></div><div className="space-y-3">{deliveries.length === 0 && <p className="text-sm text-slate-500">No webhook delivery has been queued.</p>}{deliveries.map((delivery) => <article key={delivery.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><strong>{delivery.event || "Unknown event"}</strong><p className="mt-1 font-mono text-xs text-slate-500">{delivery.id}</p></div><Badge tone={delivery.status === "succeeded" ? "green" : delivery.status === "dead_letter" ? "red" : "amber"}>{humanize(delivery.status)}</Badge></div><p className="mt-3 text-sm text-slate-600">{delivery.attemptCount} attempt{delivery.attemptCount === 1 ? "" : "s"} · last HTTP {delivery.lastStatusCode ?? "none"} · next {formatTimestamp(delivery.nextAttemptAt)}</p>{delivery.lastError && <p className="mt-2 text-sm text-red-700">{delivery.lastError}</p>}<details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-slate-600">Attempt history</summary><div className="mt-2 space-y-2">{delivery.attempts.length === 0 && <p className="text-xs text-slate-500">Waiting for the worker.</p>}{delivery.attempts.map((attempt) => <div key={attempt.id} className="rounded-lg bg-slate-50 p-3 text-xs"><strong>Attempt {attempt.attemptNumber} · {humanize(attempt.outcome)}</strong><p className="mt-1 text-slate-500">HTTP {attempt.statusCode ?? "none"} · {attempt.durationMs} ms · {formatTimestamp(attempt.createdAt)}</p>{attempt.error && <p className="mt-1 text-red-700">{attempt.error}</p>}</div>)}</div></details>{["retry", "dead_letter"].includes(delivery.status) && <button disabled={busy} onClick={() => void retryDelivery(delivery)} className="mt-3 rounded-lg border border-amber-300 px-3 py-2 text-sm font-medium text-amber-900 disabled:opacity-40">Queue manual retry</button>}</article>)}</div></Panel>{message && <p role="status" className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">{message}</p>}</div>;
}

function Operations({ session, organization }: { session: SessionCredential; organization: Organization }) {
  const canAdminister = organization.role === "owner" || organization.role === "admin";
  const [credentials, setCredentials] = React.useState<ApiCredential[]>([]);
  const [name, setName] = React.useState("Catalog and licensing automation");
  const [scopes, setScopes] = React.useState<string[]>(["directory:read", "rights:read", "permissions:read"]);
  const [expiresInDays, setExpiresInDays] = React.useState(90);
  const [issuedToken, setIssuedToken] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [auditRefreshKey, setAuditRefreshKey] = React.useState(0);
  const loadCredentials = React.useCallback(async () => {
    if (!canAdminister) return;
    const response = await api<{ credentials: ApiCredential[] }>(`/v1/organizations/${organization.id}/api-credentials`, session);
    setCredentials(response.credentials);
  }, [canAdminister, organization.id, session]);
  React.useEffect(() => void loadCredentials().catch((error) => setMessage(error.message)), [loadCredentials]);
  function toggleScope(scope: string) {
    setScopes((current) => current.includes(scope) ? current.filter((value) => value !== scope) : [...current, scope]);
  }
  async function createCredential(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      const result = await api<ApiCredential & { token: string }>(`/v1/organizations/${organization.id}/api-credentials`, session, {
        method: "POST",
        body: JSON.stringify({ name, scopes, expires_in_days: expiresInDays }),
      });
      setIssuedToken(result.token);
      setMessage("Credential created. Its secret is shown once below; the node retained only its hash.");
      await loadCredentials();
      setAuditRefreshKey((current) => current + 1);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not create API credential."); }
  }
  async function revokeCredential(credentialId: string) {
    try {
      await api(`/v1/organizations/${organization.id}/api-credentials/${credentialId}`, session, { method: "DELETE" });
      setMessage("Credential revoked. Requests using its bearer secret now fail immediately.");
      await loadCredentials();
      setAuditRefreshKey((current) => current + 1);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not revoke API credential."); }
  }
  return <div className="space-y-6"><div className="grid gap-6 lg:grid-cols-2"><Panel title="Machine credentials" description="Each secret belongs to this organization and can perform only its selected scopes. A credential never expands the organization's authority."><div className="space-y-3">{!canAdminister && <p className="text-sm text-slate-600">Only an organization owner or administrator can create and revoke machine credentials.</p>}{canAdminister && credentials.length === 0 && <p className="text-sm text-slate-500">No API credential has been issued.</p>}{canAdminister && credentials.map((credential) => <article key={credential.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><strong>{credential.name}</strong><p className="mt-1 font-mono text-xs text-slate-500">{credential.tokenPrefix}…</p></div><Badge tone={credential.status === "active" ? "green" : credential.status === "expired" ? "amber" : "red"}>{credential.status}</Badge></div><p className="mt-3 text-xs text-slate-600">Expires {formatTimestamp(credential.expiresAt)} · Last used {formatTimestamp(credential.lastUsedAt)}</p><div className="mt-3 flex flex-wrap gap-1">{credential.scopes.map((scope) => <Badge key={scope}>{humanize(scope.replace(":", " "))}</Badge>)}</div>{credential.status === "active" && <button onClick={() => revokeCredential(credential.id)} className="mt-3 rounded-lg border border-red-300 px-3 py-2 text-sm font-medium text-red-800">Revoke credential</button>}</article>)}</div></Panel><Panel title="Issue a credential" description="Use separate credentials for separate systems. Start read-only, add mutation scopes only when an integration needs them, then rotate before expiry.">{canAdminister ? <form onSubmit={createCredential} className="space-y-4"><label className="block text-sm font-medium text-slate-800">Credential name<input required value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" /></label><fieldset><legend className="text-sm font-medium text-slate-800">Allowed scopes</legend><div className="mt-2 grid gap-2 sm:grid-cols-2">{API_CREDENTIAL_SCOPES.map((scope) => <label key={scope} className="flex items-start gap-2 rounded-lg border border-slate-200 p-3 text-sm"><input type="checkbox" checked={scopes.includes(scope)} onChange={() => toggleScope(scope)} className="mt-0.5" /><span>{humanize(scope.replace(":", " "))}</span></label>)}</div></fieldset><label className="block text-sm font-medium text-slate-800">Expires in days<input type="number" min={1} max={365} value={expiresInDays} onChange={(event) => setExpiresInDays(Number(event.target.value))} className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2" /></label><button disabled={scopes.length === 0} className="rounded-xl bg-blue-700 px-5 py-2.5 font-medium text-white disabled:opacity-40">Issue one-time secret</button>{issuedToken && <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4"><strong className="text-sm text-amber-950">Copy this secret now</strong><p className="mt-1 text-xs text-amber-900">It will not appear in this console again.</p><textarea readOnly aria-label="New API credential secret" value={issuedToken} className="mt-3 min-h-20 w-full rounded-lg border border-amber-300 bg-white p-3 font-mono text-xs" /><button type="button" onClick={() => navigator.clipboard?.writeText(issuedToken)} className="mt-2 rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-medium">Copy secret</button></div>}{message && <p className="text-sm text-slate-600">{message}</p>}</form> : <p className="text-sm text-slate-600">Ask an organization owner or administrator to issue a narrowly scoped credential.</p>}</Panel></div><WebhookOperations session={session} organization={organization} canAdminister={canAdminister} onAuditChange={() => setAuditRefreshKey((current) => current + 1)} /><AuditTrail session={session} path={`/v1/organizations/${organization.id}/audit-events?limit=200`} refreshKey={auditRefreshKey} /></div>;
}

function OperatorAudit({ session }: { session: SessionCredential }) {
  return <AuditTrail session={session} path="/v1/operator/audit-events?limit=200" title="Node-wide audit trail" description="Operator actions and organization state changes appear here with their durable actor identities. Secrets and session identifiers are never included." />;
}

function OperatorReview({ session }: { session: SessionCredential }) {
  const [claims, setClaims] = React.useState<OperatorClaim[]>([]);
  const [conflicts, setConflicts] = React.useState<AuthorityConflict[]>([]);
  const [reviewNotes, setReviewNotes] = React.useState<Record<string, string>>({});
  const [resolutionNotes, setResolutionNotes] = React.useState<Record<string, string>>({});
  const [message, setMessage] = React.useState("");
  const load = React.useCallback(async () => {
    const [claimResponse, conflictResponse] = await Promise.all([
      api<{ claims: OperatorClaim[] }>("/v1/operator/authority-claims?status=self_asserted", session),
      api<{ conflicts: AuthorityConflict[] }>("/v1/operator/authority-conflicts?status=open", session),
    ]);
    setClaims(claimResponse.claims);
    setConflicts(conflictResponse.conflicts);
  }, [session]);
  React.useEffect(() => void load().catch((error) => setMessage(error.message)), [load]);
  async function review(claimId: string, decision: "verify" | "reject") {
    const note = (reviewNotes[claimId] || "").trim();
    if (!note) { setMessage("Record the evidence review and rationale before deciding."); return; }
    try {
      const result = await api<{ status: string }>(`/v1/authority-claims/${claimId}/${decision}`, session, { method: "POST", body: JSON.stringify({ evidence_note: note }) });
      setMessage(result.status === "disputed" ? "Overlapping authority detected. Resolve the conflict before either claim can receive new requests." : `Authority claim ${decision === "verify" ? "verified" : "rejected"}.`);
      setReviewNotes((current) => ({ ...current, [claimId]: "" }));
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Review failed."); }
  }
  async function resolve(conflictId: string, resolution: "claim_a" | "claim_b" | "compatible" | "neither") {
    const note = (resolutionNotes[conflictId] || "").trim();
    if (!note) { setMessage("Record the evidence and rationale before resolving a conflict."); return; }
    try {
      await api(`/v1/operator/authority-conflicts/${conflictId}/resolve`, session, { method: "POST", body: JSON.stringify({ resolution, note }) });
      setMessage("Authority conflict resolved with an auditable operator note.");
      setResolutionNotes((current) => ({ ...current, [conflictId]: "" }));
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Conflict resolution failed."); }
  }
  return <div className="space-y-6">
    <Panel title="Operator authority review" description="Compare the submitted evidence with the claimed right, territory, and share. Verification records the review; it does not create ownership.">
      <div className="space-y-3">
        {claims.length === 0 && <p className="text-sm text-slate-500">No self-asserted claim is waiting for review.</p>}
        {claims.map((claim) => <article key={claim.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap justify-between gap-2"><div><strong>{claim.workKey}</strong><p className="text-sm text-slate-600">{claim.organization?.name} · {claim.artistName || "Unknown artist"}</p></div><Badge tone="amber">{claim.status}</Badge></div><dl className="mt-3 grid gap-2 rounded-lg bg-slate-50 p-3 text-sm sm:grid-cols-3"><div><dt className="text-slate-500">Right</dt><dd>{humanize(claim.rightType)}</dd></div><div><dt className="text-slate-500">Territory</dt><dd>{claim.territory}</dd></div><div><dt className="text-slate-500">Evidence</dt><dd className="break-all">{JSON.stringify(claim.evidence)}</dd></div></dl><label className="mt-3 block text-sm font-medium text-slate-700">Evidence review note<textarea aria-label={`Evidence review note for ${claim.workKey}`} value={reviewNotes[claim.id] || ""} onChange={(event) => setReviewNotes((current) => ({ ...current, [claim.id]: event.target.value }))} className="mt-1 min-h-24 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" placeholder="Record what evidence was checked and why it supports or fails the claim." /></label><div className="mt-3 flex gap-2"><button disabled={!(reviewNotes[claim.id] || "").trim()} onClick={() => review(claim.id, "verify")} className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40">Mark evidence verified</button><button disabled={!(reviewNotes[claim.id] || "").trim()} onClick={() => review(claim.id, "reject")} className="rounded-lg bg-red-700 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40">Reject authority claim</button></div></article>)}
      </div>
    </Panel>
    <Panel title="Authority conflicts" description="Overlapping territories are not automatically conflicts. This queue opens only when exclusive claims, missing shares, or combined controlled shares above 100% collide during operator verification.">
      <div className="space-y-3">
        {conflicts.length === 0 && <p className="text-sm text-slate-500">No authority conflict is waiting for resolution.</p>}
        {conflicts.map((conflict) => {
          const note = (resolutionNotes[conflict.id] || "").trim();
          return <article key={conflict.id} className="rounded-xl border border-amber-300 bg-amber-50/40 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><strong>{conflict.workKey}</strong><p className="text-sm text-slate-600">{humanize(conflict.rightType)} · {humanize(conflict.basis.reason || "overlap")}</p></div><Badge tone="amber">open conflict</Badge></div><div className="mt-3 grid gap-3 md:grid-cols-2">{([ ["A", conflict.claimA], ["B", conflict.claimB] ] as const).map(([label, side]) => <section key={label} className="rounded-lg border border-slate-200 bg-white p-3 text-sm"><strong>Claim {label} · {side.organization?.name || "Unknown organization"}</strong><p className="mt-1 text-slate-600">{side.territory} · prior status {humanize(side.priorStatus)}</p><p className="mt-2 break-all text-xs text-slate-500">{JSON.stringify(side.evidence)}</p></section>)}</div><p className="mt-3 text-xs text-slate-600">Combined controlled share: {conflict.basis.combinedShare ?? "unknown"}%</p><textarea aria-label={`Conflict resolution note for ${conflict.workKey}`} value={resolutionNotes[conflict.id] || ""} onChange={(event) => setResolutionNotes((current) => ({ ...current, [conflict.id]: event.target.value }))} className="mt-3 min-h-24 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" placeholder="Record the evidence reviewed and why the claims are compatible, preferred, or rejected." /><div className="mt-3 flex flex-wrap gap-2"><button disabled={!note} onClick={() => resolve(conflict.id, "claim_a")} className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Keep claim A</button><button disabled={!note} onClick={() => resolve(conflict.id, "claim_b")} className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Keep claim B</button><button disabled={!note} onClick={() => resolve(conflict.id, "compatible")} className="rounded-lg border border-emerald-400 bg-white px-3 py-2 text-sm font-medium text-emerald-900 disabled:opacity-40">Mark compatible split</button><button disabled={!note} onClick={() => resolve(conflict.id, "neither")} className="rounded-lg border border-red-400 bg-white px-3 py-2 text-sm font-medium text-red-800 disabled:opacity-40">Reject both</button></div></article>;
        })}
      </div>
    </Panel>
    {message && <p className="text-sm text-slate-700">{message}</p>}
  </div>;
}

function OperatorOnlyConsole({ context, session, onSignOut, nodeInfo }: { context: SessionContext; session: SessionCredential; onSignOut: () => void; nodeInfo: NodeInfo | null }) {
  return <div className="min-h-screen bg-slate-50"><DeploymentBanner nodeInfo={nodeInfo} /><header className="border-b border-slate-200 bg-white"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4"><div><div className="text-xl font-semibold text-slate-950">Clef Rights Node</div><div className="text-xs text-slate-500">Node operations · evidence verification</div></div><div className="flex items-center gap-3"><span className="text-sm text-slate-600">{context.user.email}</span><button onClick={onSignOut} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">Sign out</button></div></div></header><main className="mx-auto max-w-7xl space-y-6 px-6 py-8"><div className="mb-6"><Badge tone="blue">Node operator</Badge><p className="mt-2 max-w-2xl text-sm text-slate-600">Review evidence independently. An operator account does not need to create or join a rights-holding organization.</p></div><DeploymentReadinessPanel apiBase={API_BASE} sessionId={session.id} sourceCodeUrl={nodeInfo?.sourceCodeUrl} /><OperatorReview session={session} /><OperatorAudit session={session} /></main><LegalNotice nodeInfo={nodeInfo}>Verification records the evidence review performed by this node. It does not create ownership, expand a claimant&apos;s rights, or provide legal advice.</LegalNotice></div>;
}

export function RightsNodeApp() {
  const [credential, setCredential] = React.useState<SessionCredential | null>(() => readSession());
  const credentialRef = React.useRef(credential?.id);
  credentialRef.current = credential?.id;
  const navigationGeneration = React.useRef(0);
  const [showConsole, setShowConsole] = React.useState(false);
  const [showSetup, setShowSetup] = React.useState(false);
  const [nodeInfo, setNodeInfo] = React.useState<NodeInfo | null>(null);
  const [context, setContext] = React.useState<SessionContext | null>(null);
  const [loading, setLoading] = React.useState(Boolean(credential));
  const [error, setError] = React.useState("");
  const [tab, setTab] = React.useState<"catalog" | "policies" | "authority" | "request" | "permissions" | "team" | "operations" | "operator" | "connected">("catalog");
  const [activeOrgId, setActiveOrgId] = React.useState(() => safeStorageGet("session", ORG_KEY) || "");

  React.useEffect(() => {
    let cancelled = false;
    void api<NodeInfo>("/v1/node/info")
      .then((data) => { if (!cancelled) setNodeInfo(data); })
      .catch(() => { if (!cancelled) setNodeInfo(null); });
    return () => { cancelled = true; };
  }, []);

  const refresh = React.useCallback(async () => {
    if (!credential) return;
    setLoading(true);
    try {
      const data = await api<SessionContext>("/v1/session", credential);
      if (credentialRef.current !== credential.id) return;
      setContext(data);
      setError("");
      if (!data.organizations.some((organization) => organization.id === activeOrgId)) {
        const next = data.organizations[0]?.id || "";
        setActiveOrgId(next);
        if (next) safeStorageSet("session", ORG_KEY, next);
      }
    } catch (caught) {
      if (credentialRef.current !== credential.id) return;
      if (caught instanceof ApiError && caught.status === 401) {
        safeStorageRemove("session", SESSION_KEY); setCredential(null); setContext(null);
      } else setError(caught instanceof Error ? caught.message : "Could not load session.");
    } finally { if (credentialRef.current === credential.id) setLoading(false); }
  }, [activeOrgId, credential]);
  React.useEffect(() => void refresh(), [refresh]);

  const authenticate = React.useCallback((session: SessionCredential) => {
    navigationGeneration.current++;
    credentialRef.current = session.id; setContext(null); setCredential(session); setLoading(true);
    setShowConsole(false); setShowSetup(false); setError("");
  }, []);
  async function signOut() {
    const previous = credential;
    navigationGeneration.current++;
    credentialRef.current = undefined;
    safeStorageRemove("session", SESSION_KEY); safeStorageRemove("session", ORG_KEY);
    setCredential(null); setContext(null); setActiveOrgId(""); setShowConsole(false); setShowSetup(false);
    if (previous) await api("/auth/session", previous, { method: "DELETE" }).catch(() => undefined);
  }
  async function restartTour() {
    const response = await api<{ session: SessionCredential }>("/v1/sandbox/session", undefined, { method: "POST" });
    const previous = credential;
    safeStorageSet("session", SESSION_KEY, JSON.stringify(response.session));
    safeStorageRemove("session", ORG_KEY); setActiveOrgId(""); authenticate(response.session);
    if (previous) await api("/auth/session", previous, { method: "DELETE" }).catch(() => undefined);
  }
  async function openConsole(orgId: string, destination: "catalog" | "policies" | "permissions" | "connected") {
    if (!credential) return;
    const generation = ++navigationGeneration.current;
    try {
      const data = await api<SessionContext>("/v1/session", credential);
      if (credentialRef.current !== credential.id || generation !== navigationGeneration.current) return;
      setContext(data); setActiveOrgId(orgId); safeStorageSet("session", ORG_KEY, orgId);
      setTab(destination); setShowConsole(true); setShowSetup(false);
    } catch (caught) {
      if (credentialRef.current === credential.id && generation === navigationGeneration.current)
        setError(caught instanceof Error ? caught.message : "Could not open the console.");
    }
  }
  if (!credential) return <SignIn onAuthenticated={authenticate} nodeInfo={nodeInfo} />;
  if (loading && !context) return <div className="grid min-h-screen place-items-center text-slate-600">Loading secure session…</div>;
  if (!context) return <div className="mx-auto max-w-xl p-8 text-red-700">{error || "Session unavailable."}</div>;
  const tourAvailable = isPublicSandbox(nodeInfo) && Boolean(nodeInfo?.sandboxGuestAccess) && context.user.email.endsWith("@sandbox.invalid");
  if (tourAvailable && !showConsole && !showSetup) return <><SandboxTour key={credential.id} session={credential}
    federationEnabled={nodeInfo?.federationEnabled}
    onConsole={(orgId, destination) => void openConsole(orgId, destination)}
    onSetup={() => { navigationGeneration.current++; setError(""); setShowSetup(true); setShowConsole(true); }} onSignOut={signOut} onRestart={restartTour}
    onDownload={(receiptId) => downloadPrivateReceipt(receiptId, credential)} /><LegalNotice nodeInfo={nodeInfo} />{error && <p role="alert" className="p-4 text-red-700">{error}</p>}</>;
  if (showSetup || requiresOrganizationSetup(context)) return <div className="min-h-screen bg-slate-50"><DeploymentBanner nodeInfo={nodeInfo} />{tourAvailable && <button className="m-6 text-blue-700 underline" onClick={() => { setShowSetup(false); setShowConsole(false); }}>← Return to the example catalog</button>}<OrganizationSetup session={credential} onCreated={() => { setShowSetup(false); void refresh(); }} /><LegalNotice nodeInfo={nodeInfo} /></div>;
  if (context.organizations.length === 0) return <OperatorOnlyConsole context={context} session={credential} onSignOut={signOut} nodeInfo={nodeInfo} />;
  const active = context.organizations.find((organization) => organization.id === activeOrgId) || context.organizations[0];
  const canManageRights = canOrganizationManageRights(active);
  const canAdministerSetup = ORG_DECISION_ROLES.has(active.role);
  const canAdministerPrivacy = isPrivacyAdministrator(active.role);
  const tabs = [...(nodeInfo?.federationEnabled ? [{ id: "connected" as const, label: "Connected catalogs" }] : []), ...(canManageRights ? [{ id: "catalog" as const, label: "Catalog" }, { id: "policies" as const, label: "Policies" }, { id: "authority" as const, label: "Authority" }] : []), { id: "request" as const, label: "Request permission" }, { id: "permissions" as const, label: "Permission ledger" }, { id: "team" as const, label: "Team" }, { id: "operations" as const, label: "Operations" }, ...(context.user.nodeRole === "admin" ? [{ id: "operator" as const, label: "Operator review" }] : [])] as const;
  const visibleTab = !canManageRights && (tab === "catalog" || tab === "policies" || tab === "authority") ? "request" : tab;
  return <div className="min-h-screen bg-slate-50"><DeploymentBanner nodeInfo={nodeInfo} /><header className="border-b border-slate-200 bg-white"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4"><div><div className="text-xl font-semibold text-slate-950">Clef Rights Node</div><div className="text-xs text-slate-500">Your catalog, creator conditions and licensing decisions</div></div><div className="flex min-w-0 max-w-full flex-wrap items-center gap-3"><select aria-label="Active organization" value={active.id} onChange={(event) => { setActiveOrgId(event.target.value); safeStorageSet("session", ORG_KEY, event.target.value); }} className="min-w-0 max-w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">{context.organizations.map((organization) => <option key={organization.id} value={organization.id}>{organization.name} · {organization.role}</option>)}</select>{tourAvailable && <button onClick={() => setShowConsole(false)} className="rounded-lg border border-blue-300 px-3 py-2 text-sm text-blue-700">Return to walkthrough</button>}<span className="hidden text-sm text-slate-600 sm:inline">{context.user.email}</span><button onClick={signOut} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">Sign out</button></div></div></header><main key={organizationConsoleScopeKey(active.id)} className="mx-auto max-w-7xl px-6 py-8"><div className="mb-6 flex flex-wrap gap-2">{tabs.map((item) => <button key={item.id} onClick={() => setTab(item.id)} className={`rounded-xl px-4 py-2 text-sm font-medium ${visibleTab === item.id ? "bg-slate-950 text-white" : "bg-white text-slate-700 shadow-sm"}`}>{item.label}</button>)}</div>{error && <div className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</div>}{visibleTab === "connected" && nodeInfo?.federationEnabled && <ConnectedCatalogs key={`${credential.id}:${active.id}`} apiBase={API_BASE} sessionId={credential.id} organizationId={active.id} organizations={context.organizations} canPublish={canAdministerPrivacy && canManageRights && !isPublicSandbox(nodeInfo)} synthetic={isPublicSandbox(nodeInfo)} />}{visibleTab === "catalog" && <Catalog session={credential} organization={active} />}{visibleTab === "policies" && <Policies key={policyEditorScopeKey(active.id)} session={credential} organization={active} />}{visibleTab === "authority" && <Authority session={credential} organization={active} />}{visibleTab === "request" && <RequestPermission session={credential} organization={active} />}{visibleTab === "permissions" && <Permissions session={credential} organization={active} />}{visibleTab === "team" && <Team session={credential} organization={active} />}{visibleTab === "operations" && <div className="space-y-6">{canAdministerSetup && <OnboardingChecklist key={active.id} apiBase={API_BASE} sessionId={credential.id} organizationId={active.id} onNavigate={(action) => setTab(action as typeof tab)} />}{canAdministerPrivacy && <PrivacyPanel key={privacyScopeKey(active.id)} apiBase={API_BASE} sessionId={credential.id} organizationId={active.id} />}<Operations session={credential} organization={active} /></div>}{visibleTab === "operator" && <div className="space-y-6"><DeploymentReadinessPanel apiBase={API_BASE} sessionId={credential.id} sourceCodeUrl={nodeInfo?.sourceCodeUrl} /><OperatorReview session={credential} /><OperatorAudit session={credential} /></div>}</main><LegalNotice nodeInfo={nodeInfo}>Your organization supplies evidence of the rights it administers. Clef records its policies, reviewers’ decisions and agreed terms in verifiable receipts.</LegalNotice></div>;
}
