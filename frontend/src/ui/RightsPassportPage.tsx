import React from "react";
import {
  USAGE_CATEGORIES,
  USAGE_KEYS,
  RESTRICTION_CATEGORIES,
  RESTRICTION_KEYS,
  UsageCategory,
  RestrictionState,
} from "../types/rights";
import { checkedJson } from "../utils/http";

type Props = {
  ownerEmail: string;
  keyId: string;
};

export function restrictionDisplayState(value: unknown): RestrictionState | "unknown" {
  return value === "allowed" || value === "conditional" || value === "denied" ? value : "unknown";
}

export function normalizePassportEditLink(
  value: unknown,
  expectedOwner: string,
  expectedKey: string,
  origin?: string,
): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const trustedOrigin = origin || (typeof window !== "undefined" ? window.location.origin : "");
  if (!trustedOrigin) return null;
  try {
    const url = new URL(value, trustedOrigin);
    if (url.origin !== trustedOrigin) return null;
    if (url.searchParams.get("view") !== "detail") return null;
    if (url.searchParams.get("owner") !== expectedOwner || url.searchParams.get("key") !== expectedKey) return null;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

export function RightsPassportPage({ ownerEmail, keyId }: Props) {
  const [data, setData] = React.useState<any | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          `/api/rights/passport?owner=${encodeURIComponent(
            ownerEmail
          )}&key=${encodeURIComponent(keyId)}`
        );
        const d = await checkedJson(res, "Passport request");
        if (d.owner !== ownerEmail || d.key !== keyId) throw new Error("Passport response scope does not match the requested owner and work");
        if (!cancelled) setData(d);
      } catch (e: any) {
        if (!cancelled) setError(e.message || "Failed to load passport");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ownerEmail, keyId]);

  if (loading)
    return (
      <div className="bg-white rounded-lg shadow-sm p-6">Loading passport…</div>
    );
  if (error)
    return (
      <div className="bg-white rounded-lg shadow-sm p-6 text-red-600">
        {error}
      </div>
    );
  if (!data) return null;

  const badges = data.badges || {};
  const restrictions = data.restrictions || {};
  const contact = data.contact || {};
  const pricing = data.pricing || {};
  const estimates = pricing.estimates || {};
  const editLink = normalizePassportEditLink(data.deepLinkEdit, ownerEmail, keyId);

  const badgePill = (state: string) => {
    if (state === "allowed") return "bg-green-100 text-green-800";
    if (state === "requires_approval") return "bg-yellow-100 text-yellow-800";
    return "bg-red-100 text-red-800";
  };

  return (
    <section
      id="rc-rights-passport"
      className="bg-white rounded-lg shadow-sm p-6 space-y-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            Rights Passport
          </h2>
          <div className="text-xs text-gray-500 mt-1">
            Key: <span className="font-mono">{data.key}</span> • Owner:{" "}
            <span className="font-mono">{data.owner}</span>
          </div>
        </div>
        {editLink ? (
          <a
            id="rc-passport-edit-link"
            className="text-sm text-blue-600 hover:underline"
            href={editLink}
          >
            Edit →
          </a>
        ) : (
          <span className="text-xs text-gray-500">Edit link unavailable</span>
        )}
      </div>

      <div className="border border-gray-200 rounded-lg p-4">
        <div className="text-sm font-semibold text-gray-800">
          Contact & escalation
        </div>
        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-gray-700">
          <div>
            <span className="text-gray-500">Preferred channel:</span>{" "}
            {contact.preferredChannel || "email"}
          </div>
          <div>
            <span className="text-gray-500">Contact email:</span>{" "}
            {contact.email || <span className="text-gray-400 italic">Not specified</span>}
          </div>
          <div
            className="cursor-help"
            title="Response time commitment - expect a reply within this window for licensing inquiries"
          >
            <span className="text-gray-500">Response SLA:</span>{" "}
            {contact.slaHours ? (
              `${contact.slaHours} hours`
            ) : (
              <span className="text-gray-400 italic">No commitment</span>
            )}
          </div>
          <div
            className="cursor-help"
            title="Alternative contact if primary doesn't respond within SLA"
          >
            <span className="text-gray-500">Escalation contact:</span>{" "}
            {contact.fallbackContact || <span className="text-gray-400 italic">None</span>}
          </div>
          {contact.notes && (
            <div className="md:col-span-2 text-xs text-gray-600">
              Notes: {contact.notes}
            </div>
          )}
        </div>
      </div>

      <div className="border border-gray-200 rounded-lg p-4">
        <div className="text-sm font-semibold text-gray-800">Usage badges</div>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
          {USAGE_KEYS.map((k) => (
            <div
              key={k}
              className="flex items-center justify-between border border-gray-100 rounded p-2"
            >
              <div className="text-sm text-gray-800">
                {USAGE_CATEGORIES[k].title}
              </div>
              <span
                className={`text-xs px-2 py-1 rounded ${badgePill(
                  badges[k] || "blocked"
                )}`}
              >
                {(badges[k] || "blocked") === "requires_approval"
                  ? "Approval"
                  : (badges[k] || "blocked") === "allowed"
                  ? "Allowed"
                  : "Blocked"}
              </span>
            </div>
          ))}
        </div>
        {data.approval?.approvalWindowDays ? (
          <div className="mt-2 text-xs text-gray-600">
            Approval window: {data.approval.approvalWindowDays} day(s)
          </div>
        ) : null}
      </div>

      <div className="border border-gray-200 rounded-lg p-4">
        <div className="text-sm font-semibold text-gray-800">
          Restrictions checklist
        </div>
        <ul className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
          {RESTRICTION_KEYS.map((k) => (
            <li
              key={k}
              className="flex items-center justify-between border border-gray-100 rounded p-2"
            >
              <span className="text-gray-800">
                {RESTRICTION_CATEGORIES[k].title}
              </span>
              <span className="text-xs text-gray-600">
                {restrictionDisplayState(restrictions[k])}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="border border-gray-200 rounded-lg p-4">
        <div className="text-sm font-semibold text-gray-800">
          Pricing clarity
        </div>
        {pricing.rationale ? (
          <div className="mt-2 text-xs text-gray-600">
            Rationale: {pricing.rationale}
          </div>
        ) : (
          <div className="mt-2 text-xs text-gray-500">
            No rationale notes provided.
          </div>
        )}
        {Object.keys(estimates).length === 0 ? (
          <div className="mt-2 text-xs text-gray-500">
            No per-usage prices configured.
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {Object.entries(estimates).map(([usage, p]: any) => (
              <div
                key={usage}
                className="flex items-center justify-between text-sm"
              >
                <div className="text-gray-800">
                  {USAGE_CATEGORIES[usage as UsageCategory]?.title || usage}
                </div>
                <div className="font-medium text-gray-900">
                  ${p.estimatedPriceUsd}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}



