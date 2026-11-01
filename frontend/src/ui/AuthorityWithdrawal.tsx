import React from "react";

type Preview = { canWithdraw: boolean; expectedDigest: string; pendingRequests: number; approvedGrants: number };
type Payload = { expected_digest: string; reason: string; confirm_withdrawal: true };

export function AuthorityWithdrawal({ apiBase = "", sessionId, organizationId, claimId, onChanged }: {
  apiBase?: string; sessionId: string; organizationId: string; claimId: string; onChanged: () => Promise<void>;
}) {
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [reason, setReason] = React.useState("");
  const [confirmed, setConfirmed] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [retry, setRetry] = React.useState<Payload | null>(null);
  const [done, setDone] = React.useState(false);
  const lock = React.useRef(false);
  const generation = React.useRef(0);
  React.useEffect(() => () => { generation.current += 1; }, [sessionId, organizationId, claimId]);
  const base = `${apiBase}/v1/organizations/${organizationId}/authority-claims/${claimId}`;

  async function perform(payload?: Payload) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setMessage("");
    const current = generation.current;
    try {
      const response = await fetch(`${base}/${payload ? "withdraw" : "withdrawal-preview"}`, {
        method: payload ? "POST" : "GET", headers: { "X-Session-Id": sessionId, ...(payload ? { "Content-Type": "application/json" } : {}) },
        ...(payload ? { body: JSON.stringify(payload) } : {}),
      });
      if (current !== generation.current) return;
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) {
          setRetry(null);
          if (response.status === 409) { setPreview(null); setConfirmed(false); }
        }
        const error = await response.json().catch(() => ({}));
        throw new Error(typeof error.detail === "string" ? error.detail : `Request failed (${response.status}).`);
      }
      const result = await response.json();
      if (current !== generation.current) return;
      if (payload) {
        setDone(true); setRetry(null); setMessage("Authority withdrawn. Review any existing grants in the Permission ledger.");
        try { await onChanged(); }
        catch { if (current === generation.current) setMessage("Authority withdrawn. Reload the authority list to see its current status."); }
      } else { setPreview(result); setConfirmed(false); }
    } catch (error) {
      if (current === generation.current) setMessage(error instanceof Error ? error.message : "The request could not be completed.");
    } finally { if (current === generation.current) { lock.current = false; setBusy(false); } }
  }

  return <div className="mt-3 border-t border-slate-200 pt-3">
    {!done && !preview && <button type="button" disabled={busy} onClick={() => void perform()} className="text-sm font-medium text-blue-800 disabled:opacity-40">Review withdrawal</button>}
    {!done && preview && <div className="space-y-3 text-sm text-slate-700">
      <p>Withdrawing this authority stops new permissions and approval of {preview.pendingRequests} pending {preview.pendingRequests === 1 ? "request" : "requests"}, and removes its connected-catalog listing.</p>
      <p>Issued grants: {preview.approvedGrants}. Each keeps its signed history. Review each grant in the Permission ledger if its terms require a separate action.</p>
      {preview.canWithdraw ? <>
        <label className="block">Reason for withdrawal<textarea aria-label="Reason for authority withdrawal" maxLength={2000} disabled={busy || !!retry} value={reason} onChange={event => setReason(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 p-2" /></label>
        <label className="flex items-start gap-2"><input type="checkbox" disabled={busy || !!retry} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I confirm this organization is withdrawing this authority assertion.</label>
        <button type="button" disabled={busy || (!retry && (!confirmed || !reason.trim()))} onClick={() => {
          const payload = retry || { expected_digest: preview.expectedDigest, reason: reason.trim(), confirm_withdrawal: true as const };
          setRetry(payload); void perform(payload);
        }} className="rounded-lg bg-red-800 px-3 py-2 font-medium text-white disabled:opacity-40">{retry ? "Retry withdrawal" : "Withdraw authority"}</button>
        {retry && <p>Retry checks the same withdrawal if the previous response was interrupted.</p>}
      </> : <p>This record is already closed. Its history remains available.</p>}
    </div>}
    {message && <p role="status" className="mt-3 text-sm text-slate-700">{message}</p>}
  </div>;
}
