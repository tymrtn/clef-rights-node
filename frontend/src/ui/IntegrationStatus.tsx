import React from "react";
import { checkedJson } from "../utils/http";

type IntegrationState = "live" | "mock" | "disabled";

type StatusResponse = {
  integrations: {
    mlc: IntegrationState;
    musicbrainz: IntegrationState;
    openrouter: IntegrationState;
  };
  mock_mode: boolean;
};

const badgeClasses = {
  live: "bg-green-100 text-green-800 border-green-200",
  mock: "bg-yellow-100 text-yellow-800 border-yellow-200",
  disabled: "bg-red-100 text-red-800 border-red-200",
};

export function IntegrationStatus() {
  const [data, setData] = React.useState<StatusResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/integrations/status");
        const json = await checkedJson<StatusResponse>(res, "Integration status");
        if (!cancelled) setData(json);
      } catch (e: any) {
        if (!cancelled) setError(e.message || "Failed to load status");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="text-xs text-red-600" title={error}>
        Integrations: error
      </div>
    );
  }

  if (!data) {
    return <div className="text-xs text-gray-500">Integrations: …</div>;
  }

  const items = [
    { name: "MLC", state: data.integrations?.mlc },
    { name: "MusicBrainz", state: data.integrations?.musicbrainz },
    { name: "Intent", state: data.integrations?.openrouter },
  ].filter((i) => i.state);

  return (
    <div className="flex items-center gap-2 text-xs text-gray-600">
      <span>Integrations:</span>
      <div className="flex gap-1 flex-wrap">
        {items.map((item) => (
          <span
            key={item.name}
            className={`px-2 py-1 rounded border ${
              badgeClasses[item.state as IntegrationState]
            }`}
            title={`Mode: ${item.state}`}
          >
            {item.name}: {item.state}
          </span>
        ))}
        {data.mock_mode && (
          <span className="px-2 py-1 rounded border bg-blue-50 text-blue-700 border-blue-200">
            Demo mode
          </span>
        )}
      </div>
    </div>
  );
}
