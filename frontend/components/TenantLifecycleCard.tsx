"use client";

import React, { useEffect, useState } from "react";
import { Building2, ShieldAlert, CheckCircle2, Loader2, AlertCircle, Download, PauseCircle, PlayCircle, Trash2 } from "lucide-react";
import { useClientId } from "./ClientContext";

// TEN-01/TEN-02/TEN-03: tenant lifecycle management -- suspend/reactivate
// (manual, owner-only; NOT subscription-driven, since no billing exists
// yet), full data export (owner/admin), and permanent delete (owner-only,
// requires re-typing the real company name as a mistake-prevention step --
// see backend/accounts.py's TenantDeleteRequest for why this is a speed
// bump, not a security boundary; require_role_allow_suspended("owner") on
// the backend is the actual boundary).

interface TenantStatus {
  client_id: string;
  company_name: string;
  lifecycle_status: string;
  suspended_at: string | null;
  suspended_by_email: string | null;
}

function backendUrl(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
}

export default function TenantLifecycleCard() {
  const clientCtx = useClientId();
  const { authToken, authReady, refreshLifecycleStatus, logout } = clientCtx;
  const role = clientCtx.user?.role;

  const [status, setStatus] = useState<TenantStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [confirmingSuspend, setConfirmingSuspend] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleteInProgress, setDeleteInProgress] = useState(false);

  const canManageLifecycle = role === "owner";
  const canExport = role === "owner" || role === "admin";

  const loadStatus = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${backendUrl()}/api/v1/tenant/status`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (res.ok) {
        setStatus(await res.json());
      }
    } catch (err) {
      console.error("Tenant status fetch failed:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authReady) return;
    loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, authToken]);

  const handleSuspend = async () => {
    setActionPending(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await fetch(`${backendUrl()}/api/v1/tenant/suspend`, {
        method: "POST",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      setStatus(await res.json());
      await refreshLifecycleStatus();
      setConfirmingSuspend(false);
    } catch (err: any) {
      setError(err.message || "Could not suspend this tenant.");
    } finally {
      setActionPending(false);
    }
  };

  const handleReactivate = async () => {
    setActionPending(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await fetch(`${backendUrl()}/api/v1/tenant/reactivate`, {
        method: "POST",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      setStatus(await res.json());
      await refreshLifecycleStatus();
      setSuccessMsg("This tenant is active again.");
    } catch (err: any) {
      setError(err.message || "Could not reactivate this tenant.");
    } finally {
      setActionPending(false);
    }
  };

  const handleExport = async () => {
    setActionPending(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await fetch(`${backendUrl()}/api/v1/tenant/export`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const stamp = new Date().toISOString().split("T")[0];
      a.download = `${status?.client_id || "tenant"}-export-${stamp}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setSuccessMsg("Your data export has downloaded.");
    } catch (err: any) {
      setError(err.message || "Could not export this tenant's data.");
    } finally {
      setActionPending(false);
    }
  };

  const handleDelete = async () => {
    if (!status) return;
    setDeleteInProgress(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl()}/api/v1/tenant`, {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ confirm_company_name: deleteConfirmText }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      // Tenant no longer exists -- this token is dead. Sign out rather
      // than leave the app sitting on a session for a tenant that's gone.
      logout();
    } catch (err: any) {
      setError(err.message || "Could not delete this tenant.");
      setDeleteInProgress(false);
    }
  };

  const isSuspended = status?.lifecycle_status === "suspended";
  const deleteConfirmMatches = status !== null && deleteConfirmText.trim() === status.company_name.trim();

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-lg">
          <Building2 className="w-5 h-5 text-indigo-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Tenant Lifecycle</h2>
          <p className="text-xs text-slate-400">Suspend, reactivate, export, or permanently delete this tenant.</p>
        </div>
      </div>

      <div className="p-6 space-y-5">
        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Checking status...
          </div>
        ) : !status ? (
          <p className="text-sm text-slate-500 italic">Could not load tenant status.</p>
        ) : (
          <>
            <div className="flex items-center gap-2 text-sm">
              {isSuspended ? (
                <>
                  <ShieldAlert className="w-4 h-4 text-amber-400" />
                  <span className="text-slate-300">
                    Suspended{status.suspended_at ? ` on ${new Date(status.suspended_at).toLocaleString()}` : ""}
                    {status.suspended_by_email ? ` by ${status.suspended_by_email}` : ""}.
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span className="text-slate-300">Active.</span>
                </>
              )}
            </div>

            {error && (
              <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded-lg px-3 py-2">
                <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}
            {successMsg && <p className="text-xs text-emerald-400">{successMsg}</p>}

            {canExport && (
              <button
                onClick={handleExport}
                disabled={actionPending}
                className="flex items-center gap-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700 disabled:opacity-50 transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                Export all tenant data (JSON)
              </button>
            )}

            {!canManageLifecycle && (
              <p className="text-xs text-slate-500 italic">
                Only this tenant's owner can suspend, reactivate, or delete it.
              </p>
            )}

            {canManageLifecycle && (
              <div className="space-y-3">
                {isSuspended ? (
                  <button
                    onClick={handleReactivate}
                    disabled={actionPending}
                    className="flex items-center gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg disabled:opacity-50 transition-colors"
                  >
                    {actionPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}
                    Reactivate this tenant
                  </button>
                ) : confirmingSuspend ? (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400">Suspend this tenant for everyone?</span>
                    <button
                      onClick={handleSuspend}
                      disabled={actionPending}
                      className="text-xs bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded-lg disabled:opacity-50 transition-colors"
                    >
                      {actionPending ? "Suspending..." : "Yes, suspend"}
                    </button>
                    <button
                      onClick={() => setConfirmingSuspend(false)}
                      disabled={actionPending}
                      className="text-xs text-slate-400 hover:text-slate-200"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmingSuspend(true)}
                    className="flex items-center gap-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700 transition-colors"
                  >
                    <PauseCircle className="w-3.5 h-3.5" />
                    Suspend this tenant
                  </button>
                )}

                <div className="border-t border-rose-900/30 pt-4">
                  <h3 className="text-xs font-semibold text-rose-400 mb-1.5 flex items-center gap-1.5">
                    <Trash2 className="w-3.5 h-3.5" />
                    Danger zone -- permanent deletion
                  </h3>
                  <p className="text-[11px] text-slate-500 mb-2 leading-relaxed">
                    Permanently deletes this tenant and every row it owns (ledgers, users, audit logs --
                    everything). This cannot be undone. Type the exact company name{" "}
                    <span className="font-mono text-slate-400">{status.company_name}</span> to confirm.
                  </p>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={deleteConfirmText}
                      onChange={(e) => setDeleteConfirmText(e.target.value)}
                      placeholder={status.company_name}
                      className="flex-1 bg-slate-950 border border-rose-900/40 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-700 focus:outline-none focus:border-rose-500 transition-colors"
                    />
                    <button
                      onClick={handleDelete}
                      disabled={!deleteConfirmMatches || deleteInProgress}
                      className="bg-rose-700 hover:bg-rose-600 disabled:opacity-40 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors whitespace-nowrap"
                    >
                      {deleteInProgress ? "Deleting..." : "Delete permanently"}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
