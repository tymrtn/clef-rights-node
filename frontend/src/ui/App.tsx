import React from "react";
import { UserGate, UserRole, ROLE_INFO, isEmail, parseUserRole } from "./UserGate";
import { ResultsTable, CatalogRow } from "./ResultsTable";
import { RightsDrawer } from "./RightsDrawer";
import { BulkEditModal } from "./BulkEditModal";
import { ManagedCatalogPage } from "./ManagedCatalogPage";
import { RightsPassportPage } from "./RightsPassportPage";
import { DashboardPage } from "./DashboardPage";
import { IntegrationStatus } from "./IntegrationStatus";
import { checkedJson } from "../utils/http";
import { safeStorageGet, safeStorageRemove } from "../utils/storage";

export function normaliseKey(row: any, entityType?: CatalogRow["type"]) {
  const type = entityType || row.type || (row.isrc ? "recording" : "work");
  const mlcSongCode = row.mlcSongCode || row.mlcsongCode;
  if (type === "recording" && row.isrc) return `isrc:${row.isrc}`;
  if (type === "work" && mlcSongCode) return `mlc:${mlcSongCode}`;
  if (row.mbid || row.id) return `source:${type}:${row.mbid || row.id}`;
  const title = row.title || row.workTitle;
  const artist = row.artist || row.performer;
  const release = row.release || row.releaseTitle || row.releaseDate;
  const writers = JSON.stringify(row.writers || []);
  const publishers = JSON.stringify(row.publishers || row.publisher || []);
  if (title && (artist || release || writers !== "[]" || publishers !== "[]")) {
    const composite = [
      type,
      title,
      artist || "",
      release || "",
      writers,
      publishers,
    ]
      .map((part) => String(part).trim().toLowerCase())
      .join("|");
    return `candidate:${encodeURIComponent(composite)}`;
  }
  return `unresolved:${crypto.randomUUID()}`;
}

function isProvisionalCatalogKey(key: string) {
  return key.startsWith("candidate:") || key.startsWith("unresolved:");
}

export function shouldSearchSongCode(filters: {
  title?: string;
  publisher?: string;
  writer?: string;
}): boolean {
  return Boolean(filters.title || filters.publisher || filters.writer);
}

export function deepLinkOwnerMatchesSession(
  referencedOwner: string | undefined,
  activeOwner: string | null
): boolean {
  return !referencedOwner || referencedOwner === activeOwner;
}

export function readStoredEmail(key: string): string | null {
  const value = safeStorageGet("local", key)?.trim() || "";
  if (isEmail(value)) return value;
  if (value) safeStorageRemove("local", key);
  return null;
}

async function hydrateRowFromMlc(
  row: CatalogRow,
  headers: HeadersInit,
  artistFallback?: string
): Promise<CatalogRow> {
  if (row.raw && Object.keys(row.raw).length > 0) {
    return row;
  }

  const titleQuery = row.title || row.key;

  try {
    const songcodeResp = await fetch("/api/mlc/search/songcode", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({ title: titleQuery }),
    });
    const songcodeData = await checkedJson(songcodeResp, "Song-code hydration");
    if (songcodeData.results && songcodeData.results.length > 0) {
      const item = songcodeData.results[0];
      return {
        key: normaliseKey(item, "work"),
        title: item.workTitle || item.title || row.title || row.key,
        type: "work",
        artist: item.artist || artistFallback,
        mlcSongCode: item.mlcSongCode,
        isrc: item.isrc,
        raw: item,
      };
    }
  } catch (err) {
    console.warn("[RightsConsole] Songcode hydration failed", err);
  }

  try {
    const recordingsResp = await fetch("/api/mlc/search/recordings", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({ artist: artistFallback, title: titleQuery }),
    });
    const recordingsData = await checkedJson(recordingsResp, "Recording hydration");
    if (recordingsData.results && recordingsData.results.length > 0) {
      const item = recordingsData.results[0];
      return {
        key: normaliseKey(item, "recording"),
        title: item.title || row.title || row.key,
        type: "recording",
        artist: item.artist || artistFallback,
        mlcSongCode: item.mlcSongCode || item.mlcsongCode,
        isrc: item.isrc,
        raw: item,
      };
    }
  } catch (err) {
    console.warn("[RightsConsole] Recordings hydration failed", err);
  }

  return row;
}

