"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { ScatterChart as ScatterIcon, Loader2, AlertCircle } from "lucide-react";
import { useClientId } from "./ClientContext";

// Real per-transaction scatter: date (x) vs amount (y), one point per real
// ledger row, colored by category. Deliberately a DIFFERENT real data
// source than the chart-suite's three aggregate datasets (category
// totals, monthly totals, amount-distribution bins) -- none of those have
// two independent numeric fields per point that a scatter could honestly
// plot. Per-row date+amount does, via the same real, already-existing
// POST /api/v1/finance/ledger-rows endpoint LedgerRowExplorer uses for its
// table view (see backend/evidence.py). Requests the max allowed 1000 rows
// with no category/month filter, most-recent-first (the endpoint's own
// ordering) -- a real recency-biased sample of this tenant's ledger, not
// every row ever ingested if there are more than 1000.
const COLORS = ["#5b6ef0", "#8b6ef5", "#33c1f0", "#2fd199", "#f0a93b", "#f2596b", "#7d8cf5", "#5fd3ff"];

interface LedgerRow {
  row_id: number | null;
  date: string;
  category: string;
  amount: number;
  description: string;
  is_recurring: boolean | null;
}

interface LedgerRowsResponse {
  row_count: number;
  legacy_row_count: number;
  rows: LedgerRow[];
}

interface TransactionScatterPanelProps {
  refreshTrigger?: number;
}

const formatCurrency = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

const formatDateTick = (ms: number) => {
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};

export default function TransactionScatterPanel({ refreshTrigger = 0 }: TransactionScatterPanelProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

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
        body: JSON.stringify({ limit: 1000 }),
        signal,
      });
      if (!response.ok) {
        throw new Error(`Ledger row lookup failed: ${response.status}`);
      }
      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Transaction scatter fetch failed:", err);
      setError(err.message || "Unable to load transaction data right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchRows(controller.signal);
    return () => controller.abort();
  }, [fetchRows, refreshTrigger]);

  const seriesByCategory = useMemo(() => {
    const rows = data?.rows ?? [];
    const grouped = new Map<string, Array<{ x: number; y: number; description: string; date: string }>>();
    for (const row of rows) {
      const ms = new Date(row.date).getTime();
      if (Number.isNaN(ms)) continue; // unparseable date -- skip rather than plot a fabricated position
      if (!grouped.has(row.category)) grouped.set(row.category, []);
      grouped.get(row.category)!.push({ x: ms, y: row.amount, description: row.description, date: row.date });
    }
    return Array.from(grouped.entries()).map(([category, points], idx) => ({
      category,
      points,
      color: COLORS[idx % COLORS.length],
    }));
  }, [data]);

  const skippedCount = (data?.rows?.length ?? 0) - seriesByCategory.reduce((sum, s) => sum + s.points.length, 0);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
          <ScatterIcon className="w-5 h-5 text-cyan-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Transaction Scatter</h2>
          <p className="text-xs text-slate-400">
            Every real transaction plotted by date and amount, colored by category
          </p>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-cyan-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Loading transactions...</p>
          </div>
        ) : !data || data.row_count === 0 ? (
          <p className="text-sm text-slate-500 italic py-8 text-center font-mono">
            No ledger data has been ingested yet for this tenant.
          </p>
        ) : (
          <div className="animate-in fade-in duration-500">
            {data.row_count >= 1000 && (
              <p className="text-xs text-amber-400/80 mb-3">
                Showing the {data.row_count} most recent transactions -- there may be more on file than fit here.
              </p>
            )}
            <ResponsiveContainer width="100%" height={320}>
              <ScatterChart margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  type="number"
                  dataKey="x"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={formatDateTick}
                  stroke="#64748b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  tickFormatter={(v: number) => formatCurrency(v)}
                  stroke="#64748b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  width={70}
                />
                <ZAxis range={[40, 40]} />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3", stroke: "#334155" }}
                  content={({ active, payload }) => {
                    if (!active || !payload || !payload.length) return null;
                    const p = payload[0].payload as { x: number; y: number; description: string; date: string };
                    return (
                      <div className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 shadow-xl max-w-[220px]">
                        <p className="font-semibold mb-1">{p.date}</p>
                        <p className={p.y >= 0 ? "text-emerald-400" : "text-rose-400"}>{formatCurrency(p.y)}</p>
                        {p.description && <p className="text-slate-400 mt-1 truncate">{p.description}</p>}
                      </div>
                    );
                  }}
                />
                <Legend wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }} />
                {seriesByCategory.map((s) => (
                  <Scatter key={s.category} name={s.category} data={s.points} fill={s.color} />
                ))}
              </ScatterChart>
            </ResponsiveContainer>
            {skippedCount > 0 && (
              <p className="text-xs text-slate-500 mt-2">
                {skippedCount} row{skippedCount === 1 ? "" : "s"} omitted -- unparseable date.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
