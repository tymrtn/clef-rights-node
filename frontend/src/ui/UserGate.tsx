import React from "react";
import { t } from "../utils/i18n";
import { safeStorageGet, safeStorageSet } from "../utils/storage";

export type UserRole = "cmo" | "publisher" | "artist";

export function parseUserRole(value: string | null | undefined): UserRole {
  return value === "cmo" || value === "publisher" || value === "artist"
    ? value
    : "publisher";
}

export function isEmail(value: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value);
}

// Role metadata for UI display
export const ROLE_INFO: Record<
  UserRole,
  { label: string; description: string; icon: string }
> = {
  cmo: {
    label: "CMO / PRO",
    description: "Collective management organization verifying and aggregating rights",
    icon: "🏛️",
  },
  publisher: {
    label: "Publisher / Label",
    description: "Managing catalog, licensing terms, and royalty splits",
    icon: "📋",
  },
  artist: {
    label: "Artist / Songwriter",
    description: "Viewing works, splits, and usage across platforms",
    icon: "🎵",
  },
};

// Demo presets: URL path → pre-populated credentials + role
const DEMO_PRESETS: Record<
  string,
  { owner: string; user: string; role: UserRole }
> = {
  society: { owner: "rights@society-demo.example", user: "admin@society-demo.example", role: "cmo" },
  publisher: { owner: "rights@publisher-demo.example", user: "admin@publisher-demo.example", role: "publisher" },
  artist: { owner: "catalog@artist-demo.example", user: "artist@artist-demo.example", role: "artist" },
};

function getDemoPreset(): { owner: string; user: string; role: UserRole } | null {
  const path = window.location.pathname.replace(/^\//, "").toLowerCase();
  return DEMO_PRESETS[path] || null;
}

type Props = {
  onConfirm: (payload: { ownerEmail: string; userEmail: string; role: UserRole }) => void;
};

export function UserGate({ onConfirm }: Props) {
  // URL preset takes priority over localStorage
  const preset = getDemoPreset();
  const [ownerEmail, setOwnerEmail] = React.useState(
    preset?.owner || safeStorageGet("local", "rc.ownerEmail") || ""
  );
  const [userEmail, setUserEmail] = React.useState(
    preset?.user || safeStorageGet("local", "rc.userEmail") || ""
  );
  const [role, setRole] = React.useState<UserRole>(
    preset?.role || parseUserRole(safeStorageGet("local", "rc.role"))
  );
  const [error, setError] = React.useState("");

  function confirm() {
    const owner = ownerEmail.trim();
    const user = userEmail.trim();
    if (!isEmail(owner)) {
      setError("Enter an organization email (used to scope the catalog).");
      return;
    }
    if (!isEmail(user)) {
      setError("Enter your email (used for audit trails).");
      return;
    }
    safeStorageSet("local", "rc.ownerEmail", owner);
    safeStorageSet("local", "rc.userEmail", user);
    safeStorageSet("local", "rc.role", role);
    onConfirm({ ownerEmail: owner, userEmail: user, role });
  }

  // Dynamic labels based on role
  const ownerLabel =
    role === "cmo"
      ? "Organization email"
      : role === "artist"
      ? "Catalog owner email"
      : "Publisher / Label email";
  const ownerPlaceholder =
    role === "cmo"
      ? "admin@cmo.org"
      : role === "artist"
      ? "catalog@artist.example"
      : "rights@publisher.example";
  const userPlaceholder =
    role === "cmo"
      ? "you@cmo.org"
      : role === "artist"
      ? "artist@example.com"
      : "you@publisher.example";

  return (
    <div
      id="rc-user-gate"
      className="bg-white rounded-lg shadow-sm p-6 max-w-xl"
    >
      <h2 className="text-xl font-semibold text-gray-900 mb-2">
        {t("gate.title")}
      </h2>
      <p className="text-gray-600 mb-4">
        Select your role to customize the console view, then enter your
        credentials to scope the catalog and attribute edits.
      </p>

      <div className="space-y-4">
        {/* Role selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            I am a...
          </label>
          <div className="grid grid-cols-3 gap-2">
            {(Object.keys(ROLE_INFO) as UserRole[]).map((r) => (
              <button
                key={r}
                id={`rc-role-${r}`}
                type="button"
                className={`p-3 rounded-lg border-2 text-left transition-colors ${
                  role === r
                    ? "border-blue-600 bg-blue-50"
                    : "border-gray-200 hover:border-gray-300 bg-white"
                }`}
                onClick={() => setRole(r)}
              >
                <div className="text-lg mb-1">{ROLE_INFO[r].icon}</div>
                <div className="text-sm font-medium text-gray-900">
                  {ROLE_INFO[r].label}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {ROLE_INFO[r].description}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div>
          <label
            htmlFor="rc-owner-email"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            {ownerLabel}
          </label>
          <input
            id="rc-owner-email"
            type="email"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg"
            placeholder={ownerPlaceholder}
            value={ownerEmail}
            onChange={(e) => setOwnerEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && confirm()}
          />
          <div className="text-xs text-gray-500 mt-1">
            {role === "cmo"
              ? "This scopes the catalog you're reviewing"
              : role === "artist"
              ? "The catalog where your works are registered"
              : "This identifies your organization's catalog"}
          </div>
        </div>
        <div>
          <label
            htmlFor="rc-user-email"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Your email
          </label>
          <input
            id="rc-user-email"
            type="email"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg"
            placeholder={userPlaceholder}
            value={userEmail}
            onChange={(e) => setUserEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && confirm()}
          />
          <div className="text-xs text-gray-500 mt-1">
            Used for audit trails and edit attribution
          </div>
        </div>
        <button
          id="rc-user-confirm"
          className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          onClick={confirm}
        >
          {t("gate.continue")}
        </button>
      </div>

      {error && <div className="text-red-600 text-sm mt-3">{error}</div>}
    </div>
  );
}

