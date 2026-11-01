import React from "react";

import type { NodeReadiness, ReadinessState } from "../types/rights";
import { getNodeReadiness } from "../utils/http";


const LABELS: Record<ReadinessState, string> = {
  ready: "Ready",
  warning: "Review",
  disabled: "Disabled",
  missing: "Missing",
  stale: "Stale",
  blocked: "Blocked",
};

export function readinessStateClasses(state: ReadinessState): string {
  if (state === "ready") return "bg-emerald-100 text-emerald-800";
  if (state === "warning" || state === "stale") return "bg-amber-100 text-amber-800";
  if (state === "missing" || state === "blocked") return "bg-red-100 text-red-800";
  return "bg-slate-100 text-slate-600";
}

export function resolveRemediationHref(remediation: string, sourceCodeUrl?: string | null): string {
  if (/^https:\/\//.test(remediation)) return remediation;
  const base = sourceCodeUrl?.replace(/\/$/, "") || "https://github.com/tymrtn/clef-rights-node/blob/main";
  return `${base}/${remediation.replace(/^\//, "")}`;
}

export function isReadinessResultCurrent(
  checkedAt: string,
  nowMilliseconds = Date.now(),
  maximumAgeMilliseconds = 60_000,
): boolean {
  const checkedMilliseconds = new Date(checkedAt).getTime();
  const age = nowMilliseconds - checkedMilliseconds;
  return Number.isFinite(checkedMilliseconds) && age >= 0 && age <= maximumAgeMilliseconds;
}

export function DeploymentReadinessPanel({
  apiBase,
  sessionId,
  sourceCodeUrl,
}: {
  apiBase: string;
  sessionId: string;
  sourceCodeUrl?: string | null;
}) {
  const [readiness, setReadiness] = React.useState<NodeReadiness | null>(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setReadiness(await getNodeReadiness(apiBase, sessionId));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load deployment readiness.");
    } finally {
      setLoading(false);
    }
  }, [apiBase, sessionId]);

  React.useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(interval);
  }, [load]);

  const displayReady = Boolean(
    readiness?.ready
    && !error
    && isReadinessResultCurrent(readiness.checkedAt),
  );

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="deployment-readiness-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="deployment-readiness-title" className="text-lg font-semibold text-slate-950">Deployment readiness</h2>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">Non-secret checks for this node’s source, signing identity, workers, delivery services, and optional adapters.</p>
        </div>
        <div className="flex items-center gap-2">
          {readiness && <span className={`rounded-full px-3 py-1 text-xs font-medium ${displayReady ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>{displayReady ? "Ready for this mode" : "Action required"}</span>}
          <button type="button" disabled={loading} onClick={() => void load()} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 disabled:opacity-50">Refresh</button>
        </div>
      </div>
      {loading && !readiness && <p className="mt-5 text-sm text-slate-500">Checking the deployment…</p>}
      {error && <div role="alert" className="mt-5 rounded-xl bg-red-50 p-3 text-sm text-red-800">{error} <button type="button" onClick={() => void load()} className="font-medium underline">Try again</button></div>}
      {readiness && (
        <div className="mt-5 space-y-3">
          {readiness.checks.map((check) => (
            <article key={check.key} className="rounded-xl border border-slate-200 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <strong className="text-sm capitalize text-slate-900">{check.key.replace(/_/g, " ")}</strong>
                <span className={`rounded-full px-2 py-1 text-xs font-medium ${readinessStateClasses(check.status)}`}>{LABELS[check.status]}{check.required ? " · required" : ""}</span>
              </div>
              <p className="mt-2 text-sm text-slate-600">{check.summary}</p>
              {check.remediation && <a className="mt-2 inline-block text-sm font-medium text-blue-700 underline" href={resolveRemediationHref(check.remediation, sourceCodeUrl)} target="_blank" rel="noreferrer">Open remediation instructions</a>}
            </article>
          ))}
          <p className="text-xs text-slate-500">Checked {new Date(readiness.checkedAt).toLocaleString()} · mode {readiness.deploymentMode.replace(/_/g, " ")}</p>
        </div>
      )}
    </section>
  );
}
