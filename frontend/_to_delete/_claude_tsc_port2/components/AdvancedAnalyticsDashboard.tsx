"use client";

import { useCallback, useEffect, useState } from 'react';
import { BarChart3, TrendingUp, DollarSign, Loader2, AlertCircle } from 'lucide-react';
import { useClientId } from './ClientContext';

// REWRITTEN. The previous version fetched /api/v1/bi/summary with NO
// Authorization header at all (that endpoint requires one --
// Depends(verify_jwt_and_get_client_id) -- so the request was always
// rejected with 401) and sent a made-up "x-client-id" header the backend
// never reads. Even ignoring auth, generate_bi_summary()'s real response
// has no "metrics.total_revenue/total_expense/net_profit" fields at all
// -- those never existed anywhere in the backend. Either way, this
// component always fell back to hardcoded numbers baked into its own
// source ($124,500 / $45,070 / $79,430, "+14.2% from last ledger batch")
// -- not stale data, fake data that displayed permanently regardless of
// what was really in the ledger.
//
// Fixed to call the new, real /api/v1/finance/analytics-summary endpoint
// (pure arithmetic over db_manager.get_ledger_chart_context -- no LLM),
// with a real Bearer token, and to surface real errors/empty-state
// instead of ever silently substituting invented numbers.

interface AnalyticsSummaryPayload {
  status: string;
  total_revenue: number;
  total_expense: number;
  net_profit: number;
  trend_note: string;
}

interface AdvancedAnalyticsDashboardProps {
  refreshTrigger: number;
}

export default function AdvancedAnalyticsDashboard({ refreshTrigger }: AdvancedAnalyticsDashboardProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [data, setData] = useState<AnalyticsSummaryPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAnalytics = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;

    setLoading(true);
    setError(null);

    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const res = await fetch(`${backendUrl}/api/v1/finance/analytics-summary`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        signal,
      });

      if (!res.ok) {
        throw new Error(`Analytics summary request failed: ${res.status}`);
      }

      setData(await res.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Failed to fetch analytics summary:", err);
      setError(err.message || "Analytics summary is currently unavailable.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchAnalytics(controller.signal);
    return () => controller.abort();
  }, [fetchAnalytics, refreshTrigger]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-indigo-400" />
            Advanced Statistical & BI Analytics Suite
          </h3>
          <p className="text-xs text-slate-400 mt-1">Real revenue/expense/profit computed directly from this tenant's ledger.</p>
        </div>
        <span className="px-3 py-1 bg-indigo-950 text-indigo-400 border border-indigo-800 rounded-full text-xs font-semibold">
          Live Warehouse Sync
        </span>
      </div>

      {error && !data ? (
        <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
          <AlertCircle className="w-8 h-8 text-rose-500/50" />
          <p className="text-sm">{error}</p>
        </div>
      ) : loading && !data ? (
        <div className="flex flex-col items-center justify-center py-8 gap-3 text-indigo-400">
          <Loader2 className="w-6 h-6 animate-spin" />
          <p className="text-sm font-medium">Computing real analytics from ledger data...</p>
        </div>
      ) : data?.status === "NO_DATA" ? (
        <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400 text-center">
          <BarChart3 className="w-8 h-8 text-slate-600" />
          <p className="text-sm">{data.trend_note}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-slate-950 border border-slate-800/80 rounded-lg p-4">
            <div className="flex items-center justify-between text-slate-400 text-xs uppercase font-semibold">
              <span>Total Revenue</span>
              <TrendingUp className="w-4 h-4 text-emerald-400" />
            </div>
            <p className="text-2xl font-bold text-white mt-2">
              ${(data?.total_revenue ?? 0).toLocaleString()}
            </p>
            <p className="text-xs text-emerald-400 mt-1">{data?.trend_note}</p>
          </div>

          <div className="bg-slate-950 border border-slate-800/80 rounded-lg p-4">
            <div className="flex items-center justify-between text-slate-400 text-xs uppercase font-semibold">
              <span>Total Operational Expenses</span>
              <DollarSign className="w-4 h-4 text-amber-400" />
            </div>
            <p className="text-2xl font-bold text-white mt-2">
              ${(data?.total_expense ?? 0).toLocaleString()}
            </p>
            <p className="text-xs text-slate-500 mt-1">Sum of all negative-amount ledger rows for this tenant</p>
          </div>

          <div className="bg-slate-950 border border-slate-800/80 rounded-lg p-4">
            <div className="flex items-center justify-between text-slate-400 text-xs uppercase font-semibold">
              <span>Net Calculated Profit</span>
              <BarChart3 className="w-4 h-4 text-indigo-400" />
            </div>
            <p className="text-2xl font-bold text-white mt-2">
              ${(data?.net_profit ?? 0).toLocaleString()}
            </p>
            <p className="text-xs text-indigo-400 mt-1">Revenue minus expenses, this tenant's real ledger only</p>
          </div>
        </div>
      )}
    </div>
  );
}
