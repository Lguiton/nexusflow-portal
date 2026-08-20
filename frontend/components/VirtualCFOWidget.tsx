'use client';

import React, { useState, useEffect } from 'react';
import { Briefcase, TrendingUp, Flame, Clock, AlertCircle, Loader2, ChevronRight, Sparkles, Download } from 'lucide-react';
import { useClientId } from "./ClientContext";

interface CFOPayload {
  metrics: { gross_margin: number; burn_rate: number; cash_runway_months: number; };
  insights: string[];
}

export default function VirtualCFOWidget({ refreshTrigger = 0 }: { refreshTrigger?: number }) {
  const [data, setData] = useState<CFOPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  let currentClientId = "default_client";
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) {
      currentClientId = clientCtx.clientId;
    }
  } catch (e) {}

  useEffect(() => {
    async function fetchCFOBriefing() {
      setLoading(true);
      try {
        // FIX: Hardcoded to 127.0.0.1:8000 to perfectly match the Uvicorn terminal output
        const backendUrl = "http://127.0.0.1:8000";
        const token = typeof window !== 'undefined' ? sessionStorage.getItem('nexus_access_token') : null;

        const response = await fetch(`${backendUrl}/api/v1/finance/cfo-briefing`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-client-id': currentClientId,
            ...(token ? { 'Authorization': `Bearer ${token}` } : {})
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
  }, [currentClientId, refreshTrigger]);

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
            <p className="text-xs text-slate-400">AI-generated executive financial summary</p>
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
                  <p className="text-sm text-slate-500 italic">No strategic insights generated for this period.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
