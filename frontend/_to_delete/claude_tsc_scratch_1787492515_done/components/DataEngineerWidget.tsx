"use client";

import { useCallback, useEffect, useState } from "react";
import { Database, RefreshCw, CheckCircle2, ShieldCheck, Loader2, AlertCircle } from 'lucide-react';
import { useClientId } from "./ClientContext";

interface AuditPayload {
  // Was "agent_status" -- the real analyze_schema_quality() in
  // backend/agents/data_engineer.py returns the key "status" (values:
  // "NO_DATA" or "OPTIMIZED"), never "agent_status". With the old key,
  // data?.agent_status was always undefined, so the badge silently always
  // showed the hardcoded "OPTIMIZED" fallback regardless of the real
  // status -- including for a brand-new tenant with no data yet.
  status: string;
  recommendations: string[];
}

interface DataEngineerWidgetProps {
  refreshTrigger?: number;
}

export default function DataEngineerWidget({ refreshTrigger = 0 }: DataEngineerWidgetProps) {
  // 1. Unconditional Hook execution
  const clientCtx = useClientId() as any;
  const currentClientId = clientCtx?.clientId || "CLI-001";
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [data, setData] = useState<AuditPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 2. Memoized fetch function accepting an AbortSignal
  const fetchAuditData = useCallback(async (signal?: AbortSignal) => {
    // Wait for ClientProvider's dev-login to resolve (success OR failure)
    // before firing -- previously this fired immediately on mount, before
    // any token could possibly exist, and never re-fired once one did.
    if (!authReady) return;

    setLoading(true);
    setError(null);

    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

      // Was "/api/v1/data/audit" -- that route doesn't exist on the
      // backend at all (confirmed against main.py). The real endpoint is
      // "/api/v1/data/schema-audit".
      const response = await fetch(`${backendUrl}/api/v1/data/schema-audit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-client-id": currentClientId,
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        signal,
      });

      if (!response.ok) {
        throw new Error(`Audit request failed: ${response.status}`);
      }

      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;

      console.error("Data Engineer fetch failed:", err);
      // Previously this silently replaced any failure (wrong URL, network
      // error, auth failure, anything) with hardcoded fake "OPTIMIZED"
      // status and three canned recommendation strings, with a comment
      // admitting it was intentional. That masked a real, live failure as
      // a success with no way to tell from the UI. Surface the real error
      // instead, matching how every other widget in this app handles it.
      setError(err.message || "Data Engineer audit is currently unavailable.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [currentClientId, authToken, authReady]);

  // 3. Proper AbortController cleanup binding
  useEffect(() => {
    const controller = new AbortController();
    fetchAuditData(controller.signal);

    return () => controller.abort();
  }, [fetchAuditData, refreshTrigger]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
            <Database className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              Data Engineer Audit (Agent #02)
            </h2>
            <p className="text-xs text-slate-400">Automated pipeline integrity & schema hygiene</p>
          </div>
        </div>

        <button
          onClick={() => fetchAuditData()}
          disabled={loading}
          className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed border border-slate-700"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          Re-Audit
        </button>
      </div>

      <div className="p-6 flex-1 flex flex-col">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 py-8 gap-3">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center h-full text-emerald-400 py-8 gap-3">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Running Schema Audit...</p>
          </div>
        ) : (
          <div className="space-y-6 animate-in fade-in duration-500 flex-1">
            <div className="flex items-center justify-between text-xs font-semibold bg-slate-950/50 border border-slate-800/80 rounded-lg p-3">
              <div className="flex items-center gap-2">
                <span className="text-slate-500">Agent Status:</span>
                <span className="text-emerald-400 flex items-center gap-1">
                  <ShieldCheck className="w-3.5 h-3.5" />
                  {data?.status || "OPTIMIZED"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-slate-500">Tenant:</span>
                <span className="text-indigo-400">{currentClientId}</span>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
                <Database className="w-4 h-4 text-emerald-400" />
                Pipeline & Hygiene Recommendations
              </h3>
              <div className="space-y-3">
                {data?.recommendations && data.recommendations.length > 0 ? (
                  data.recommendations.map((rec, idx) => (
                    <div key={idx} className="flex gap-3 items-start bg-slate-800/30 p-3.5 rounded-lg border border-slate-700/30">
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                      <p className="text-sm text-slate-300 leading-relaxed">{rec}</p>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-500 italic">No hygiene recommendations at this time.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
