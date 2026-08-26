"use client";

import React, { useEffect, useState } from "react";
import { ScrollText, Loader2, ShieldCheck, ShieldAlert, RefreshCw } from "lucide-react";
import { useClientId } from "./ClientContext";

// ENT-03: explainable-AI audit/lineage log. Every real routed query gets
// one entry here (orchestrator.route_query -> db_manager.log_lineage_entry),
// hash-chained per tenant so tampering is detectable, not just claimed --
// the integrity panel below is a real recomputation of that chain, not a
// static badge.
interface LineageEntry {
  lineage_id: number;
  timestamp: string;
  session_id: string | null;
  agent_name: string;
  model_used: string | null;
  query_text: string;
  decision_summary: string;
  status: string;
  row_hash: string;
}

interface Integrity {
  intact: boolean;
  row_count: number;
  first_break_lineage_id: number | null;
}

export default function AuditLineageCard() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const [entries, setEntries] = useState<LineageEntry[]>([]);
  const [integrity, setIntegrity] = useState<Integrity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchLineage = async () => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/audit/lineage?limit=25`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) throw new Error(`Server status: ${res.status}`);
      const data = await res.json();
      setEntries(data.entries ?? []);
      setIntegrity(data.integrity ?? null);
    } catch (err: any) {
      setError(err.message || "Could not load the audit lineage log.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLineage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, authToken, backendUrl]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
            <ScrollText className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Audit Lineage</h2>
            <p className="text-xs text-slate-400">Every routed query, hash-chained so tampering is detectable.</p>
          </div>
        </div>
        <button
          onClick={fetchLineage}
          disabled={loading}
          className="text-slate-500 hover:text-slate-300 transition-colors disabled:opacity-50"
          aria-label="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="p-6 space-y-4">
        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading lineage log...
          </div>
        ) : error ? (
          <p className="text-xs text-rose-400">{error}</p>
        ) : (
          <>
            {integrity && (
              <div
                className={`flex items-center gap-2 rounded-lg border p-3 text-xs ${
                  integrity.intact
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                    : "bg-rose-500/10 border-rose-500/30 text-rose-300"
                }`}
              >
                {integrity.intact ? <ShieldCheck className="w-4 h-4 shrink-0" /> : <ShieldAlert className="w-4 h-4 shrink-0" />}
                <span>
                  {integrity.row_count === 0
                    ? "No lineage entries yet -- nothing to verify."
                    : integrity.intact
                    ? `Chain verified intact across all ${integrity.row_count} entr${integrity.row_count === 1 ? "y" : "ies"}.`
                    : `Chain integrity check FAILED at entry #${integrity.first_break_lineage_id} -- this record may have been altered.`}
                </span>
              </div>
            )}

            {entries.length === 0 ? (
              <p className="text-xs text-slate-600 italic">No queries have been routed yet for this tenant.</p>
            ) : (
              <div className="space-y-1.5 max-h-80 overflow-y-auto">
                {entries.map((e) => (
                  <div key={e.lineage_id} className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-cyan-400 font-medium">{e.agent_name}</span>
                      <span
                        className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
                          e.status === "COMPLETE" || e.status === "ANSWERED"
                            ? "bg-emerald-500/10 text-emerald-400"
                            : "bg-rose-500/10 text-rose-400"
                        }`}
                      >
                        {e.status}
                      </span>
                    </div>
                    <p className="text-slate-400 truncate" title={e.query_text}>{e.query_text || "(no query text)"}</p>
                    <p className="text-slate-600 mt-1">{new Date(e.timestamp).toLocaleString()}</p>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
