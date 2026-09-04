"use client";

import React, { useEffect, useState } from "react";
import {
  Layers,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { useClientId } from "./ClientContext";

// DATA-09 (versioning half): the backend has carried real, tested explicit
// dataset versioning (backend/db_manager.py's
// _archive_current_ledger_version_locked/get_dataset_versions/
// get_dataset_version_rows/restore_dataset_version, GET /api/v1/data/
// dataset-versions, GET .../rows, POST .../restore) since this pass -- a
// version is created automatically whenever an upload replaces existing
// ledger data, never on deletion (see db_manager.py's own comment on why
// deletion stays a real, separate erase). This card is the real surface
// to see and use that history, same relationship IngestionHistoryCard.tsx
// has to DATA-08/DATA-09's deletion half.
//
// Deliberately a separate card, not folded into IngestionHistoryCard: that
// card's history log is upload ATTEMPTS (including rejected/errored ones);
// this one is actual DATA snapshots you can restore. Different data,
// different action (restore vs delete), worth keeping visually distinct.

interface DatasetVersion {
  version_number: number;
  archived_at: string;
  row_count: number;
  replaced_by_filename: string;
  source: "REPLACED" | "RESTORE_SNAPSHOT" | string;
}

interface VersionRow {
  row_id: number;
  date: string;
  category: string;
  amount: number;
  description: string;
  is_recurring: boolean | null;
}

function backendUrl(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
}

function SourceBadge({ source }: { source: string }) {
  if (source === "RESTORE_SNAPSHOT") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-sky-400 bg-sky-500/10 border border-sky-500/20 rounded-full px-2 py-0.5">
        Pre-restore snapshot
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-slate-400 bg-slate-500/10 border border-slate-500/20 rounded-full px-2 py-0.5">
      Replaced by upload
    </span>
  );
}

interface DatasetVersionsCardProps {
  refreshTrigger: number;
  onDataChanged: () => void;
}

