"use client";

import { useCallback, useEffect, useState } from "react";
import { Search, Loader2, AlertCircle, ListFilter } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-01: evidence trail. Real drill-down into the exact ledger rows
// behind a category/month via POST /api/v1/finance/ledger-rows -- every
// row shown here carries its real row_id (see backend/db_manager.py's
// DIFF-01 migration), not a fabricated reference. Scope note: this is a
// standalone explorer, not (yet) wired into every chart/insight elsewhere
// on the dashboard as a click-through -- see backend/evidence.py's module
// docstring for why that's a separate, larger step.
interface LedgerRow {
  row_id: number | null;
  date: string;
  category: string;
  amount: number;
  description: string;
  is_recurring: boolean | null;
}

interface LedgerRowsResponse {
  client_id: string;
  filter: { category: string | null; month: string | null };
  row_count: number;
  legacy_row_count: number;
  rows: LedgerRow[];
}

interface LedgerRowExplorerProps {
  refreshTrigger?: number;
}

export default function LedgerRowExplorer({ refreshTrigger = 0 }: LedgerRowExplorerProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [category, setCategory] = useState("");
  const [month, setMonth] = useState("");
  const [data, setData] = useState<LedgerRowsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRows = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/api/v1/finance/ledger-rows`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          category: category.trim() || null,
          month: month.trim() || null,
          limit: 50,
        }),
        signal,
      });
      if (!response.ok) {
        throw new Error(`Ledger row lookup failed: ${response.status}`);
      }
      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Ledger row explorer fetch failed:", err);
      setError(err.message || "Unable to load ledger rows right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady, category, month]);

  useEffect(() => {
    const controller = new AbortController();
    fetchRows(controller.signal);
    return () => controller.abort();
  }, [fetchRows, refreshTrigger]);

  const formatCurrency = (n: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-violet-500/10 border border-violet-500/20 rounded-lg">
            <Search className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Ledger Row Explorer</h2>
            <p className="text-xs text-slate-400">See the exact transactions behind any category or month</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="Category (exact)"
            className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 placeholder:text-slate-500 w-36"
          />
          <input
            type="text"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            placeholder="YYYY-MM"
            className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 placeholder:text-slate-500 w-24"
          />
          <button
            onClick={() => fetchRows()}
            disabled={loading}
            className="text-xs bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50 border border-violet-700/40"
          >
            <ListFilter className="w-3 h-3" />
            Filter
          </button>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-violet-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Loading rows...</p>
          </div>
        ) : data && data.row_count === 0 ? (
          <p className="text-sm text-slate-500 italic py-4">No matching rows.</p>
        ) : (
          <div className="animate-in fade-in duration-500">
            {data && data.legacy_row_count > 0 && (
              <p className="text-xs text-amber-400/80 mb-3">
                {data.legacy_row_count} of these rows predate row-level tracking and have no stable id yet -- re-upload to assign one.
              </p>
            )}
            <div className="overflow-x-auto rounded-lg border border-slate-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-950/50 text-left text-xs uppercase tracking-wider text-slate-500">
                    <th className="px-4 py-2.5 font-semibold">Date</th>
                    <th className="px-4 py-2.5 font-semibold">Category</th>
                    <th className="px-4 py-2.5 font-semibold">Description</th>
                    <th className="px-4 py-2.5 font-semibold text-right">Amount</th>
                    <th className="px-4 py-2.5 font-semibold">Row ID</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.rows ?? []).map((row, idx) => (
                    <tr key={row.row_id ?? idx} className="border-t border-slate-800/70">
                      <td className="px-4 py-2.5 text-slate-300 whitespace-nowrap">{row.date}</td>
                      <td className="px-4 py-2.5 text-slate-300">{row.category}</td>
                      <td className="px-4 py-2.5 text-slate-400">{row.description}</td>
                      <td className={`px-4 py-2.5 text-right font-medium whitespace-nowrap ${row.amount >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {formatCurrency(row.amount)}
                      </td>
                      <td className="px-4 py-2.5 text-slate-500 text-xs">{row.row_id ?? "legacy"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
