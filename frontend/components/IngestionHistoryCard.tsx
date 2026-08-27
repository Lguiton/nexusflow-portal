"use client";

import React, { useEffect, useState } from "react";
import {
  History,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  AlertCircle,
  Trash2,
} from "lucide-react";
import { useClientId } from "./ClientContext";

// DATA-08/DATA-09: the backend has carried a real, tested ingestion-history
// log (backend/db_manager.py's log_ingestion_attempt/get_ingestion_history,
// GET /api/v1/data/ingestion-history) and an explicit tenant-scoped ledger
// delete (delete_tenant_ledger, DELETE /api/v1/finance/ledger) since an
// earlier pass this session -- both real, both covered by backend tests
// (test_ingestion.py, test_api_endpoints.py) -- but neither was ever wired
// into any frontend component, so a real user had no way to see past
// upload attempts or to wipe their own ledger data short of re-uploading
// an empty file. This card is that missing surface, not new backend work.
//
// Deliberately separate from the history log itself: deleting ledger DATA
// (the `ledgers` table) does NOT delete the audit trail of past upload
// ATTEMPTS (the `ingestion_history` table) -- so this card's own history
// list still shows "you deleted your ledger on <date>" after the fact,
// same principle as TenantLifecycleCard's export/delete not needing to
// agree with each other's scope.

interface IngestionHistoryEntry {
  timestamp: string;
  filename: string;
  status: "SUCCESS" | "REJECTED" | "ERROR" | string;
  rows_ingested: number;
  rows_skipped: number;
  detail: string;
}

function backendUrl(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
}

function StatusBadge({ status }: { status: string }) {
  if (status === "SUCCESS") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-2 py-0.5">
        <CheckCircle2 className="w-3 h-3" /> Success
      </span>
    );
  }
  if (status === "REJECTED") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-full px-2 py-0.5">
        <AlertTriangle className="w-3 h-3" /> Rejected
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-400 bg-rose-500/10 border border-rose-500/20 rounded-full px-2 py-0.5">
      <XCircle className="w-3 h-3" /> Error
    </span>
  );
}

interface IngestionHistoryCardProps {
  refreshTrigger: number;
  onDataChanged: () => void;
}

export default function IngestionHistoryCard({ refreshTrigger, onDataChanged }: IngestionHistoryCardProps) {
  const clientCtx = useClientId() as any;
  const { authToken, authReady } = clientCtx;
  const role = clientCtx.user?.role;
  const canDelete = role === "owner" || role === "admin";

  const [history, setHistory] = useState<IngestionHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteResultMsg, setDeleteResultMsg] = useState<string | null>(null);
  const deleteConfirmMatches = confirmText.trim().toUpperCase() === "DELETE";

  const loadHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl()}/api/v1/data/ingestion-history?limit=20`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) throw new Error(`Server status: ${res.status}`);
      const data = await res.json();
      setHistory(data.history ?? []);
    } catch (err: any) {
      setError(err.message || "Could not load ingestion history.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authReady) return;
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, authToken, refreshTrigger]);

  const handleDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    setDeleteResultMsg(null);
    try {
      const res = await fetch(`${backendUrl()}/api/v1/finance/ledger`, {
        method: "DELETE",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      const body = await res.json();
      setDeleteResultMsg(body.message || `Deleted ${body.rows_deleted} row(s).`);
      setConfirmText("");
      await loadHistory();
      onDataChanged();
    } catch (err: any) {
      setDeleteError(err.message || "Could not delete ledger data.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-lg">
          <History className="w-5 h-5 text-indigo-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Ingestion History</h2>
          <p className="text-xs text-slate-400">Every upload attempt for this tenant -- successful, rejected, or errored.</p>
        </div>
      </div>

      <div className="p-6 space-y-4">
        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading history...
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded-lg px-3 py-2">
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : history.length === 0 ? (
          <p className="text-sm text-slate-500 italic">No uploads yet -- your history will show up here.</p>
        ) : (
          <div className="max-h-72 overflow-y-auto space-y-2 pr-1">
            {history.map((h, i) => (
              <div
                key={i}
                className="flex items-start justify-between gap-3 bg-slate-950/40 border border-slate-800 rounded-lg px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={h.status} />
                    <span className="text-xs font-mono text-slate-300 truncate">{h.filename}</span>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1 truncate" title={h.detail}>
                    {h.detail}
                  </p>
                </div>
                <div className="text-right flex-shrink-0">
                  <p className="text-[11px] text-slate-500">{new Date(h.timestamp).toLocaleString()}</p>
                  {h.status === "SUCCESS" && (
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      {h.rows_ingested} row{h.rows_ingested === 1 ? "" : "s"}
                      {h.rows_skipped ? `, ${h.rows_skipped} skipped` : ""}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {!canDelete ? (
          <p className="text-xs text-slate-500 italic border-t border-slate-800 pt-4">
            Only this tenant's owner or admin can delete all ledger data.
          </p>
        ) : (
          <div className="border-t border-rose-900/30 pt-4">
            <h3 className="text-xs font-semibold text-rose-400 mb-1.5 flex items-center gap-1.5">
              <Trash2 className="w-3.5 h-3.5" />
              Danger zone -- delete all ledger data
            </h3>
            <p className="text-[11px] text-slate-500 mb-2 leading-relaxed">
              Permanently deletes every ledger row this tenant has uploaded. This does not remove
              this history log, and does not affect your account or team -- only re-uploading a
              file brings data back. Type <span className="font-mono text-slate-400">DELETE</span> to confirm.
            </p>

            {deleteError && (
              <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded-lg px-3 py-2 mb-2">
                <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}
            {deleteResultMsg && <p className="text-xs text-emerald-400 mb-2">{deleteResultMsg}</p>}

            <div className="flex gap-2">
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder="DELETE"
                className="flex-1 bg-slate-950 border border-rose-900/40 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-700 focus:outline-none focus:border-rose-500 transition-colors"
              />
              <button
                onClick={handleDelete}
                disabled={!deleteConfirmMatches || deleting}
                className="bg-rose-700 hover:bg-rose-600 disabled:opacity-40 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors whitespace-nowrap"
              >
                {deleting ? "Deleting..." : "Delete all ledger data"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
