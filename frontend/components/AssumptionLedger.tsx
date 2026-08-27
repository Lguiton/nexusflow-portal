"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpenCheck, Loader2, AlertCircle } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-02: Assumption ledger. Renders the REAL numeric constants and
// methodology notes returned by GET /api/v1/assumptions -- nothing here
// is hardcoded; every value comes straight from the backend's live
// module constants (see backend/assumptions.py), so this can never drift
// out of sync with the code actually computing CFO/forecast figures.
interface NumericAssumption {
  key: string;
  label: string;
  value: number;
  unit: string;
  used_by: string;
  description: string;
}

interface MethodologyNote {
  key: string;
  label: string;
  used_by: string;
  description: string;
}

interface AssumptionsResponse {
  numeric_assumptions: NumericAssumption[];
  methodology_notes: MethodologyNote[];
}

function formatValue(value: number, unit: string): string {
  if (unit === "usd") {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
  }
  if (unit === "% per month") {
    return `${value}%/mo`;
  }
  return `${value} ${unit}`;
}

export default function AssumptionLedger() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [data, setData] = useState<AssumptionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAssumptions = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/api/v1/assumptions`, {
        method: "GET",
        headers: {
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        signal,
      });
      if (!response.ok) {
        throw new Error(`Assumption ledger request failed: ${response.status}`);
      }
      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Assumption ledger fetch failed:", err);
      // FIXED (real raw-error UI leak, confirmed live 2026-08-26 via the
      // real Jest suite -- same bug class already fixed in the Live Swarm
      // Telemetry panel): this used to be `err.message || "<friendly
      // text>"`. err.message is set from the throw above
      // ("Assumption ledger request failed: 500"), which is truthy, so
      // the friendly fallback was dead code -- every real failure showed
      // the raw HTTP status to the user instead. The technical message is
      // still logged via console.error just above; only the user-facing
      // state is now always the translated message.
      setError("Assumption ledger is currently unavailable.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchAssumptions(controller.signal);
    return () => controller.abort();
  }, [fetchAssumptions]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <BookOpenCheck className="w-5 h-5 text-amber-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Assumption Ledger</h2>
          <p className="text-xs text-slate-400">Every constant and methodology choice your numbers above actually depend on</p>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-amber-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Loading assumption ledger...</p>
          </div>
        ) : (
          <div className="space-y-6 animate-in fade-in duration-500">
            <div>
              <h3 className="text-sm font-semibold text-slate-300 mb-3">Numeric Assumptions</h3>
              <div className="overflow-x-auto rounded-lg border border-slate-800">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-950/50 text-left text-xs uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-2.5 font-semibold">Assumption</th>
                      <th className="px-4 py-2.5 font-semibold">Value</th>
                      <th className="px-4 py-2.5 font-semibold">Used By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.numeric_assumptions ?? []).map((row) => (
                      <tr key={row.key} className="border-t border-slate-800/70 align-top">
                        <td className="px-4 py-3">
                          <p className="text-slate-200 font-medium">{row.label}</p>
                          <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{row.description}</p>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-amber-400 font-semibold">
                          {formatValue(row.value, row.unit)}
                        </td>
                        <td className="px-4 py-3 text-slate-400">{row.used_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-300 mb-3">Methodology Notes</h3>
              <div className="space-y-3">
                {(data?.methodology_notes ?? []).map((note) => (
                  <div key={note.key} className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3.5">
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <p className="text-sm font-medium text-slate-200">{note.label}</p>
                      <span className="text-xs text-slate-500 whitespace-nowrap">{note.used_by}</span>
                    </div>
                    <p className="text-xs text-slate-400 leading-relaxed">{note.description}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
