import React from "react";
import { CatalogRow } from "./ResultsTable";

type Props = {
  onResults: (rows: CatalogRow[]) => void;
  headers: () => HeadersInit;
};

export function ManagedCatalogPage({ onResults, headers }: Props) {
  const [q, setQ] = React.useState("");
  const [stance, setStance] = React.useState<string>("");
  const [approvalRequired, setApprovalRequired] =
    React.useState<boolean>(false);
  const [blockedRestriction, setBlockedRestriction] =
    React.useState<string>("");
  const [loading, setLoading] = React.useState(false);
  const [saved, setSaved] = React.useState<any[]>([]);
  const [saveName, setSaveName] = React.useState("");
  const [error, setError] = React.useState("");
  const didAutoRun = React.useRef(false);
  const requestIdRef = React.useRef(0);

  async function loadSaved() {
    try {
      const res = await fetch("/api/saved-searches/list", {
        headers: headers(),
      });
      if (!res.ok) throw new Error(`Saved-search load failed (${res.status})`);
      const data = await res.json();
      setSaved(data.items || []);
    } catch {
      // ignore
    }
  }

  React.useEffect(() => {
    loadSaved();
    // Auto-run search on mount to show catalog items immediately (once only)
    if (!didAutoRun.current) {
      didAutoRun.current = true;
      run();
    }
    return () => {
      requestIdRef.current += 1;
      didAutoRun.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  type SearchFilters = {
    q: string;
    stance: string;
    approvalRequired: boolean;
    blockedRestriction: string;
  };

  async function run(explicit?: SearchFilters) {
    const requestId = ++requestIdRef.current;
    const active = explicit || { q, stance, approvalRequired, blockedRestriction };
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (active.q.trim()) params.set("q", active.q.trim());
      params.set("intended_usage", "streaming_visual");
      if (active.stance) params.set("stance", active.stance);
      if (active.approvalRequired) params.set("approval_required", "true");
      if (active.blockedRestriction)
        params.set("blocked_restriction", active.blockedRestriction);
      const res = await fetch(`/api/catalog/faceted?${params.toString()}`, {
        headers: headers(),
      });
      if (!res.ok) throw new Error(`Catalog search failed (${res.status})`);
      const data = await res.json();
      const rows: CatalogRow[] = (data.items || []).map((i: any) => ({
        key: i.key,
        title: i.title,
        type: i.type,
        artist: i.artist,
        isrc: i.isrc,
        mlcSongCode: i.mlcSongCode,
        releaseDate: i.releaseDate,
        headlineStatus: i.headlineStatus,
        aiGenStatus: i.aiGenStatus,
        approvalWindowDays: i.approvalWindowDays,
        raw: i,
      }));
      if (requestId === requestIdRef.current) onResults(rows);
    } catch (err: any) {
      if (requestId === requestIdRef.current)
        setError(err.message || "Catalog search failed");
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }

  async function applySavedSearch(item: any) {
    const query = item.query || {};
    const next = {
      q: query.q || "",
      stance: query.stance || "",
      approvalRequired: !!query.approval_required,
      blockedRestriction: query.blocked_restriction || "",
    };
    setQ(next.q);
    setStance(next.stance);
    setApprovalRequired(next.approvalRequired);
    setBlockedRestriction(next.blockedRestriction);
    await run(next);
  }

  async function saveCurrent() {
    const name = saveName.trim();
    if (!name) return;
    try {
      const response = await fetch("/api/saved-searches/create", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({
          name,
          query: {
            q: q.trim() || undefined,
            stance: stance || undefined,
            approval_required: approvalRequired || undefined,
            blocked_restriction: blockedRestriction || undefined,
          },
          is_smart_folder: true,
        }),
      });
      if (!response.ok) throw new Error(`Saved search failed (${response.status})`);
      setSaveName("");
      await loadSaved();
    } catch (err: any) {
      setError(err.message || "Unable to save search");
    }
  }

  return (
    <section
      id="rc-managed-catalog"
      className="bg-white rounded-lg shadow-sm p-4"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-gray-700">My Catalog</h3>
          <p className="text-xs text-gray-500 mt-1">
            Browse your stored works. Click "View details" to configure AI training, licensing rules, and restrictions.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            id="rc-saved-searches"
            className="text-sm border border-gray-300 rounded-lg px-2 py-2"
            onChange={(e) => {
              const id = e.target.value;
              const item = saved.find((s) => s.id === id);
              if (item) applySavedSearch(item);
            }}
            defaultValue=""
          >
            <option value="" disabled>
              Saved searches…
            </option>
            {saved.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-3 flex flex-wrap gap-3 items-end">
        <div className="flex flex-col">
          <label className="text-xs text-gray-600 mb-1">Search</label>
          <input
            id="rc-managed-q"
            className="px-3 py-2 border border-gray-300 rounded-lg"
            placeholder="title, artist, key…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
          />
        </div>
        <div className="flex flex-col">
          <label className="text-xs text-gray-600 mb-1">Stance</label>
          <select
            id="rc-managed-stance"
            className="px-3 py-2 border border-gray-300 rounded-lg"
            value={stance}
            onChange={(e) => setStance(e.target.value)}
          >
            <option value="">Any</option>
            <option value="allowed">Allowed</option>
            <option value="requires_approval">Approval</option>
            <option value="blocked">Blocked</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <input
            id="rc-managed-approval-required"
            type="checkbox"
            checked={approvalRequired}
            onChange={(e) => setApprovalRequired(e.target.checked)}
          />
          <label
            htmlFor="rc-managed-approval-required"
            className="text-sm text-gray-700"
          >
            Approval required
          </label>
        </div>
        <div className="flex flex-col">
          <label className="text-xs text-gray-600 mb-1">
            Blocked restriction
          </label>
          <input
            id="rc-managed-blocked-restriction"
            className="px-3 py-2 border border-gray-300 rounded-lg"
            placeholder="political, adult…"
            value={blockedRestriction}
            onChange={(e) => setBlockedRestriction(e.target.value)}
          />
        </div>
        <button
          id="rc-managed-run"
          className={`px-4 py-2 rounded-lg text-white ${
            loading
              ? "bg-blue-300 cursor-not-allowed"
              : "bg-blue-600 hover:bg-blue-700"
          }`}
          onClick={() => run()}
          disabled={loading}
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 items-end">
        <div className="flex flex-col">
          <label className="text-xs text-gray-600 mb-1">
            Save as smart folder
          </label>
          <input
            id="rc-managed-save-name"
            className="px-3 py-2 border border-gray-300 rounded-lg"
            placeholder="needs approval"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
          />
        </div>
        <button
          id="rc-managed-save"
          className="px-3 py-2 rounded-lg bg-gray-900 text-white hover:bg-black"
          onClick={saveCurrent}
          type="button"
        >
          Save
        </button>
      </div>
    </section>
  );
}
