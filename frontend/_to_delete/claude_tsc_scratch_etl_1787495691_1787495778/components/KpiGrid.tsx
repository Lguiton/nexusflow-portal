"use client";

import React, { useEffect, useState } from 'react';
import { DollarSign, TrendingUp, Loader2, AlertCircle } from 'lucide-react';
import { useClientId } from "./ClientContext";

// Rewritten 2026-08-22. This file was previously named KpiGrid but exported
// a component literally called `Header` -- a full second copy of the app's
// header (logo, title, hardcoded "SECURE_ONLINE"/"ISOLATED" status text,
// and a Sub-Agent Network tile), rendered directly underneath page.tsx's
// own real header. That produced the duplicate/conflicting header panels
// seen in the live dashboard. Per founder decision, this is now repurposed
// into what its name always implied: a real KPI widget.
//
// Only Ledger Total and Monthly Revenue are shown. "Active Clients" is
// intentionally omitted -- there is no field anywhere in the ledgers table
// (client_id, date, category, amount, description) that identifies an
// individual customer distinct from the tenant itself, so there is
// currently no real data to compute it from. Per founder decision
// (2026-08-22), this stays out until a real customer-identifying field
// exists in ingestion, rather than show a fabricated number.
interface KpiSummary {
  ledger_total_amount: number;
  ledger_row_count: number;
  monthly_revenue: number;
  monthly_revenue_label: string;
  revenue_month: string;
}

interface KpiGridProps {
  refreshTrigger?: number;
}

export default function KpiGrid({ refreshTrigger = 0 }: KpiGridProps) {
  const [data, setData] = useState<KpiSummary | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  let currentClientId = "default_client";
  let authToken: string | null = null;
  let authReady = false;
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) {
      currentClientId = clientCtx.clientId;
    }
    authToken = clientCtx?.authToken ?? null;
    authReady = clientCtx?.authReady ?? false;
  } catch (e) {}

  useEffect(() => {
    if (!authReady) return;

    let cancelled = false;

    async function fetchKpiSummary() {
      setLoading(true);
      try {
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
        const response = await fetch(`${backendUrl}/api/v1/finance/kpi-summary`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { 'Authorization': `Bearer ${authToken}` } : {}),
          },
        });
        if (!response.ok) {
          throw new Error(`KPI summary request failed: ${response.status}`);
        }
        const result: KpiSummary = await response.json();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (err: any) {
        console.error("KPI summary fetch failed:", err);
        if (!cancelled) {
          setError(err.message || "Unable to load KPI data right now.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchKpiSummary();
    return () => { cancelled = true; };
  }, [currentClientId, refreshTrigger, authReady, authToken]);

  const formatCurrency = (n: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Ledger Total</span>
          <DollarSign className="w-5 h-5 text-indigo-400" />
        </div>
        <div className="mt-4">
          {error ? (
            <div className="flex items-center gap-2 text-slate-400">
              <AlertCircle className="w-4 h-4 text-rose-500/70" />
              <span className="text-sm">{error}</span>
            </div>
          ) : loading ? (
            <div className="flex items-center gap-2 text-indigo-400">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm">Loading...</span>
            </div>
          ) : (
            <>
              <p className="text-2xl font-bold text-white">{formatCurrency(data?.ledger_total_amount ?? 0)}</p>
              <p className="text-xs text-slate-500 mt-1">Across {data?.ledger_row_count ?? 0} ledger entries</p>
            </>
          )}
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            {data?.monthly_revenue_label || "Monthly Revenue"}
          </span>
          <TrendingUp className="w-5 h-5 text-emerald-400" />
        </div>
        <div className="mt-4">
          {error ? (
            <div className="flex items-center gap-2 text-slate-400">
              <AlertCircle className="w-4 h-4 text-rose-500/70" />
              <span className="text-sm">{error}</span>
            </div>
          ) : loading ? (
            <div className="flex items-center gap-2 text-emerald-400">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm">Loading...</span>
            </div>
          ) : (
            <>
              <p className="text-2xl font-bold text-white">{formatCurrency(data?.monthly_revenue ?? 0)}</p>
              <p className="text-xs text-slate-500 mt-1">
                {data?.revenue_month ?? ""} -- total revenue this month, not a recurring-revenue figure
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
