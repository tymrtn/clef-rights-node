import React from "react";
import { isEmail } from "./UserGate";
import { checkedJson } from "../utils/http";
import { safeStorageGet } from "../utils/storage";
import {
  USAGE_CATEGORIES,
  RESTRICTION_CATEGORIES,
  USAGE_KEYS,
  RESTRICTION_KEYS,
  UsageState,
  UsageCategory,
  RestrictionState,
} from "../types/rights";
import { RIGHTS_MACROS, RightsMacro } from "../types/macros";
import { MacroSelector } from "./MacroSelector";

interface RightsMatrix {
  usage: Record<string, UsageState>;
  restrictions: Record<string, RestrictionState>;
}

export const checkedCollaborationJson = checkedJson;

export function isCurrentValidation(requestId: number, currentRequestId: number): boolean {
  return requestId === currentRequestId;
}

type Props = {
  row: any;
  data: { contract: any; matrix: RightsMatrix; version: number } | null;
  onClose: () => void;
  onSave: (contract: any) => Promise<void>;
  loading: boolean;
};

export function RightsDrawer({ row, data, onClose, onSave, loading }: Props) {
  const [draft, setDraft] = React.useState<any | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [aiLoading, setAiLoading] = React.useState(false);
  const [aiReasoning, setAiReasoning] = React.useState("");
  const [issues, setIssues] = React.useState<any[]>([]);
  const [activeTab, setActiveTab] = React.useState<"edit" | "preview">("edit");
  const [approvals, setApprovals] = React.useState<any[]>([]);
  const [comments, setComments] = React.useState<any[]>([]);
  const [commentBody, setCommentBody] = React.useState("");
  const [history, setHistory] = React.useState<any[]>([]);
  const [diffSummary, setDiffSummary] = React.useState<string | null>(null);
  const validationRequestIdRef = React.useRef(0);

  const clone = React.useCallback(
    (value: any) => JSON.parse(JSON.stringify(value)),
    []
  );

  React.useEffect(() => {
    if (data?.contract) {
      setDraft(clone(data.contract));
    } else {
      setDraft(null);
    }
    setIssues([]);
  }, [data, clone]);

  // Guardrails: validate draft and surface conflicts (debounced).
  React.useEffect(() => {
    const requestId = ++validationRequestIdRef.current;
    if (!draft) {
      setIssues([]);
      return;
    }
    setIssues([]);
    const id = window.setTimeout(async () => {
      try {
        const res = await fetch("/api/rights/validate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: row.key, contract: draft }),
        });
        const data = await checkedJson(res, "Rights validation");
        if (isCurrentValidation(requestId, validationRequestIdRef.current)) {
          setIssues(data.issues || []);
        }
      } catch {
        // ignore
      }
    }, 250);
    return () => {
      window.clearTimeout(id);
      if (isCurrentValidation(requestId, validationRequestIdRef.current)) {
        validationRequestIdRef.current += 1;
      }
    };
  }, [draft, row.key]);

  const collabHeaders = React.useCallback((): HeadersInit => {
    const owner = safeStorageGet("local", "rc.ownerEmail")?.trim() || "";
    const user = safeStorageGet("local", "rc.userEmail")?.trim() || "";
    const headers: Record<string, string> = {};
    if (isEmail(owner)) headers["X-Owner-Email"] = owner;
    if (isEmail(user)) headers["X-User-Email"] = user;
    return headers;
  }, []);

  // Load approvals/comments/history for collaboration panel
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [a, c, h] = await Promise.all([
          fetch(`/api/approvals/list?key=${encodeURIComponent(row.key)}`, {
            headers: collabHeaders(),
          }).then((response) => checkedCollaborationJson(response, "Approval list")),
          fetch(`/api/comments/thread?key=${encodeURIComponent(row.key)}`, {
            headers: collabHeaders(),
          }).then((response) => checkedCollaborationJson(response, "Comment thread")),
          fetch(
            `/api/rights/history?key=${encodeURIComponent(row.key)}&limit=10`,
            {
              headers: collabHeaders(),
            }
          ).then((response) => checkedCollaborationJson(response, "Rights history")),
        ]);
        if (cancelled) return;
        setApprovals(a.items || []);
        setComments(c.items || []);
        setHistory(Array.isArray(h) ? h : []);
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [row.key, collabHeaders]);

  async function requestApproval() {
    try {
      const res = await fetch("/api/approvals/request", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...collabHeaders() },
        body: JSON.stringify({ key: row.key, due_in_days: 7 }),
      });
      await checkedCollaborationJson(res, "Approval request");
      const list = await fetch(
        `/api/approvals/list?key=${encodeURIComponent(row.key)}`,
        {
          headers: collabHeaders(),
        }
      ).then((response) => checkedCollaborationJson(response, "Approval list refresh"));
      setApprovals(list.items || []);
    } catch (e: any) {
      setError(e.message || "Approval request failed");
    }
  }

  async function decideApproval(
    approvalId: string,
    decision: "approved" | "rejected"
  ) {
    try {
      const res = await fetch("/api/approvals/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...collabHeaders() },
        body: JSON.stringify({ approval_id: approvalId, decision }),
      });
      await checkedCollaborationJson(res, "Approval decision");
      const list = await fetch(
        `/api/approvals/list?key=${encodeURIComponent(row.key)}`,
        { headers: collabHeaders() }
      ).then((response) => checkedCollaborationJson(response, "Approval list refresh"));
      setApprovals(list.items || []);
    } catch (e: any) {
      setError(e.message || "Approval decision failed");
    }
  }

  async function postComment() {
    const body = commentBody.trim();
    if (!body) return;
    const mentions = Array.from(
      body.matchAll(/@([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/g)
    ).map((m) => m[1]);
    try {
      const res = await fetch("/api/comments/create", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...collabHeaders() },
        body: JSON.stringify({ key: row.key, body, mentions }),
      });
      await checkedCollaborationJson(res, "Comment creation");
      const thread = await fetch(
        `/api/comments/thread?key=${encodeURIComponent(row.key)}`,
        {
          headers: collabHeaders(),
        }
      ).then((response) => checkedCollaborationJson(response, "Comment thread refresh"));
      setComments(thread.items || []);
      setCommentBody("");
    } catch (e: any) {
      setError(e.message || "Comment failed");
    }
  }

  async function computeDiffSinceLast() {
    try {
      if (!history.length || !data?.version) {
        setDiffSummary("No prior versions available.");
        return;
      }
      const prevVersion = history.find(
        (h) => h.version === data.version - 1
      )?.version;
      if (!prevVersion) {
        setDiffSummary("No prior version found for comparison.");
        return;
      }
      const prev = await fetch(
        `/api/rights/history/version?key=${encodeURIComponent(
          row.key
        )}&version=${prevVersion}`,
        { headers: collabHeaders() }
      ).then((response) => checkedCollaborationJson(response, "Rights history version"));
      const prevMatrix = prev.matrix || {};
      const curMatrix = data.matrix || {};
      const changes: string[] = [];
      const prevUsage = prevMatrix.usage || {};
      const curUsage = curMatrix.usage || {};
      const prevRestrictions = prevMatrix.restrictions || {};
      const curRestrictions = curMatrix.restrictions || {};

      let usageChanged = 0;
      Object.keys({ ...prevUsage, ...curUsage }).forEach((k) => {
        if ((prevUsage[k] || "blocked") !== (curUsage[k] || "blocked"))
          usageChanged += 1;
      });
      let restrictionChanged = 0;
      Object.keys({ ...prevRestrictions, ...curRestrictions }).forEach((k) => {
        if (
          (prevRestrictions[k] || "allowed") !==
          (curRestrictions[k] || "allowed")
        )
          restrictionChanged += 1;
      });
      if (usageChanged)
        changes.push(`${usageChanged} usage category change(s)`);
      if (restrictionChanged)
        changes.push(`${restrictionChanged} restriction change(s)`);

      const prevApproval =
        prev.contract?.artist?.approval?.approvalWindowDays ?? 0;
      const curApproval =
        data.contract?.artist?.approval?.approvalWindowDays ?? 0;
      if (prevApproval !== curApproval)
        changes.push(`approvalWindowDays ${prevApproval} → ${curApproval}`);

      setDiffSummary(
        changes.length
          ? changes.join(", ")
          : "No meaningful differences detected."
      );
    } catch {
      setDiffSummary("Diff unavailable.");
    }
  }

  if (!row || !draft) return null;

  function setUsageState(key: string, state: UsageState) {
    setDraft((prev: any) => {
      const next = clone(prev);
      next.artist = next.artist || {};
      next.artist.usageMatrix = next.artist.usageMatrix || {};
      next.artist.usageMatrix[key] = state;
      next.matrix = next.matrix || { usage: {}, restrictions: {} };
      next.matrix.usage[key] = state;
      return next;
    });
  }

  function setRestrictionState(key: string, state: RestrictionState) {
    setDraft((prev: any) => {
      const next = clone(prev);
      next.artist = next.artist || {};
      next.artist.restrictionMatrix = next.artist.restrictionMatrix || {};
      next.artist.restrictionMatrix[key] = state;
      next.matrix = next.matrix || { usage: {}, restrictions: {} };
      next.matrix.restrictions[key] = state;
      return next;
    });
  }

  function applyMacro(macro: RightsMacro) {
    setDraft((prev: any) => {
      const next = clone(prev);
      next.metadata = next.metadata || {};
      next.metadata.selectedMacroId = macro.id;
      next.metadata.selectedMacroName = macro.name;
      next.artist = next.artist || {};
      next.artist.usageMatrix = { ...macro.usageMatrix };
      next.artist.restrictionMatrix = { ...macro.restrictionMatrix };
      if (macro.approvalWindowDays !== undefined) {
        next.artist.approval = next.artist.approval || {};
        next.artist.approval.approvalWindowDays = macro.approvalWindowDays;
      }
      next.matrix = next.matrix || { usage: {}, restrictions: {} };
      next.matrix.usage = { ...macro.usageMatrix };
      next.matrix.restrictions = { ...macro.restrictionMatrix };
      return next;
    });
  }

  async function handleAIRecommend() {
    setAiLoading(true);
    setAiReasoning("");
    try {
      // Use artist from MLC raw data (performer field) as canonical source
      const artist = row.raw?.artist || row.artist || "Unknown Artist";
      const response = await fetch("/api/rights/recommend-macro", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          artist: artist,
          genres: row.genres || [],
          career_stage: row.careerStage || "emerging",
        }),
      });
      if (!response.ok) throw new Error("AI recommendation failed");
      const { macroId, reasoning } = await response.json();
      const macro = RIGHTS_MACROS.find((m) => m.id === macroId);
      if (macro) {
        applyMacro(macro);
        setAiReasoning(reasoning || "");
      }
    } catch (err: any) {
      setError(err.message || "AI recommendation failed");
    } finally {
      setAiLoading(false);
    }
  }

  async function handleSave() {
    if (!draft || loading) return;
    setSaving(true);
    setError("");
    try {
      await onSave(draft);
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <aside
      id="rc-rights-drawer"
      className="fixed top-0 right-0 w-full max-w-xl h-full bg-white shadow-2xl z-30 overflow-y-auto"
    >
      <div className="p-6 space-y-6">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Rights editor
            </h2>
            <p className="text-sm text-gray-500">{row.title}</p>
            <p className="text-xs text-gray-400">
              Version {data?.version ?? 0}
            </p>
          </div>
          <button
            className="text-sm text-gray-500 hover:text-gray-700"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        {loading && <div className="text-sm text-gray-500">Loading…</div>}

        {issues.length > 0 && (
          <section
            id="rc-conflict-detector"
            className="border border-amber-200 bg-amber-50 rounded-lg p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-amber-900">
                  Potential conflicts detected
                </h3>
                <p className="text-xs text-amber-800 mt-1">
                  These are guardrails (warnings/info), not blockers.
                </p>
              </div>
              <span className="text-xs bg-amber-100 text-amber-800 px-2 py-1 rounded">
                {issues.length} issue{issues.length === 1 ? "" : "s"}
              </span>
            </div>
            <ul className="mt-3 space-y-2">
              {issues.slice(0, 5).map((i, idx) => (
                <li key={idx} className="text-xs text-amber-900">
                  <span className="font-medium">{i.code}</span>: {i.message}
                  {i.fixIt && (
                    <div className="text-[11px] text-amber-800 mt-0.5">
                      Fix: {i.fixIt}
                    </div>
                  )}
                </li>
              ))}
              {issues.length > 5 && (
                <li className="text-[11px] text-amber-800">
                  + {issues.length - 5} more…
                </li>
              )}
            </ul>
          </section>
        )}

        <div
          className="flex gap-2"
          role="tablist"
          aria-label="Rights editor views"
        >
          <button
            type="button"
            id="rc-tab-edit"
            role="tab"
            aria-selected={activeTab === "edit"}
            className={`px-3 py-2 rounded-lg text-sm font-medium ${
              activeTab === "edit"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
            onClick={() => setActiveTab("edit")}
          >
            Edit
          </button>
          <button
            type="button"
            id="rc-tab-preview"
            role="tab"
            aria-selected={activeTab === "preview"}
            className={`px-3 py-2 rounded-lg text-sm font-medium ${
              activeTab === "preview"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
            onClick={() => setActiveTab("preview")}
          >
            Preview
          </button>
        </div>

        <section
          id="rc-mlc-metadata"
          className="bg-blue-50 border border-blue-200 rounded-lg p-4"
        >
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            MLC Catalog Information
          </h3>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-gray-600 font-medium">Type:</span>
              <span className="ml-2 text-gray-900">{row.type}</span>
            </div>
            {row.mlcSongCode && (
              <div>
                <span className="text-gray-600 font-medium">Song Code:</span>
                <span className="ml-2 text-gray-900">{row.mlcSongCode}</span>
              </div>
            )}
            {row.isrc && (
              <div>
                <span className="text-gray-600 font-medium">ISRC:</span>
                <span className="ml-2 text-gray-900">{row.isrc}</span>
              </div>
            )}
            {row.raw?.artist && (
              <div>
                <span className="text-gray-600 font-medium">Artist:</span>
                <span className="ml-2 text-gray-900">{row.raw.artist}</span>
              </div>
            )}
            {row.release && (
              <div className="col-span-2">
                <span className="text-gray-600 font-medium">Release:</span>
                <span className="ml-2 text-gray-900">{row.release}</span>
                {row.releaseDate && (
                  <span className="ml-2 text-gray-500 text-xs">
                    ({row.releaseDate})
                  </span>
                )}
              </div>
            )}
            {row.raw?.album && !row.release && (
              <div className="col-span-2">
                <span className="text-gray-600 font-medium">Album:</span>
                <span className="ml-2 text-gray-900">{row.raw.album}</span>
              </div>
            )}
            {row.mbid && (
              <div>
                <span className="text-gray-600 font-medium">MBID:</span>
                <span className="ml-2 text-gray-900 font-mono text-xs">
                  {row.mbid}
                </span>
              </div>
            )}
            {row.raw?.writers && row.raw.writers.length > 0 && (
              <div className="col-span-2">
                <span className="text-gray-600 font-medium">Writers:</span>
                <span className="ml-2 text-gray-900">
                  {row.raw.writers
                    .map((w: any) =>
                      `${w.writerFirstName || ""} ${
                        w.writerLastName || ""
                      }`.trim()
                    )
                    .join(", ")}
                </span>
              </div>
            )}
            {row.raw?.publishers && row.raw.publishers.length > 0 && (
              <div className="col-span-2">
                <span className="text-gray-600 font-medium">Publishers:</span>
                <span className="ml-2 text-gray-900">
                  {row.raw.publishers
                    .map((p: any) => p.publisherName || p)
                    .join(", ")}
                </span>
              </div>
            )}
          </div>
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-gray-600 hover:text-gray-900">
              View raw MLC data
            </summary>
            <pre className="mt-2 bg-white p-3 border border-gray-200 rounded text-xs overflow-x-auto">
              {JSON.stringify(row.raw, null, 2)}
            </pre>
          </details>
        </section>

        <MacroSelector
          artistName={row.raw?.artist || row.artist || row.title}
          onSelectMacro={applyMacro}
          onAIRecommend={handleAIRecommend}
          aiLoading={aiLoading}
        />

        {aiReasoning && (
          <section
            id="rc-ai-reasoning"
            className="bg-green-50 border border-green-200 rounded-lg p-4"
          >
            <h3 className="text-sm font-semibold text-gray-900 mb-2">
              AI Recommendation
            </h3>
            <p className="text-sm text-gray-700">{aiReasoning}</p>
          </section>
        )}

        {activeTab === "edit" && (
          <section>
            <h3 className="text-sm font-semibold text-gray-700 mb-3">
              Usage matrix
            </h3>
            <div id="rc-drawer-usage-grid" className="grid grid-cols-1 gap-3">
              {USAGE_KEYS.map((key) => {
                const state = (draft.artist?.usageMatrix?.[key] ||
                  "blocked") as UsageState;
                const meta = USAGE_CATEGORIES[key];
                return (
                  <div
                    key={key}
                    id={`rc-usage-${key}`}
                    className="border border-gray-200 rounded-lg p-4"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex-1">
                        <div className="font-medium text-gray-900">
                          {meta.title}
                        </div>
                        <div className="text-xs text-gray-500 mt-1">
                          {meta.description}
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                          state === "allowed"
                            ? "bg-green-100 text-green-700 border-2 border-green-300"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                        onClick={() => setUsageState(key, "allowed")}
                      >
                        ✅ Allowed
                      </button>
                      <button
                        className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                          state === "requires_approval"
                            ? "bg-yellow-100 text-yellow-700 border-2 border-yellow-300"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                        onClick={() => setUsageState(key, "requires_approval")}
                      >
                        ⚠️ Requires Approval
                      </button>
                      <button
                        className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                          state === "blocked"
                            ? "bg-red-100 text-red-700 border-2 border-red-300"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                        onClick={() => setUsageState(key, "blocked")}
                      >
                        ❌ Blocked
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {activeTab === "edit" && (
          <section>
            <h3 className="text-sm font-semibold text-gray-700 mb-3">
              Restriction policies
            </h3>
            <div
              id="rc-drawer-restriction-grid"
              className="grid grid-cols-1 gap-3"
            >
              {RESTRICTION_KEYS.map((key) => {
                const state = (draft.artist?.restrictionMatrix?.[key] ||
                  "allowed") as RestrictionState;
                const meta = RESTRICTION_CATEGORIES[key];
                return (
                  <div
                    key={key}
                    id={`rc-restriction-${key}`}
                    className="border border-gray-200 rounded-lg p-4"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex-1">
                        <div className="font-medium text-gray-900">
                          {meta.title}
                        </div>
                        <div className="text-xs text-gray-500 mt-1">
                          {meta.description}
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                          state === "allowed"
                            ? "bg-green-100 text-green-700 border-2 border-green-300"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                        onClick={() => setRestrictionState(key, "allowed")}
                      >
                        ✅ Allowed
                      </button>
                      <button
                        className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                          state === "conditional"
                            ? "bg-yellow-100 text-yellow-700 border-2 border-yellow-300"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                        onClick={() => setRestrictionState(key, "conditional")}
                      >
                        ⚠️ Conditional
                      </button>
                      <button
                        className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                          state === "denied"
                            ? "bg-red-100 text-red-700 border-2 border-red-300"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                        onClick={() => setRestrictionState(key, "denied")}
                      >
                        ❌ Denied
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {activeTab === "edit" && (
          <section className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-gray-700">
                Approval window (days)
              </label>
              <input
                type="number"
                min={0}
                className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                value={draft.artist?.approval?.approvalWindowDays ?? 0}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  setDraft((prev: any) => {
                    const next = clone(prev);
                    next.artist = next.artist || {};
                    next.artist.approval = next.artist.approval || {};
                    next.artist.approval.approvalWindowDays = value;
                    return next;
                  });
                }}
              />
            </div>
          </section>
        )}

        {activeTab === "edit" && (
          <section
            id="rc-contact-metadata"
            className="border border-gray-200 rounded-lg p-4"
          >
            <h3 className="text-sm font-semibold text-gray-700 mb-3">
              Contact & escalation
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-600">
                  Preferred channel
                </label>
                <select
                  className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                  value={draft.contact?.preferredChannel || "email"}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDraft((prev: any) => {
                      const next = clone(prev);
                      next.contact = next.contact || {};
                      next.contact.preferredChannel = v;
                      return next;
                    });
                  }}
                >
                  <option value="email">Email</option>
                  <option value="slack">Slack</option>
                  <option value="portal">Partner portal</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-600">Approval email</label>
                <input
                  className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                  placeholder="rights@label.example"
                  value={draft.contact?.email || ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDraft((prev: any) => {
                      const next = clone(prev);
                      next.contact = next.contact || {};
                      next.contact.email = v;
                      return next;
                    });
                  }}
                />
              </div>
              <div>
                <label
                  className="text-xs text-gray-600 cursor-help"
                  title="Response time commitment for licensing inquiries. Licensees expect a reply within this window."
                >
                  Response SLA (hours) <span className="text-gray-400">?</span>
                </label>
                <input
                  type="number"
                  min={0}
                  className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                  placeholder="48"
                  value={draft.contact?.slaHours ?? ""}
                  onChange={(e) => {
                    const v =
                      e.target.value === "" ? null : Number(e.target.value);
                    setDraft((prev: any) => {
                      const next = clone(prev);
                      next.contact = next.contact || {};
                      next.contact.slaHours = v;
                      return next;
                    });
                  }}
                />
                <div className="text-xs text-gray-400 mt-1">
                  Standard: 48-72 hours
                </div>
              </div>
              <div>
                <label
                  className="text-xs text-gray-600 cursor-help"
                  title="Alternative contact if primary doesn't respond within SLA. Could be a backup email, sync agency, or legal department."
                >
                  Fallback contact <span className="text-gray-400">?</span>
                </label>
                <input
                  className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                  placeholder="legal@publisher.example"
                  value={draft.contact?.fallbackContact || ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDraft((prev: any) => {
                      const next = clone(prev);
                      next.contact = next.contact || {};
                      next.contact.fallbackContact = v;
                      return next;
                    });
                  }}
                />
                <div className="text-xs text-gray-400 mt-1">
                  Escalation if no response
                </div>
              </div>
              <div className="md:col-span-2">
                <label className="text-xs text-gray-600">Notes</label>
                <input
                  className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                  placeholder="Escalate for political requests; provide briefs for sync."
                  value={draft.contact?.notes || ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDraft((prev: any) => {
                      const next = clone(prev);
                      next.contact = next.contact || {};
                      next.contact.notes = v;
                      return next;
                    });
                  }}
                />
              </div>
            </div>
          </section>
        )}

        {activeTab === "edit" && (
          <section
            id="rc-pricing"
            className="border border-gray-200 rounded-lg p-4"
          >
            <h3 className="text-sm font-semibold text-gray-700 mb-3">
              Pricing
            </h3>
            <p className="text-xs text-gray-500 mb-3">
              Optional: set base USD price per usage. Downstream UIs can show
              estimated price with multipliers.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {(["ads_brand", "film_tv", "ugc_creator", "video_game"] as UsageCategory[]).map(
                (k) => (
                  <div key={k}>
                    <label className="text-xs text-gray-600">
                      {USAGE_CATEGORIES[k]?.title || k}
                    </label>
                    <input
                      type="number"
                      min={0}
                      className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                      value={draft.master?.pricing?.basePriceUsd?.[k] ?? ""}
                      onChange={(e) => {
                        const v =
                          e.target.value === "" ? null : Number(e.target.value);
                        setDraft((prev: any) => {
                          const next = clone(prev);
                          next.master = next.master || {};
                          next.master.pricing = next.master.pricing || {};
                          next.master.pricing.basePriceUsd =
                            next.master.pricing.basePriceUsd || {};
                          if (v === null)
                            delete next.master.pricing.basePriceUsd[k];
                          else next.master.pricing.basePriceUsd[k] = v;
                          return next;
                        });
                      }}
                    />
                  </div>
                )
              )}
              <div>
                <label className="text-xs text-gray-600">
                  License stance multiplier
                </label>
                <input
                  type="number"
                  min={0}
                  step="0.1"
                  className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                  value={draft.master?.pricing?.licenseStanceMultiplier ?? 1.0}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setDraft((prev: any) => {
                      const next = clone(prev);
                      next.master = next.master || {};
                      next.master.pricing = next.master.pricing || {};
                      next.master.pricing.licenseStanceMultiplier = v;
                      return next;
                    });
                  }}
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">
                  Audience reach multiplier
                </label>
                <input
                  type="number"
                  min={0}
                  step="0.1"
                  className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                  value={draft.master?.pricing?.audienceReachMultiplier ?? 1.0}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setDraft((prev: any) => {
                      const next = clone(prev);
                      next.master = next.master || {};
                      next.master.pricing = next.master.pricing || {};
                      next.master.pricing.audienceReachMultiplier = v;
                      return next;
                    });
                  }}
                />
              </div>
              <div className="md:col-span-2">
                <label className="text-xs text-gray-600">Rationale notes</label>
                <input
                  className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
                  placeholder="Premium catalog; higher rates for ads, flexible for sync."
                  value={draft.master?.pricing?.rationaleNotes || ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDraft((prev: any) => {
                      const next = clone(prev);
                      next.master = next.master || {};
                      next.master.pricing = next.master.pricing || {};
                      next.master.pricing.rationaleNotes = v;
                      return next;
                    });
                  }}
                />
              </div>
            </div>
          </section>
        )}

        {activeTab === "preview" && (
          <section id="rc-preview-mode" className="space-y-3">
            <h3 className="text-sm font-semibold text-gray-700">
              Downstream licensing UI preview
            </h3>
            <p className="text-xs text-gray-500">
              This shows how badges/checklists could surface for common usage
              categories.
            </p>
            <div className="grid grid-cols-1 gap-3">
              {([
                "ads_brand",
                "film_tv",
                "ugc_creator",
                "ai_training_recursive",
              ] as UsageCategory[]).map((k) => {
                const state = (draft.artist?.usageMatrix?.[k] ||
                  "blocked") as UsageState;
                const badge =
                  state === "allowed"
                    ? "Allowed"
                    : state === "requires_approval"
                    ? "Approval required"
                    : "Blocked";
                const badgeClass =
                  state === "allowed"
                    ? "bg-green-100 text-green-800"
                    : state === "requires_approval"
                    ? "bg-yellow-100 text-yellow-800"
                    : "bg-red-100 text-red-800";
                const approvalDays =
                  draft.artist?.approval?.approvalWindowDays ?? 0;
                const deniedRestrictions = RESTRICTION_KEYS.filter(
                  (rk) =>
                    (draft.artist?.restrictionMatrix?.[rk] || "allowed") ===
                    "denied"
                );
                return (
                  <div
                    key={k}
                    id={`rc-preview-${k}`}
                    className="border border-gray-200 rounded-lg p-4"
                  >
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-medium text-gray-900">
                        {USAGE_CATEGORIES[k]?.title || k}
                      </div>
                      <span
                        className={`text-xs px-2 py-1 rounded ${badgeClass}`}
                      >
                        {badge}
                      </span>
                    </div>
                    {state === "requires_approval" && (
                      <div className="mt-2 text-xs text-gray-600">
                        Approval SLA: {approvalDays || "—"} day
                        {approvalDays === 1 ? "" : "s"}
                      </div>
                    )}
                    <div className="mt-3">
                      <div className="text-[11px] text-gray-500 font-medium">
                        Checklist
                      </div>
                      <ul className="mt-1 text-xs text-gray-700 space-y-1">
                        <li>Confirm territory and term</li>
                        {deniedRestrictions.length > 0 && (
                          <li>
                            Restricted:{" "}
                            {deniedRestrictions.slice(0, 3).join(", ")}
                            {deniedRestrictions.length > 3 ? "…" : ""}
                          </li>
                        )}
                        <li>Contact: rights@your-org.example</li>
                      </ul>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        <section
          id="rc-collaboration"
          className="border-t border-gray-200 pt-4 space-y-3"
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-700">
              Collaboration
            </h3>
            <button
              id="rc-approval-request"
              className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700"
              onClick={requestApproval}
              type="button"
            >
              Request approval
            </button>
          </div>

          <div className="grid grid-cols-1 gap-3">
            <div className="border border-gray-200 rounded-lg p-3">
              <div className="text-xs font-medium text-gray-600 mb-2">
                Approvals
              </div>
              {approvals.length === 0 ? (
                <div className="text-xs text-gray-500">
                  No approval requests yet.
                </div>
              ) : (
                <ul className="space-y-2">
                  {approvals.slice(0, 5).map((a) => (
                    <li key={a.id} className="text-xs text-gray-700">
                      <span className="font-medium">{a.status}</span> •
                      requested by{" "}
                      <span className="font-mono">{a.requestedBy}</span>
                      {a.dueAt && (
                        <span className="text-gray-400">
                          {" "}
                          • due {String(a.dueAt).slice(0, 10)}
                        </span>
                      )}
                      {a.status === "open" && (
                        <span className="ml-2 inline-flex gap-2">
                          <button
                            type="button"
                            className="text-[11px] px-2 py-1 rounded bg-green-100 text-green-800 hover:bg-green-200"
                            onClick={() => decideApproval(a.id, "approved")}
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            className="text-[11px] px-2 py-1 rounded bg-red-100 text-red-800 hover:bg-red-200"
                            onClick={() => decideApproval(a.id, "rejected")}
                          >
                            Reject
                          </button>
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="border border-gray-200 rounded-lg p-3">
              <div className="text-xs font-medium text-gray-600 mb-2">
                Comments
              </div>
              <div className="space-y-2">
                <textarea
                  id="rc-comment-body"
                  className="w-full border border-gray-300 rounded-lg p-2 text-sm"
                  placeholder="Add a comment… Use @email for mentions."
                  value={commentBody}
                  onChange={(e) => setCommentBody(e.target.value)}
                />
                <div className="flex justify-end">
                  <button
                    id="rc-comment-post"
                    className="text-xs px-3 py-1.5 rounded-lg bg-gray-900 text-white hover:bg-black"
                    onClick={postComment}
                    type="button"
                  >
                    Post comment
                  </button>
                </div>
              </div>
              <div className="mt-3">
                {comments.length === 0 ? (
                  <div className="text-xs text-gray-500">No comments yet.</div>
                ) : (
                  <ul className="space-y-2">
                    {comments.slice(-5).map((c) => (
                      <li key={c.id} className="text-xs text-gray-700">
                        <span className="font-mono">{c.author}</span>: {c.body}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="border border-gray-200 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div className="text-xs font-medium text-gray-600">History</div>
                <button
                  id="rc-history-diff"
                  className="text-xs px-3 py-1.5 rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200"
                  onClick={computeDiffSinceLast}
                  type="button"
                >
                  What changed since last version?
                </button>
              </div>
              {diffSummary && (
                <div className="mt-2 text-xs text-gray-700">{diffSummary}</div>
              )}
              <div className="mt-2 text-[11px] text-gray-500">
                {history.length
                  ? `Latest versions: ${history
                      .slice(0, 5)
                      .map((h) => h.version)
                      .join(", ")}`
                  : "No history yet."}
              </div>
            </div>
          </div>
        </section>

        {error && <div className="text-sm text-red-600">{error}</div>}

        <div className="flex justify-end gap-3">
          <button className="px-4 py-2 text-sm text-gray-600" onClick={onClose}>
            Cancel
          </button>
          <button
            className={`px-5 py-2 rounded-lg text-white ${
              saving || loading
                ? "bg-blue-300 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-700"
            }`}
            onClick={handleSave}
            disabled={saving || loading}
          >
            {saving ? "Saving…" : loading ? "Loading…" : "Save changes"}
          </button>
        </div>
      </div>
    </aside>
  );
}
