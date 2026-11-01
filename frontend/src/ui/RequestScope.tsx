import React from "react";

export const LEGACY_AI_USAGE_KEYS = ["ai_training_recursive"] as const;

export const AI_USAGE_KEYS = [
  "ai_model_training",
  "ai_model_fine_tuning",
  "ai_grounded_generation",
  "ai_embedding_creation",
  "ai_embedding_retrieval",
  "ai_source_separation",
  "ai_music_transformation",
  "ai_lyric_analysis",
  "ai_lyric_generation",
  "ai_synthetic_voice",
] as const;

export const ALL_AI_USAGE_KEYS = [...AI_USAGE_KEYS, ...LEGACY_AI_USAGE_KEYS] as const;

export function isAiUsageKey(usage: string): boolean {
  return (ALL_AI_USAGE_KEYS as readonly string[]).includes(usage);
}

export const AI_INPUT_KEYS = ["full_mix", "stems", "isolated_vocals", "lyrics", "composition_data", "reference_embeddings"] as const;
export const AI_MODEL_SCOPE_KEYS = ["private_single_tenant", "shared_commercial_model", "public_or_open_weights"] as const;
export const AI_SAFEGUARD_KEYS = ["provenanceReceipt", "outputWatermark", "attribution", "similarityReview", "deletionAttestation"] as const;

export const RESTRICTION_KEYS = [
  "political",
  "adult",
  "alcohol_tobacco_cannabis",
  "weapons_defense",
  "gambling",
  "religion",
  "sensitive_social_issues",
  "health_pharma",
  "children_sensitive",
  "likeness_voice_clone",
  "deceptive_endorsement",
] as const;

const DECLARED_LIMITS = { sourceDurationSeconds: "Source duration used (seconds)", outputDurationSeconds: "Maximum output duration (seconds)", lyricCharacters: "Lyric characters supplied", sourceRetentionDays: "Source retention (days)", embeddingRetentionDays: "Embedding retention (days)" };

export type RequestScope = {
  releaseTitle: string;
  restrictionCategories: string[];
  contentConfirmed: boolean;
  inputAssets: string[];
  modelScope: string;
  aiLimits: Record<string, string>;
  acceptedSafeguards: string[];
};
type ListField = "restrictionCategories" | "inputAssets" | "acceptedSafeguards";
type PublishedStates = Record<string, string | number | boolean | null>;

export function initialRequestScope(): RequestScope {
  return { releaseTitle: "", restrictionCategories: [], contentConfirmed: false, inputAssets: ["full_mix"], modelScope: "private_single_tenant",
    aiLimits: Object.fromEntries(Object.keys(DECLARED_LIMITS).map((key) => [key, ""])), acceptedSafeguards: [] };
}

/** The request `context` both the local and federated request endpoints evaluate against the published policy. */
export function requestScopeContext(scope: RequestScope, usage: string) {
  const aiUse = isAiUsageKey(usage) ? {
    inputAssets: scope.inputAssets,
    modelScope: scope.modelScope,
    acceptedSafeguards: scope.acceptedSafeguards,
    ...Object.fromEntries(Object.entries(scope.aiLimits).map(([key, value]) => [key, value === "" ? null : Number(value)])),
  } : undefined;
  return { releaseTitle: scope.releaseTitle, restrictionCategories: scope.restrictionCategories, ...(aiUse ? { aiUse } : {}) };
}

export function requestScopeComplete(scope: RequestScope, usage: string, requiredSafeguards: readonly string[]): boolean {
  return scope.contentConfirmed && (!isAiUsageKey(usage) || (scope.inputAssets.length > 0 && requiredSafeguards.every((item) => scope.acceptedSafeguards.includes(item))));
}

const stateText = (state: PublishedStates[string] | undefined) => state === undefined || state === null ? "" : String(state).replace(/_/g, " ");

