import React from "react";
import { checkedJson } from "../utils/http";

type Props = {
  headers: () => HeadersInit;
};

export function DashboardPage({ headers }: Props) {
  const [data, setData] = React.useState<any | null>(null);
  const [approvals, setApprovals] = React.useState<any[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadToken, setReloadToken] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [s, a] = await Promise.all([
          fetch("/api/dashboard/summary", { headers: headers() }).then((response) =>
            checkedJson(response, "Dashboard summary"),
          ),
          fetch("/api/approvals/list?status=open", { headers: headers() }).then((response) =>
            checkedJson(response, "Approval list"),
          ),
        ]);
        if (cancelled) return;
        setData(s);
        setApprovals(a.items || []);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Dashboard request failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [headers, reloadToken]);

  if (loading) {
    return (
      <section className="bg-white rounded-lg shadow-sm p-6 text-gray-500">
        Loading dashboard…
      </section>
    );
  }

  if (error) {
    return (
      <section className="bg-white rounded-lg shadow-sm p-6" role="alert">
        <div className="text-sm text-red-700">{error}</div>
        <button className="mt-3 rounded bg-gray-900 px-3 py-2 text-sm text-white" onClick={() => setReloadToken((value) => value + 1)}>
          Retry dashboard
        </button>
      </section>
    );
  }

  if (!data) return null;

  const stance = data.stanceCounts || {};

  return (
    <section id="rc-dashboard" className="space-y-4">
      <div className="bg-white rounded-lg shadow-sm p-6">
        <h2 className="text-lg font-semibold text-gray-900">Dashboard</h2>
        <p className="text-sm text-gray-500 mt-1">
          Organization-level metrics: track how many works are protected, exposed, or pending approval.
        </p>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-3">
          <div className="border border-gray-200 rounded-lg p-3">
            <div className="text-xs text-gray-500">Allowed</div>
            <div className="text-xl font-semibold text-gray-900">
              {stance.allowed || 0}
            </div>
          </div>
          <div className="border border-gray-200 rounded-lg p-3">
            <div className="text-xs text-gray-500">Approval</div>
            <div className="text-xl font-semibold text-gray-900">
              {stance.requires_approval || 0}
            </div>
          </div>
          <div className="border border-gray-200 rounded-lg p-3">
            <div className="text-xs text-gray-500">Blocked</div>
            <div className="text-xl font-semibold text-gray-900">
              {stance.blocked || 0}
            </div>
          </div>
          <div className="border border-gray-200 rounded-lg p-3">
            <div className="text-xs text-gray-500">Approvals pending</div>
            <div className="text-xl font-semibold text-gray-900">
              {data.approvalsPending || 0}
            </div>
          </div>
        </div>
        <div className="mt-3 text-xs text-gray-600">
          Changes last 7 days: {data.changesLast7Days || 0} • Recent ingest
          errors: {data.recentIngestErrors || 0}
        </div>
      </div>

      <div className="bg-white rounded-lg shadow-sm p-6">
        <h3 className="text-sm font-semibold text-gray-700">Open approvals</h3>
        {approvals.length === 0 ? (
          <div className="mt-2 text-sm text-gray-500">None.</div>
        ) : (
          <ul className="mt-2 space-y-2">
            {approvals.slice(0, 10).map((a) => (
              <li key={a.id} className="text-sm text-gray-700">
                <span className="font-mono">{a.key}</span> • requested by{" "}
                <span className="font-mono">{a.requestedBy}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}