export default function DatasetVersionsCard({ refreshTrigger, onDataChanged }: DatasetVersionsCardProps) {
  const clientCtx = useClientId() as any;
  const { authToken, authReady } = clientCtx;
  const role = clientCtx.user?.role;
  const canRestore = role === "owner" || role === "admin";

  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);
  const [expandedRows, setExpandedRows] = useState<VersionRow[]>([]);
  const [rowsLoading, setRowsLoading] = useState(false);

  const [armedVersion, setArmedVersion] = useState<number | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreMsg, setRestoreMsg] = useState<string | null>(null);

  const authHeaders = (): Record<string, string> => (authToken ? { Authorization: `Bearer ${authToken}` } : {});

  const loadVersions = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl()}/api/v1/data/dataset-versions?limit=20`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`Server status: ${res.status}`);
      const data = await res.json();
      setVersions(data.versions ?? []);
    } catch (err: any) {
      setError(err.message || "Could not load dataset versions.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authReady) return;
    loadVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, authToken, refreshTrigger]);

  const toggleInspect = async (versionNumber: number) => {
    if (expandedVersion === versionNumber) {
      setExpandedVersion(null);
      setExpandedRows([]);
      return;
    }
    setExpandedVersion(versionNumber);
    setRowsLoading(true);
    setExpandedRows([]);
    try {
      const res = await fetch(
        `${backendUrl()}/api/v1/data/dataset-versions/${versionNumber}/rows?limit=25`,
        { headers: authHeaders() }
      );
      if (!res.ok) throw new Error(`Server status: ${res.status}`);
      const data = await res.json();
      setExpandedRows(data.rows ?? []);
    } catch (err) {
      setExpandedRows([]);
    } finally {
      setRowsLoading(false);
    }
  };

  const handleRestore = async (versionNumber: number) => {
    setRestoring(true);
    setRestoreError(null);
    setRestoreMsg(null);
    try {
      const res = await fetch(
        `${backendUrl()}/api/v1/data/dataset-versions/${versionNumber}/restore`,
        { method: "POST", headers: authHeaders() }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      const body = await res.json();
      setRestoreMsg(body.message || `Restored version ${versionNumber}.`);
      setArmedVersion(null);
      await loadVersions();
      onDataChanged();
    } catch (err: any) {
      setRestoreError(err.message || "Could not restore this version.");
    } finally {
      setRestoring(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-lg">
          <Layers className="w-5 h-5 text-indigo-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Dataset Versions</h2>
          <p className="text-xs text-slate-400">
            Every time an upload replaces existing data, the old data is kept here -- inspect or restore it.
          </p>
        </div>
      </div>

      <div className="p-6 space-y-4">
        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading versions...
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded-lg px-3 py-2">
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : versions.length === 0 ? (
          <p className="text-sm text-slate-500 italic">
            No dataset versions yet -- a version is created automatically the next time you upload a file that replaces existing data.
          </p>
        ) : (
          <div className="max-h-96 overflow-y-auto space-y-2 pr-1">
            {restoreMsg && (
              <div className="flex items-start gap-2 text-xs text-emerald-400 bg-emerald-950/20 border border-emerald-900/40 rounded-lg px-3 py-2">
                <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <span>{restoreMsg}</span>
              </div>
            )}
            {restoreError && (
              <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded-lg px-3 py-2">
                <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <span>{restoreError}</span>
              </div>
            )}

            {versions.map((v) => (
              <div key={v.version_number} className="bg-slate-950/40 border border-slate-800 rounded-lg overflow-hidden">
                <div className="flex items-start justify-between gap-3 px-3 py-2">
                  <button
                    onClick={() => toggleInspect(v.version_number)}
                    className="min-w-0 flex-1 flex items-start gap-2 text-left"
                  >
                    {expandedVersion === v.version_number ? (
                      <ChevronDown className="w-3.5 h-3.5 text-slate-500 mt-0.5 flex-shrink-0" />
                    ) : (
                      <ChevronRight className="w-3.5 h-3.5 text-slate-500 mt-0.5 flex-shrink-0" />
                    )}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold text-slate-200">Version {v.version_number}</span>
                        <SourceBadge source={v.source} />
                      </div>
                      <p className="text-[11px] text-slate-500 mt-1 truncate">
                        {v.row_count} row{v.row_count === 1 ? "" : "s"}, superseded by{" "}
                        <span className="font-mono text-slate-400">{v.replaced_by_filename}</span>
                      </p>
                    </div>
                  </button>
                  <div className="text-right flex-shrink-0">
                    <p className="text-[11px] text-slate-500">{new Date(v.archived_at).toLocaleString()}</p>
                    {canRestore && (
                      armedVersion === v.version_number ? (
                        <div className="flex items-center gap-1 mt-1">
                          <button
                            onClick={() => handleRestore(v.version_number)}
                            disabled={restoring}
                            className="bg-sky-700 hover:bg-sky-600 disabled:opacity-40 text-white text-[11px] font-semibold px-2 py-1 rounded-md whitespace-nowrap"
                          >
                            {restoring ? "Restoring..." : "Confirm restore"}
                          </button>
                          <button
                            onClick={() => setArmedVersion(null)}
                            disabled={restoring}
                            className="text-[11px] text-slate-400 hover:text-slate-300 px-1.5 py-1"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setArmedVersion(v.version_number)}
                          className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-sky-400 mt-1"
                        >
                          <RotateCcw className="w-3 h-3" /> Restore
                        </button>
                      )
                    )}
                  </div>
                </div>

                {expandedVersion === v.version_number && (
                  <div className="border-t border-slate-800 px-3 py-2 bg-slate-950/60">
                    {rowsLoading ? (
                      <div className="flex items-center gap-2 text-slate-500 text-[11px] py-1">
                        <Loader2 className="w-3 h-3 animate-spin" /> Loading rows...
                      </div>
                    ) : expandedRows.length === 0 ? (
                      <p className="text-[11px] text-slate-500 italic">No rows in this version.</p>
                    ) : (
                      <div className="space-y-1 max-h-40 overflow-y-auto">
                        {expandedRows.map((r) => (
                          <div key={r.row_id} className="flex justify-between text-[11px] text-slate-400 gap-2">
                            <span className="truncate">
                              {r.date} · {r.category} · {r.description}
                            </span>
                            <span className="font-mono flex-shrink-0">{r.amount}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {!canRestore && versions.length > 0 && (
          <p className="text-xs text-slate-500 italic border-t border-slate-800 pt-4">
            Only this tenant's owner or admin can restore a past dataset version.
          </p>
        )}
      </div>
    </div>
  );
}