export function RequestScopeFields({ usage, value, onChange, label, requiredSafeguards, policy }: {
  usage: string;
  value: RequestScope;
  onChange: React.Dispatch<React.SetStateAction<RequestScope>>;
  label: (key: string) => string;
  requiredSafeguards: readonly string[];
  /** Published states shown beside each choice, when the source policy is known. */
  policy?: { restrictions?: PublishedStates; inputs?: PublishedStates; modelScopes?: PublishedStates };
}) {
  function toggle(field: ListField, item: string) {
    onChange((current) => ({
      ...current,
      [field]: current[field].includes(item) ? current[field].filter((existing) => existing !== item) : [...current[field], item],
      ...(field === "restrictionCategories" ? { contentConfirmed: false } : {}),
    }));
  }
  return <>
    <input aria-label="Proposed release or project title" value={value.releaseTitle} onChange={(event) => onChange((current) => ({ ...current, releaseTitle: event.target.value }))} className="request-scope-title w-full rounded-xl border border-slate-300 px-3 py-2" placeholder="Proposed release or project title" />
    {isAiUsageKey(usage) && <section className="request-scope-ai space-y-4 rounded-2xl border border-blue-200 bg-blue-50/40 p-4"><div><h3 className="font-medium text-slate-950">Declare the AI system’s exact use</h3><p className="mt-1 text-sm text-slate-600">Grounded generation and embeddings are licensed operations, not incidental technical details. Declare every source asset and retention period.</p></div>
      <fieldset><legend className="text-sm font-medium text-slate-800">Source materials entering the system</legend><div className="request-scope-options mt-2 grid gap-2 sm:grid-cols-3">{AI_INPUT_KEYS.map((asset) => <label key={asset} className="request-scope-option flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 text-sm"><input type="checkbox" checked={value.inputAssets.includes(asset)} onChange={() => toggle("inputAssets", asset)} />{label(asset)}{policy?.inputs && <span className="request-scope-state text-slate-500">({stateText(policy.inputs[asset])})</span>}</label>)}</div></fieldset>
      <label className="block text-sm font-medium text-slate-800">Model environment<select value={value.modelScope} onChange={(event) => onChange((current) => ({ ...current, modelScope: event.target.value }))} className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2">{AI_MODEL_SCOPE_KEYS.map((scope) => <option key={scope} value={scope}>{policy?.modelScopes ? `${label(scope)} (${stateText(policy.modelScopes[scope])})` : label(scope)}</option>)}</select></label>
      <div className="grid gap-3 sm:grid-cols-2">{Object.entries(DECLARED_LIMITS).map(([key, text]) => <label key={key} className="text-sm text-slate-700">{text}<input type="number" min="0" value={value.aiLimits[key]} onChange={(event) => onChange((current) => ({ ...current, aiLimits: { ...current.aiLimits, [key]: event.target.value } }))} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" placeholder="Declare or settle in license" /></label>)}</div>
      {requiredSafeguards.length > 0 && <fieldset><legend className="text-sm font-medium text-slate-800">Controls required by the published policy</legend><p className="mt-1 text-xs text-slate-600">Accepting these controls records them in the request and signed receipt; it does not claim they have already been performed.</p><div className="request-scope-options mt-2 grid gap-2 sm:grid-cols-2">{requiredSafeguards.map((safeguard) => <label key={safeguard} className="request-scope-option flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 text-sm"><input type="checkbox" checked={value.acceptedSafeguards.includes(safeguard)} onChange={() => toggle("acceptedSafeguards", safeguard)} />{label(safeguard)}</label>)}</div></fieldset>}
    </section>}
    <fieldset className="request-scope-content space-y-3 rounded-xl border border-slate-200 p-4"><legend className="px-1 font-medium text-slate-900">Content and associations</legend><p className="text-sm text-slate-600">Select every category associated with the proposed use. The artist’s published conditions apply to these choices.</p>
      <div className="request-scope-options grid gap-2 sm:grid-cols-2">{RESTRICTION_KEYS.map((category) => <label key={category} className="request-scope-option flex items-start gap-2 text-sm"><input type="checkbox" checked={value.restrictionCategories.includes(category)} onChange={() => toggle("restrictionCategories", category)} />{label(category)}{policy?.restrictions && <span className="request-scope-state text-slate-500">({stateText(policy.restrictions[category])})</span>}</label>)}</div>
      <label className="request-scope-option request-scope-confirm flex items-start gap-2 border-t border-slate-200 pt-3 text-sm"><input required type="checkbox" checked={value.contentConfirmed} onChange={(event) => onChange((current) => ({ ...current, contentConfirmed: event.target.checked }))} />I have reviewed every category. My selections describe this use; leaving all categories clear means none apply.</label>
    </fieldset>
  </>;
}
