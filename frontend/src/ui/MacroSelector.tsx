import React from "react";
import { RIGHTS_MACROS, RightsMacro } from "../types/macros";

interface Props {
  artistName?: string;
  onSelectMacro: (macro: RightsMacro) => void;
  onAIRecommend: () => void;
  aiLoading?: boolean;
}

export function MacroSelector({
  artistName,
  onSelectMacro,
  onAIRecommend,
  aiLoading,
}: Props) {
  const [expanded, setExpanded] = React.useState(false);
  const [remoteMacros, setRemoteMacros] = React.useState<RightsMacro[] | null>(
    null
  );
  const [remoteVersion, setRemoteVersion] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/macros/list");
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        if (Array.isArray(data.macros)) {
          // Remote macros are display metadata only. Resolve every selection to a
          // complete, locally validated matrix before it can mutate a policy.
          const resolved = data.macros.flatMap((remote: Partial<RightsMacro>) => {
            const local = RIGHTS_MACROS.find((candidate) => candidate.id === remote.id);
            if (!local) return [];
            return [
              {
                ...local,
                name: remote.name || local.name,
                description: remote.description || local.description,
                tags: Array.isArray(remote.tags) ? remote.tags : local.tags,
                usageExamples: remote.usageExamples || local.usageExamples,
              },
            ];
          });
          setRemoteMacros(resolved.length ? resolved : null);
          setRemoteVersion(data.version || null);
        }
      } catch {
        // silent fallback to local macros
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const macros = remoteMacros || RIGHTS_MACROS;

  return (
    <section id="rc-macro-selector" className="border-b border-gray-200 pb-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-baseline gap-2">
          <h3 className="text-sm font-semibold text-gray-700">
            Quick Templates
          </h3>
          {remoteVersion && (
            <span className="text-[11px] text-gray-400" id="rc-macro-version">
              v{remoteVersion}
            </span>
          )}
        </div>
        <button
          id="rc-macro-ai-recommend"
          className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
            aiLoading
              ? "bg-purple-200 text-purple-600 cursor-not-allowed"
              : "bg-purple-600 text-white hover:bg-purple-700"
          }`}
          onClick={onAIRecommend}
          disabled={aiLoading}
        >
          {aiLoading ? "🤖 Analyzing…" : "🤖 AI Recommend"}
        </button>
      </div>

      <div className="space-y-2">
        {macros.slice(0, expanded ? undefined : 3).map((macro) => (
          <button
            key={macro.id}
            id={`rc-macro-${macro.id}`}
            className="w-full text-left border border-gray-200 rounded-lg p-3 hover:border-blue-400 hover:bg-blue-50 transition-colors"
            onClick={() => onSelectMacro(macro)}
          >
            <div className="font-medium text-sm text-gray-900">
              {macro.name}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {macro.description}
            </div>
            {macro.usageExamples &&
              Object.keys(macro.usageExamples).length > 0 && (
                <div className="mt-2 text-[11px] text-gray-500">
                  <span className="font-medium text-gray-600">Examples:</span>{" "}
                  {Object.values(macro.usageExamples).slice(0, 2).join(" • ")}
                </div>
              )}
          </button>
        ))}
      </div>

      {!expanded && macros.length > 3 && (
        <button
          id="rc-macro-expand"
          className="mt-2 text-xs text-blue-600 hover:text-blue-700 font-medium"
          onClick={() => setExpanded(true)}
        >
          Show {macros.length - 3} more templates →
        </button>
      )}

      {expanded && (
        <button
          id="rc-macro-collapse"
          className="mt-2 text-xs text-gray-600 hover:text-gray-700 font-medium"
          onClick={() => setExpanded(false)}
        >
          Show less ↑
        </button>
      )}
    </section>
  );
}
