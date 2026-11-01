import React from "react";

import type { OnboardingState, OrganizationOnboardingStatus } from "../types/rights";
import { getOrganizationOnboardingStatus } from "../utils/http";


const LABELS: Record<OnboardingState, string> = {
  complete: "Complete",
  in_progress: "In progress",
  pending: "Next",
  not_applicable: "Not applicable",
};

export function onboardingStateClasses(state: OnboardingState): string {
  if (state === "complete") return "bg-emerald-100 text-emerald-800";
  if (state === "in_progress") return "bg-amber-100 text-amber-800";
  if (state === "pending") return "bg-blue-100 text-blue-800";
  return "bg-slate-100 text-slate-600";
}

export function OnboardingChecklist({
  apiBase,
  sessionId,
  organizationId,
  onNavigate,
}: {
  apiBase: string;
  sessionId: string;
  organizationId: string;
  onNavigate?: (action: string) => void;
}) {
  const [status, setStatus] = React.useState<OrganizationOnboardingStatus | null>(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await getOrganizationOnboardingStatus(apiBase, sessionId, organizationId));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load organization setup.");
    } finally {
      setLoading(false);
    }
  }, [apiBase, organizationId, sessionId]);

  React.useEffect(() => void load(), [load]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="organization-setup-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="organization-setup-title" className="text-lg font-semibold text-slate-950">Organization setup</h2>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">Follow one evidence-backed path from managed catalog to a reconciled permission. Setup never creates authority by itself.</p>
        </div>
        {status && <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{status.completedCount} of {status.applicableCount} complete</span>}
      </div>
      {loading && !status && <p className="mt-5 text-sm text-slate-500">Checking organization setup…</p>}
      {error && <div role="alert" className="mt-5 rounded-xl bg-red-50 p-3 text-sm text-red-800">{error} <button type="button" onClick={() => void load()} className="font-medium underline">Try again</button></div>}
      {status && (
        <ol className="mt-5 grid gap-3 md:grid-cols-2">
          {status.milestones.map((milestone) => (
            <li key={milestone.key} className={`rounded-xl border p-4 ${milestone.status === "not_applicable" ? "border-slate-100 bg-slate-50/60" : "border-slate-200"}`}>
              <div className="flex items-center justify-between gap-2">
                <strong className="text-sm capitalize text-slate-900">{milestone.key.replace(/_/g, " ")}</strong>
                <span className={`rounded-full px-2 py-1 text-xs font-medium ${onboardingStateClasses(milestone.status)}`}>{LABELS[milestone.status]}</span>
              </div>
              <p className="mt-2 text-sm leading-5 text-slate-600">{milestone.summary}</p>
              {milestone.action && milestone.status !== "complete" && milestone.status !== "not_applicable" && onNavigate && (
                <button type="button" onClick={() => onNavigate(milestone.action!)} className="mt-3 text-sm font-medium text-blue-700 underline">Open {milestone.action.replace(/_/g, " ")}</button>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