export function App() {
  const [identityGeneration, setIdentityGeneration] = React.useState(0);
  return <SessionConsole key={identityGeneration} onIdentityReset={() => setIdentityGeneration(value => value + 1)} />;
}

function SessionConsole({ onIdentityReset }: { onIdentityReset: () => void }) {
  const [view, setView] = React.useState<"catalog" | "detail" | "dashboard">(
    "catalog"
  );
  const [selectedRow, setSelectedRow] = React.useState<CatalogRow | null>(null);
  const [ownerEmail, setOwnerEmail] = React.useState<string | null>(() =>
    readStoredEmail("rc.ownerEmail")
  );
  const [userEmail, setUserEmail] = React.useState<string | null>(() =>
    readStoredEmail("rc.userEmail")
  );
  const [userRole, setUserRole] = React.useState<UserRole>(
    () => parseUserRole(safeStorageGet("local", "rc.role"))
  );
  // const [intentResult, setIntentResult] = React.useState<IntentResult | null>(null)
  const [filters, setFilters] = React.useState({
    artist: "",
    title: "",
    publisher: "",
    writer: "",
  });
  const [results, setResults] = React.useState<CatalogRow[]>([]);
  const [loadingResults, setLoadingResults] = React.useState(false);
  const [selectedKeys, setSelectedKeys] = React.useState<string[]>([]);
  const [drawerData, setDrawerData] = React.useState<{
    contract: any;
    matrix: any;
    version: number;
  } | null>(null);
  const [drawerRecordKey, setDrawerRecordKey] = React.useState<string | null>(null);
  const [drawerLoading, setDrawerLoading] = React.useState(false);
  const drawerRequestIdRef = React.useRef(0);
  const searchRequestIdRef = React.useRef(0);
  React.useEffect(() => () => {
    drawerRequestIdRef.current += 1;
    searchRequestIdRef.current += 1;
  }, []);
  const [bulkOpen, setBulkOpen] = React.useState(false);
  const [toast, setToast] = React.useState<string | null>(null);
  const [catalogMode, setCatalogMode] = React.useState<"external" | "managed">(
    "external"
  );
  const [integrationStatus, setIntegrationStatus] = React.useState<any | null>(
    null
  );
  const deepLinkProcessedRef = React.useRef(false);
  const [pendingDeepLink, setPendingDeepLink] = React.useState<{
    row: CatalogRow;
    artistOverride?: string;
  } | null>(null);
  const [autoSearchParams, setAutoSearchParams] = React.useState<{
    artist?: string;
    title?: string;
  } | null>(null);

  const passportParams = React.useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    const viewParam = params.get("view");
    const keyParam = params.get("key");
    const ownerParam = params.get("owner") || ownerEmail;
    return {
      isPassport: viewParam === "passport" && !!keyParam && !!ownerParam,
      key: keyParam,
      owner: ownerParam,
    };
  }, [ownerEmail]);

  const apiHeaders = React.useCallback((): HeadersInit => {
    const headers: Record<string, string> = {};
    if (ownerEmail) headers["X-Owner-Email"] = ownerEmail;
    if (userEmail) headers["X-User-Email"] = userEmail;
    return headers;
  }, [ownerEmail, userEmail]);

  React.useEffect(() => {
    if (toast) {
      const id = setTimeout(() => setToast(null), 4000);
      return () => clearTimeout(id);
    }
  }, [toast]);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/integrations/status");
        const data = await checkedJson(res, "Integration status");
        if (!cancelled) setIntegrationStatus(data);
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function runSearch(customFilters?: Partial<typeof filters>) {
    if (!ownerEmail) return;
    const requestId = ++searchRequestIdRef.current;
    const merged = { ...filters, ...customFilters };
    const payloadArtist = merged.artist || undefined;
    const payloadTitle = merged.title || undefined;
    const payloadPublisher = merged.publisher || undefined;
    const payloadWriter = merged.writer || undefined;
    setFilters({
      artist: payloadArtist || "",
      title: payloadTitle || "",
      publisher: payloadPublisher || "",
      writer: payloadWriter || "",
    });
    setLoadingResults(true);
    try {
      const rows: CatalogRow[] = [];
      const payload: any = {
        title: payloadTitle,
        writer_lastname: payloadWriter,
        publisher: payloadPublisher,
      };
      if (shouldSearchSongCode({
        title: payloadTitle,
        publisher: payloadPublisher,
        writer: payloadWriter,
      })) {
        const scResp = await fetch("/api/mlc/search/songcode", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...apiHeaders(),
          },
          body: JSON.stringify(payload),
        });
        const scData = await checkedJson(scResp, "Song-code search");
        const songcodeRows = (scData.results || []).map((item: any) => ({
          key: normaliseKey(item, "work"),
          title: item.workTitle || item.title || "Untitled",
          type: "work" as const,
          artist: item.artist || item.performer || undefined,
          mlcSongCode: item.mlcSongCode,
          isrc: item.isrc,
          raw: item,
        }));
        rows.push(...songcodeRows);
      }

      // Artist-only search: Use MusicBrainz to get catalog, then query The MLC
      if (payloadArtist) {
        // If we have a title, search The MLC directly
        if (payloadTitle) {
          const recResp = await fetch("/api/mlc/search/recordings", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...apiHeaders(),
            },
            body: JSON.stringify({
              artist: payloadArtist,
              title: payloadTitle,
            }),
          });
          const recData = await checkedJson(recResp, "Recording search");
          if (recData.note && !recData.results?.length) {
          if (requestId === searchRequestIdRef.current) setToast(recData.note);
          }
          const recRows = (recData.results || []).map((item: any) => ({
            key: normaliseKey(item, "recording"),
            title: item.title || "Untitled",
            type: "recording" as const,
            artist: item.artist || item.performer || undefined,
            mlcSongCode: item.mlcSongCode || item.mlcsongCode,
            isrc: item.isrc,
            raw: item,
          }));
          rows.push(...recRows);
        } else {
          // Artist-only: Use MusicBrainz to get song titles, then query The MLC for each
          try {
            const mbResp = await fetch("/api/musicbrainz/search", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...apiHeaders(),
              },
              body: JSON.stringify({
                artist: payloadArtist,
                limit: 50, // Limit to avoid too many The MLC queries
              }),
            });
            const mbData = await checkedJson(mbResp, "MusicBrainz search");

            if (mbData.musicbrainz_enabled && mbData.results?.length > 0) {
              // Use MusicBrainz results directly, then enrich with The MLC data
              const mbRows = mbData.results.map((item: any) => ({
                key: normaliseKey({
                  ...item,
                  artist: item.artist || payloadArtist,
                  type: "recording",
                }, "recording"),
                title: item.title || "Untitled",
                type: "recording" as const,
                artist: item.artist || payloadArtist,
                mlcSongCode: undefined, // Will be enriched if The MLC query succeeds
                isrc: item.isrc,
                release: item.release,
                releaseDate: item.releaseDate,
                mbid: item.mbid,
                raw: { ...item.raw, source: "musicbrainz" },
              }));
              rows.push(...mbRows);

              // Optionally: Query The MLC for top results to get The MLC song codes
              // Limit to first 10 to avoid rate limits
              const topMbResults = mbData.results.slice(0, 10);
              for (const mbItem of topMbResults) {
                if (mbItem.title) {
                  try {
                    const mlcResp = await fetch("/api/mlc/search/recordings", {
                      method: "POST",
                      headers: {
                        "Content-Type": "application/json",
                        ...apiHeaders(),
                      },
                      body: JSON.stringify({
                        artist: payloadArtist,
                        title: mbItem.title,
                      }),
                    });
                    const mlcData = await checkedJson(mlcResp, "The MLC enrichment");
                    if (mlcData.results?.length > 0) {
                      // Update the corresponding row with The MLC data
                      const existingRow = rows.find(
                        (r) =>
                          r.mbid === mbItem.mbid ||
                          (r.title === mbItem.title &&
                            r.artist === mbItem.artist)
                      );
                      if (existingRow) {
                        const mlcResult = mlcData.results[0];
                        existingRow.mlcSongCode =
                          mlcResult.mlcSongCode || mlcResult.mlcsongCode;
                        existingRow.isrc = existingRow.isrc || mlcResult.isrc;
                        existingRow.raw = {
                          ...existingRow.raw,
                          mlc: mlcResult,
                        };
                      }
                    }
                    // Small delay to respect rate limits
                    await new Promise((resolve) => setTimeout(resolve, 200));
                  } catch (err) {
                    console.warn(
                      `The MLC enrichment failed for ${mbItem.title}:`,
                      err
                    );
                  }
                }
              }
            } else if (mbData.note) {
              if (requestId === searchRequestIdRef.current) setToast(mbData.note);
            }
          } catch (err) {
            console.error("MusicBrainz search failed:", err);
            // Fallback: Try The MLC anyway (might work for some artists)
            const recResp = await fetch("/api/mlc/search/recordings", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...apiHeaders(),
              },
              body: JSON.stringify({
                artist: payloadArtist,
                title: undefined,
              }),
            });
            const recData = await checkedJson(recResp, "Fallback recording search");
            if (recData.note && !recData.results?.length) {
              if (requestId === searchRequestIdRef.current) setToast(
                recData.note || "No results found. Try adding a song title."
              );
            }
            const recRows = (recData.results || []).map((item: any) => ({
              key: normaliseKey(item, "recording"),
              title: item.title || "Untitled",
              type: "recording" as const,
              artist: item.artist || item.performer || undefined,
              mlcSongCode: item.mlcSongCode || item.mlcsongCode,
              isrc: item.isrc,
              raw: item,
            }));
            rows.push(...recRows);
          }
        }
      }
      const dedup = new Map<string, CatalogRow>();
      rows.forEach((row, index) => {
        // Provisional matches are not identities. Keep colliding candidates
        // visible and distinct until an import assigns a durable identifier.
        const key = isProvisionalCatalogKey(row.key)
          ? `${row.key}:result:${index}`
          : row.key;
        if (!dedup.has(key)) dedup.set(key, key === row.key ? row : { ...row, key });
      });
      if (requestId !== searchRequestIdRef.current) return;
      setResults(Array.from(dedup.values()));
      setSelectedKeys([]);
      if (!rows.length) {
        setToast(
          "No catalog matches for the current filters – adjust intent or add a title fragment"
        );
      }
    } catch (err) {
      if (requestId !== searchRequestIdRef.current) return;
      console.error(err);
      setToast("Search failed; check filters or try again later");
    } finally {
      if (requestId === searchRequestIdRef.current) setLoadingResults(false);
    }
  }

  const loadDrawer = React.useCallback(
    async (row: CatalogRow, overrideArtist?: string) => {
      if (!ownerEmail) return;
      if (isProvisionalCatalogKey(row.key)) {
        setToast("Import this result to assign a durable identifier before editing rights.");
        return;
      }

      const requestId = ++drawerRequestIdRef.current;
      setDrawerLoading(true);
      setDrawerData(null);
      setDrawerRecordKey(null);
      try {
        const headers: HeadersInit = { ...apiHeaders() };
        const hydratedRow = await hydrateRowFromMlc(
          row,
          headers,
          overrideArtist
        );
        if (requestId !== drawerRequestIdRef.current) return;
        setSelectedRow(hydratedRow);

        const res = await fetch(
          `/api/rights/by-key?key=${encodeURIComponent(hydratedRow.key)}`,
          {
            headers,
          }
        );
        if (!res.ok) throw new Error("Failed to load rights contract");
        const data = await res.json();
        if (requestId !== drawerRequestIdRef.current) return;
        setDrawerRecordKey(hydratedRow.key);
        setDrawerData({
          contract: data.contract,
          matrix: data.matrix,
          version: data.version,
        });
        setView("detail");
      } catch (err) {
        if (requestId !== drawerRequestIdRef.current) return;
        console.error(err);
        setToast("Unable to load rights contract");
      } finally {
        if (requestId === drawerRequestIdRef.current) {
          setDrawerLoading(false);
        }
      }
    },
    [apiHeaders, ownerEmail]
  );

  async function saveContract(contract: any) {
    if (!ownerEmail || !selectedRow || !drawerRecordKey || drawerLoading) return false;
    if (drawerRecordKey !== selectedRow.key) {
      throw new Error("The displayed policy no longer matches the selected work");
    }
    const editorGeneration = drawerRequestIdRef.current;
    const res = await fetch("/api/rights/save", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...apiHeaders(),
      },
      body: JSON.stringify({
        key: drawerRecordKey,
        artist: ownerEmail,
        contract,
        expected_version: drawerData?.version ?? 0,
      }),
    });
    if (editorGeneration !== drawerRequestIdRef.current) return false;
    if (!res.ok) {
      if (res.status === 409) {
        throw new Error("This policy changed in another session. Reload it before saving.");
      }
      throw new Error(`Save failed (${res.status})`);
    }
    const data = await res.json();
    if (editorGeneration !== drawerRequestIdRef.current) return false;
    setDrawerData({
      contract: data.contract,
      matrix: data.matrix,
      version: data.version,
    });
    setToast("Rights saved");
    // refresh results list with latest matrix info if present
    setResults((prev) =>
      prev.map((r) => (r.key === drawerRecordKey ? { ...r } : r))
    );
    return true;
  }

  function closeDrawer() {
    drawerRequestIdRef.current += 1;
    setDrawerLoading(false);
    setDrawerData(null);
    setDrawerRecordKey(null);
    setSelectedRow(null);
    setView("catalog");
  }

  function switchCatalogMode(mode: "external" | "managed") {
    searchRequestIdRef.current += 1;
    closeDrawer();
    setResults([]);
    setSelectedKeys([]);
    setLoadingResults(false);
    setCatalogMode(mode);
  }

  async function applyBulk({ changes, note }: any) {
    if (!ownerEmail || !selectedKeys.length) return;
    const durableKeys = selectedKeys.filter((key) => !isProvisionalCatalogKey(key));
    if (durableKeys.length !== selectedKeys.length) {
      setToast("Import every selected result before editing rights.");
      return;
    }
    try {
      const res = await fetch("/api/rights/bulk-update", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...apiHeaders(),
        },
        body: JSON.stringify({ keys: durableKeys, changes, note }),
      });
      if (!res.ok) throw new Error("Bulk update failed");
      await res.json();
      setToast("Bulk changes applied");
      setBulkOpen(false);
      setSelectedKeys([]);
      runSearch();
    } catch (err) {
      console.error(err);
      setToast("Bulk update failed");
    }
  }

  // No auto-login: keep core clean. Demo convenience is via explicit "Try sample catalog" action.

  // Deep-link support: ?artist=...&key=...&view=detail
  React.useEffect(() => {
    if (deepLinkProcessedRef.current) return;
    const params = new URLSearchParams(window.location.search);
    const qpView = params.get("view");

    // Passport view is handled separately - don't process as deep link
    if (qpView === "passport") return;

    const qpKey = params.get("key");
    if (!qpKey) return;

    const qpOwner = params.get("owner") || undefined;
    if (!deepLinkOwnerMatchesSession(qpOwner, ownerEmail)) {
      setToast("Open this work from an authenticated session for the referenced organization.");
      return;
    }

    const qpArtist =
      params.get("artist") || params.get("authority_name") || undefined;
    const qpTitle = params.get("title") || qpKey;
    const qpSongCode =
      params.get("mlc_song_code") || params.get("mlcSongCode") || undefined;

    const stubRow: CatalogRow = {
      key: qpKey,
      title: qpTitle,
      type: "work",
      artist: qpArtist,
      mlcSongCode: qpSongCode,
      raw: {
        workTitle: qpTitle,
        title: qpTitle,
        artist: qpArtist,
        mlcSongCode: qpSongCode,
      },
    };

    setPendingDeepLink({ row: stubRow, artistOverride: qpArtist });
    setAutoSearchParams({ artist: qpArtist, title: qpTitle });
    if (qpView === "detail" || !qpView) {
      setView("detail");
    }

    deepLinkProcessedRef.current = true;
  }, [ownerEmail]);

  React.useEffect(() => {
    if (!pendingDeepLink) return;
    if (!ownerEmail) return;
    loadDrawer(pendingDeepLink.row, pendingDeepLink.artistOverride);
    setPendingDeepLink(null);
    setView("detail");
  }, [pendingDeepLink, ownerEmail, loadDrawer]);

  React.useEffect(() => {
    if (!autoSearchParams) return;
    if (!ownerEmail) return;
    runSearch({
      artist: autoSearchParams.artist || "",
      title: autoSearchParams.title || "",
    });
    setAutoSearchParams(null);
  }, [autoSearchParams, ownerEmail]);

  return (
    <div id="rights-console-app" className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              Clef Rights Console
            </h1>
            {passportParams.isPassport && (
              <div className="mt-1 text-xs text-gray-500">
                Public rights passport view
              </div>
            )}
            {integrationStatus && !passportParams.isPassport && (
              <div className="mt-1 flex flex-wrap gap-2 text-xs">
                {["mlc", "musicbrainz", "openrouter_intent"].map((k) => {
                  const s = integrationStatus[k]?.status || "unknown";
                  const cls =
                    s === "live"
                      ? "bg-green-100 text-green-800"
                      : s === "degraded"
                      ? "bg-yellow-100 text-yellow-800"
                      : "bg-gray-100 text-gray-700";
                  return (
                    <span
                      key={k}
                      className={`px-2 py-1 rounded ${cls}`}
                      id={`rc-integration-${k}`}
                      title="Integration status (live/degraded/mock)"
                    >
                      {k}: {s}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
          <div className="flex gap-2 items-center">
            {/* Show back link in passport view */}
            {passportParams.isPassport && (
              <a
                href="/"
                className="px-3 py-2 text-sm text-blue-600 hover:underline"
                id="rc-passport-back"
              >
                Back to console
              </a>
            )}
            {/* Hide nav buttons in passport view for cleaner public display */}
            {ownerEmail && userEmail && !passportParams.isPassport && (
              <>
                <button
                  className={`px-4 py-2 rounded-lg text-sm font-medium ${
                    view === "catalog"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                  }`}
                  onClick={() => setView("catalog")}
                >
                  Catalog
                </button>
                <button
                  className={`px-4 py-2 rounded-lg text-sm font-medium ${
                    view === "dashboard"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                  }`}
                  onClick={() => setView("dashboard")}
                  id="rc-nav-dashboard"
                >
                  Dashboard
                </button>
              </>
            )}
            {ownerEmail && userEmail && !passportParams.isPassport && (
              <>
                <span
                  className="px-3 py-2 text-xs text-gray-500 border-l border-gray-200 ml-2"
                  id="rc-role-badge"
                  title={ROLE_INFO[userRole].description}
                >
                  {ROLE_INFO[userRole].icon} {ROLE_INFO[userRole].label}
                </span>
                <button
                  className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200"
                  onClick={() => {
                    safeStorageRemove("local", "rc.ownerEmail");
                    safeStorageRemove("local", "rc.userEmail");
                    safeStorageRemove("local", "rc.role");
                    setOwnerEmail(null);
                    setUserEmail(null);
                    setUserRole("publisher");
                    onIdentityReset();
                  }}
                  id="rc-logout"
                  title="Sign out"
                >
                  Sign out
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-6 space-y-6">
        {passportParams.isPassport &&
          passportParams.key &&
          passportParams.owner && (
            <RightsPassportPage
              ownerEmail={passportParams.owner}
              keyId={passportParams.key}
            />
          )}

        {passportParams.isPassport ? null : (
          <>
            {(!ownerEmail || !userEmail) && (
              <UserGate
                onConfirm={({ ownerEmail, userEmail, role }) => {
                  setOwnerEmail(ownerEmail);
                  setUserEmail(userEmail);
                  setUserRole(role);
                  setToast(
                    `Signed in as ${ROLE_INFO[role].label}. You can now seed a sample catalog or search.`
                  );
                }}
              />
            )}

            {ownerEmail && userEmail && view === "dashboard" && (
              <DashboardPage headers={apiHeaders} />
            )}

            {(view === "catalog" || view === "detail") && (
              <>
                {ownerEmail && userEmail && (
                  <section className="bg-white rounded-lg shadow-sm p-4">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div>
                        <div className="text-sm font-semibold text-gray-700">
                          {userRole === "cmo"
                            ? "Review Mode"
                            : userRole === "artist"
                            ? "View Mode"
                            : "Catalog Mode"}
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5">
                          {catalogMode === "external"
                            ? userRole === "cmo"
                              ? "Search The MLC/MusicBrainz to find and verify works"
                              : userRole === "artist"
                              ? "Search public catalogs to find your works"
                              : "Search The MLC/MusicBrainz to import works"
                            : userRole === "cmo"
                            ? "Browse registered works and verify rights declarations"
                            : userRole === "artist"
                            ? "View your registered works and royalty splits"
                            : "Browse your catalog and configure licensing terms"}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button
                          id="rc-mode-external"
                          className={`px-3 py-2 rounded-lg text-sm font-medium ${
                            catalogMode === "external"
                              ? "bg-blue-600 text-white"
                              : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                          }`}
                          onClick={() => switchCatalogMode("external")}
                        >
                          {userRole === "cmo"
                            ? "Public Registries"
                            : userRole === "artist"
                            ? "Find My Works"
                            : "Import from The MLC"}
                        </button>
                        <button
                          id="rc-mode-managed"
                          className={`px-3 py-2 rounded-lg text-sm font-medium ${
                            catalogMode === "managed"
                              ? "bg-blue-600 text-white"
                              : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                          }`}
                          onClick={() => switchCatalogMode("managed")}
                        >
                          {userRole === "cmo"
                            ? "Under Review"
                            : userRole === "artist"
                            ? "My Works"
                            : "My Catalog"}
                        </button>
                        {catalogMode === "managed" && (
                          <button
                            id="rc-reset-catalog"
                            className="ml-2 px-3 py-2 text-xs text-red-600 hover:text-red-800 hover:bg-red-50 rounded-lg"
                            onClick={async () => {
                              if (!confirm("Reset catalog to default sample data? This removes any custom entries.")) return;
                              try {
                                const response = await fetch("/api/catalog/reset-sample", {
                                  method: "POST",
                                  headers: apiHeaders(),
                                });
                                if (!response.ok) throw new Error(`Reset failed (${response.status})`);
                                setResults([]);
                                setToast("Catalog reset. Click 'Load sample' to re-seed.");
                              } catch {
                                setToast("Failed to reset catalog");
                              }
                            }}
                            title="Remove all catalog items and start fresh"
                          >
                            Reset
                          </button>
                        )}
                      </div>
                    </div>
                  </section>
                )}

                {ownerEmail &&
                  userEmail &&
                  catalogMode === "managed" && (
                    <ManagedCatalogPage
                      headers={apiHeaders}
                      onResults={(rows) => {
                        setResults(rows);
                        setSelectedKeys([]);
                      }}
                    />
                  )}

                {ownerEmail &&
                  userEmail &&
                  catalogMode === "external" && (
                    <section className="bg-white rounded-lg shadow-sm p-4">
                      <div className="mb-3 flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-gray-700">
                          {userRole === "cmo"
                            ? "Search Public Registries"
                            : userRole === "artist"
                            ? "Find Your Works"
                            : "Search The MLC Catalog"}
                        </h3>
                        <span className="text-xs text-gray-500">
                          {userRole === "artist"
                            ? "Enter your name to find works registered to you"
                            : "Enter an artist name to browse their catalog"}
                        </span>
                        {userRole !== "artist" && (
                          <button
                            id="rc-seed-sample"
                            className="ml-auto px-3 py-1.5 text-xs bg-gray-900 text-white rounded-lg hover:bg-black"
                            onClick={async () => {
                              try {
                                const res = await fetch(
                                  "/api/catalog/seed-sample",
                                  {
                                    method: "POST",
                                    headers: apiHeaders(),
                                  }
                                );
                                const data = await res.json();
                                if (!res.ok) throw new Error(data.detail || `Seed failed (${res.status})`);
                                const total =
                                  (data.created || 0) + (data.duplicates || 0);
                                setToast(
                                  data.created
                                    ? `Seeded ${data.created} sample items — switching to ${
                                        userRole === "cmo" ? "Under Review" : "My Catalog"
                                      }`
                                    : `Sample catalog ready (${total} items) — switching to ${
                                        userRole === "cmo" ? "Under Review" : "My Catalog"
                                      }`
                                );
                                // Auto-switch to managed mode to show the seeded items
                                switchCatalogMode("managed");
                              } catch {
                                setToast("Unable to seed sample catalog");
                              }
                            }}
                          >
                            {userRole === "cmo"
                              ? "Load sample for review"
                              : "Try with sample catalog"}
                          </button>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-3">
                        <div className="flex flex-col">
                          <label
                            className="text-xs text-gray-600 mb-1"
                            title="Performer on the recording (fictional examples only in demo mode)"
                          >
                            Artist (Performer) ℹ️
                          </label>
                          <input
                            id="rc-search-artist"
                            className="px-3 py-2 border border-gray-300 rounded-lg"
                            placeholder="Northlight Assembly"
                            value={filters.artist}
                            onChange={(e) =>
                              setFilters((prev) => ({
                                ...prev,
                                artist: e.target.value,
                              }))
                            }
                            onKeyDown={(e) => e.key === "Enter" && runSearch()}
                          />
                        </div>
                        <div className="flex flex-col">
                          <label className="text-xs text-gray-600 mb-1">
                            Song Title
                          </label>
                          <input
                            id="rc-search-title"
                            className="px-3 py-2 border border-gray-300 rounded-lg"
                            placeholder="Zombie"
                            value={filters.title}
                            onChange={(e) =>
                              setFilters((prev) => ({
                                ...prev,
                                title: e.target.value,
                              }))
                            }
                            onKeyDown={(e) => e.key === "Enter" && runSearch()}
                          />
                        </div>
                        <div className="flex flex-col">
                          <label className="text-xs text-gray-600 mb-1">
                            Publisher
                          </label>
                          <input
                            id="rc-search-publisher"
                            className="px-3 py-2 border border-gray-300 rounded-lg"
                            placeholder="Universal"
                            value={filters.publisher}
                            onChange={(e) =>
                              setFilters((prev) => ({
                                ...prev,
                                publisher: e.target.value,
                              }))
                            }
                            onKeyDown={(e) => e.key === "Enter" && runSearch()}
                          />
                        </div>
                        <div className="flex flex-col">
                          <label
                            className="text-xs text-gray-600 mb-1"
                            title="Composer/writer of the song (e.g., 'O'Riordan', 'Swift')"
                          >
                            Songwriter (Last Name) ℹ️
                          </label>
                          <input
                            id="rc-search-writer"
                            className="px-3 py-2 border border-gray-300 rounded-lg"
                            placeholder="O'Riordan"
                            value={filters.writer}
                            onChange={(e) =>
                              setFilters((prev) => ({
                                ...prev,
                                writer: e.target.value,
                              }))
                            }
                            onKeyDown={(e) => e.key === "Enter" && runSearch()}
                          />
                        </div>
                        <div className="flex flex-col justify-end">
                          <button
                            id="rc-search-button"
                            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                            onClick={() => runSearch()}
                          >
                            Search
                          </button>
                        </div>
                      </div>
                      {selectedKeys.length > 0 && (
                        <button
                          className="px-4 py-2 bg-black text-white rounded-lg"
                          onClick={() => setBulkOpen(true)}
                        >
                          Bulk edit ({selectedKeys.length})
                        </button>
                      )}
                    </section>
                  )}

                {ownerEmail && userEmail && (
                  <ResultsTable
                    rows={results}
                    selected={selectedKeys}
                    loading={loadingResults}
                    userRole={userRole}
                    onToggle={(key) =>
                      setSelectedKeys((prev) =>
                        prev.includes(key)
                          ? prev.filter((k) => k !== key)
                          : [...prev, key]
                      )
                    }
                    onOpenDrawer={(row) => loadDrawer(row)}
                    onLoadSample={async () => {
                      try {
                        const res = await fetch("/api/catalog/seed-sample", {
                          method: "POST",
                          headers: apiHeaders(),
                        });
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.detail || `Seed failed (${res.status})`);
                        setToast(
                          data.created
                            ? `Loaded ${data.created} sample items`
                            : `Sample catalog ready (${(data.created || 0) + (data.duplicates || 0)} items)`
                        );
                        switchCatalogMode("managed");
                      } catch {
                        setToast("Unable to load sample catalog");
                      }
                    }}
                    onSwitchToExternal={() => switchCatalogMode("external")}
                  />
                )}
              </>
            )}
          </>
        )}
      </main>

      {ownerEmail && userEmail && selectedRow && view === "detail" && (
        <RightsDrawer
          key={selectedRow.key}
          row={selectedRow}
          data={drawerData}
          loading={drawerLoading}
          onClose={closeDrawer}
          onSave={saveContract}
        />
      )}

      <BulkEditModal
        open={Boolean(ownerEmail && userEmail && bulkOpen)}
        onClose={() => setBulkOpen(false)}
        onApply={applyBulk}
        selectedCount={selectedKeys.length}
      />

      {toast && (
        <div
          className="fixed bottom-6 right-6 bg-gray-900 text-white px-4 py-3 rounded-lg shadow-lg text-sm"
          id="rc-toast"
        >
          {toast}
        </div>
      )}
    </div>
  );
}
