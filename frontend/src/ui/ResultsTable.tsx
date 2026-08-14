import React from "react";
import type { UserRole } from "./UserGate";

export type CatalogRow = {
  key: string;
  title: string;
  type: "recording" | "work";
  artist?: string;
  mlcSongCode?: string;
  isrc?: string;
  mbid?: string; // MusicBrainz ID
  release?: string; // Album/release title
  releaseDate?: string; // Release date
  headlineStatus?: "allowed" | "requires_approval" | "blocked";
  aiGenStatus?: "allowed" | "requires_approval" | "blocked";
  approvalWindowDays?: number;
  raw: any;
};

type Props = {
  rows: CatalogRow[];
  selected: string[];
  onToggle: (key: string) => void;
  onOpenDrawer: (row: CatalogRow) => void;
  loading?: boolean;
  userRole?: UserRole;
  onLoadSample?: () => void;
  onSwitchToExternal?: () => void;
};

export function ResultsTable({
  rows,
  selected,
  onToggle,
  onOpenDrawer,
  loading,
  userRole = "publisher",
  onLoadSample,
  onSwitchToExternal,
}: Props) {
  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-sm p-6 text-gray-500">
        Loading results…
      </div>
    );
  }

  if (!rows.length) {
    // Role-specific welcome content
    const welcomeContent = {
      cmo: {
        title: "Ready to review catalogs",
        description: "As a CMO, you can verify rights declarations from publishers and ensure compliance across your territory.",
        steps: [
          "Load a fictional sample catalog",
          "Review AI training permissions and usage restrictions",
          "Verify rights declarations match registered works",
        ],
        primaryAction: "Load sample catalog",
        secondaryAction: "Search public registries",
      },
      publisher: {
        title: "Configure your catalog rights",
        description: "Import works from MLC or MusicBrainz, then configure AI training permissions, licensing terms, and usage restrictions.",
        steps: [
          "Import works from external registries or load sample data",
          "Configure usage permissions (streaming, sync, AI training)",
          "Set pricing and approval workflows",
        ],
        primaryAction: "Load sample catalog",
        secondaryAction: "Import from MLC",
      },
      artist: {
        title: "View your registered works",
        description: "See how your music is registered, check your royalty splits, and understand how your works can be used.",
        steps: [
          "Search for your works in public catalogs",
          "View current licensing terms and restrictions",
          "Check AI training and derivative permissions",
        ],
        primaryAction: "Load sample works",
        secondaryAction: "Find my works",
      },
    };

    const content = welcomeContent[userRole];

    return (
      <div id="rc-welcome-card" className="bg-white rounded-lg shadow-sm p-8">
        <div className="max-w-2xl mx-auto text-center">
          <div className="text-4xl mb-4">
            {userRole === "cmo" ? "🏛️" : userRole === "artist" ? "🎵" : "📋"}
          </div>
          <h2 className="text-xl font-semibold text-gray-900 mb-2">
            {content.title}
          </h2>
          <p className="text-gray-600 mb-6">{content.description}</p>

          <div className="bg-gray-50 rounded-lg p-4 mb-6 text-left">
            <div className="text-sm font-medium text-gray-700 mb-2">
              Getting started:
            </div>
            <ol className="text-sm text-gray-600 space-y-1">
              {content.steps.map((step, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="text-blue-600 font-medium">{i + 1}.</span>
                  {step}
                </li>
              ))}
            </ol>
          </div>

          <div className="flex justify-center gap-3">
            {onLoadSample && (
              <button
                id="rc-welcome-load-sample"
                className="px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
                onClick={onLoadSample}
              >
                {content.primaryAction}
              </button>
            )}
            {onSwitchToExternal && (
              <button
                id="rc-welcome-search"
                className="px-5 py-2.5 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium"
                onClick={onSwitchToExternal}
              >
                {content.secondaryAction}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  const showStatus = rows.some((r) => !!r.headlineStatus);
  const showAiGen = rows.some((r) => !!r.aiGenStatus);

  return (
    <div className="bg-white rounded-lg shadow-sm overflow-x-auto">
      <table
        id="rc-results-table"
        className="min-w-full divide-y divide-gray-200"
      >
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Select
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Title
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Artist
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Type
            </th>
            {showStatus && (
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
            )}
            {showAiGen && (
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider" title="Combined AI/Generative protection: training, derivatives, voice cloning">
                AI/Gen
              </th>
            )}
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              MLC Song Code
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              ISRC
            </th>
            <th className="px-4 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {rows.map((row) => {
            const isSelected = selected.includes(row.key);
            const isProvisional = row.key.startsWith("candidate:") || row.key.startsWith("unresolved:");
            return (
              <tr
                key={row.key}
                data-mlc-song-code={row.mlcSongCode || ""}
                className="hover:bg-gray-50"
              >
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    className="rc-row-select"
                    checked={isSelected}
                    disabled={isProvisional}
                    title={isProvisional ? "Import this result before editing rights" : undefined}
                    onChange={() => onToggle(row.key)}
                  />
                </td>
                <td className="px-4 py-3 text-sm font-medium text-gray-900">
                  {row.title}
                </td>
                <td className="px-4 py-3 text-sm text-gray-500">
                  {row.artist || "—"}
                </td>
                <td className="px-4 py-3 text-sm text-gray-500">{row.type}</td>
                {showStatus && (
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {row.headlineStatus ? (
                      <span
                        className={`text-xs px-2 py-1 rounded ${
                          row.headlineStatus === "allowed"
                            ? "bg-green-100 text-green-800"
                            : row.headlineStatus === "requires_approval"
                            ? "bg-yellow-100 text-yellow-800"
                            : "bg-red-100 text-red-800"
                        }`}
                        title={
                          row.headlineStatus === "requires_approval" &&
                          row.approvalWindowDays
                            ? `Approval window: ${row.approvalWindowDays} days`
                            : undefined
                        }
                      >
                        {row.headlineStatus === "allowed"
                          ? "Allowed"
                          : row.headlineStatus === "requires_approval"
                          ? "Approval"
                          : "Blocked"}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                )}
                {showAiGen && (
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {row.aiGenStatus ? (
                      <span
                        className={`text-xs px-2 py-1 rounded ${
                          row.aiGenStatus === "allowed"
                            ? "bg-green-100 text-green-800"
                            : row.aiGenStatus === "requires_approval"
                            ? "bg-yellow-100 text-yellow-800"
                            : "bg-red-100 text-red-800"
                        }`}
                        title="Combined: AI training, derivatives, voice cloning"
                      >
                        {row.aiGenStatus === "allowed"
                          ? "Allowed"
                          : row.aiGenStatus === "requires_approval"
                          ? "Approval"
                          : "Blocked"}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                )}
                <td className="px-4 py-3 text-sm text-gray-500">
                  {row.mlcSongCode || "—"}
                </td>
                <td className="px-4 py-3 text-sm text-gray-500">
                  {row.isrc || "—"}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    className="text-sm text-blue-600 hover:underline disabled:cursor-not-allowed disabled:text-gray-400 disabled:no-underline"
                    disabled={isProvisional}
                    title={isProvisional ? "Import this result to assign a durable identifier" : undefined}
                    onClick={() => onOpenDrawer(row)}
                  >
                    {isProvisional ? "Import required" : "View details"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
