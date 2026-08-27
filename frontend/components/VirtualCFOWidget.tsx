'use client';

import React, { useState, useEffect } from 'react';
import { Briefcase, TrendingUp, Flame, Clock, AlertCircle, Loader2, ChevronRight, Sparkles, Download, UploadCloud } from 'lucide-react';
import { useClientId } from "./ClientContext";

interface CFOPayload {
  metrics: { gross_margin: number; burn_rate: number; cash_runway_months: number; };
  insights: string[];
  // FIN-02/FIN-03: metrics are now scoped to one real calendar month (the
  // tenant's most recently completed month with ledger data), not a
  // lifetime-to-date sum -- reporting_month ("YYYY-MM") is surfaced in the
  // header so that scope is visible, not silently assumed by the viewer.
  reporting_month?: string | null;
}

// "2026-07" -> "July 2026". Falls back to the raw string if it doesn't
// parse cleanly -- never hide the month behind a blank label.
function formatReportingMonth(reportingMonth: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(reportingMonth);
  if (!match) return reportingMonth;
  const [, yearStr, monthStr] = match;
  const monthIndex = parseInt(monthStr, 10) - 1;
  const date = new Date(parseInt(yearStr, 10), monthIndex, 1);
  if (Number.isNaN(date.getTime())) return reportingMonth;
  return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

export default function VirtualCFOWidget({ refreshTrigger = 0, onNavigateToLedger }: { refreshTrigger?: number; onNavigateToLedger?: () => void }) {
  const [data, setData] = useState<CFOPayload | null>(null);
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
    // Wait for ClientProvider's dev-login to resolve (success OR failure)
    // before firing -- previously this fired immediately on mount, before
    // any token could possibly exist, and never re-fired once one did.
    if (!authReady) return;

    async function fetchCFOBriefing() {
      setLoading(true);
      try {
        // Was hardcoded to "http://127.0.0.1:8000" -- inconsistent with
        // every other widget in this app, and silently breaks anywhere
        // other than that exact local setup. Matches the rest of the
        // codebase's convention now.
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

        const response = await fetch(`${backendUrl}/api/v1/finance/cfo-briefing`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-client-id': currentClientId,
            ...(authToken ? { 'Authorization': `Bearer ${authToken}` } : {})
          },
        });

        if (!response.ok) {
          throw new Error(`Server status: ${response.status}`);
        }

        const result = await response.json();
        setData(result);
        setError(null);
      } catch (err: any) {
        console.error("Virtual CFO fetch failed:", err);
        setError(err.message || "Virtual CFO is currently analyzing offline ledgers.");
      } finally {
        setLoading(false);
      }
    }

    fetchCFOBriefing();
  }, [currentClientId, refreshTrigger, authReady, authToken]);

  // A successful fetch with no ledger uploaded yet still returns a 200 with
  // all-zero/null metrics and an empty insights array -- that's not an
  // error, so it shouldn't hit the `error` branch, but rendering three bare
  // "--" tiles and "No strategic insights generated for this period." gives
  // a first-time user nothing to act on. Treat "all metrics falsy and no
  // insights" as its own guided empty state instead.
  const hasNoLedgerData =
    !!data &&
    !data.metrics?.gross_margin &&
    !data.metrics?.burn_rate &&
    !data.metrics?.cash_runway_months &&
    (!data.insights || data.insights.length === 0);

  const handleExport = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `cfo-briefing-${new Date().toISOString().split('T')[0]}.json`;
    a.click();
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-lg">
            <Briefcase className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              Virtual CFO Briefing
            </h2>
            <p className="text-xs text-slate-400">
              {data?.reporting_month
                ? `Executive financial summary for ${formatReportingMonth(data.reporting_month)}`
                : 'AI-generated executive financial summary'}
            </p>
          </div>
        </div>

        <button
          onClick={handleExport}
          disabled={loading || !data}
          className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed border border-slate-700"
        >
          <Download className="w-3 h-3" />
          Export JSON
        </button>
      </div>

      <div className="p-6 flex-1">
        {error ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 py-8 gap-3">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading ? (
          <div className="flex flex-col items-center justify-center h-full text-indigo-400 py-8 gap-3">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Compiling Briefing...</p>
          </div>
        ) : !data ? (
          <div className="text-slate-500 text-sm py-8 text-center">No briefing available.</div>
        ) : hasNoLedgerData ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-8 gap-3">
            <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-full">
              <UploadCloud className="w-6 h-6 text-indigo-400" />
            </div>
            <p className="text-sm font-medium text-slate-300">No ledger data yet</p>
            <p className="text-xs text-slate-500 max-w-xs">
              Upload a CSV ledger to generate your first Virtual CFO briefing — gross margin, burn rate, and cash runway will populate automatically.
            </p>
            {onNavigateToLedger && (
              <button
                onClick={onNavigateToLedger}
                className="mt-1 bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded text-xs font-semibold transition-colors flex items-center gap-1.5"
              >
                <UploadCloud className="w-3 h-3" />
                Upload Ledger
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-8 animate-in fade-in duration-500">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Gross Margin</span>
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                </div>
                <div className="text-2xl font-bold text-slate-100">
                  {data?.metrics?.gross_margin ? `${data.metrics.gross_margin.toFixed(1)}%` : '--'}
                </div>
              </div>

              <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Monthly Burn</span>
                  <Flame className="w-4 h-4 text-rose-400" />
                </div>
                <div className="text-2xl font-bold text-slate-100">
                  {data?.metrics?.burn_rate
                    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(data.metrics.burn_rate)
                    : '--'}
                </div>
              </div>

              <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Cash Runway</span>
                  <Clock className="w-4 h-4 text-cyan-400" />
                </div>
                <div className="text-2xl font-bold text-slate-100 flex items-baseline gap-1">
                  {data?.metrics?.cash_runway_months ? data.metrics.cash_runway_months.toFixed(1) : '--'}
                  <span className="text-sm font-medium text-slate-500">months</span>
                </div>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-indigo-400" />
                Strategic Advisory
              </h3>
              <div className="space-y-3">
                {data?.insights && data.insights.length > 0 ? (
                  data.insights.map((insight, idx) => (
                    <div key={idx} className="flex gap-3 items-start bg-slate-800/30 p-3.5 rounded-lg border border-slate-700/30">
                      <ChevronRight className="w-4 h-4 text-indigo-500 mt-0.5 shrink-0" />
                      <p className="text-sm text-slate-300 leading-relaxed">{insight}</p>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-500 italic">
                    No strategic insights generated for this period — insights are produced from your uploaded ledger data, so this usually means the current period doesn't have enough transactions yet.
                  </p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
