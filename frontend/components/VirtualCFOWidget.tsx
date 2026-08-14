'use client';

import React, { useState, useEffect } from 'react';
import { Briefcase, TrendingUp, Flame, Clock, AlertCircle, Loader2, ChevronRight, Sparkles } from 'lucide-react';

// Define the expected shape of the CFO payload from main.py
interface CFOMetrics {
  gross_margin: number;
  burn_rate: number;
  cash_runway_months: number;
}

interface CFOPayload {
  metrics: CFOMetrics;
  insights: string[];
}

export default function VirtualCFOWidget() {
  const [data, setData] = useState<CFOPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchCFOBriefing() {
      try {
        // Your backend route expects a POST request for the CFO briefing
        const response = await fetch('http://127.0.0.1:8000/api/v1/finance/cfo-briefing', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        });

        if (!response.ok) {
          throw new Error(`Server status: ${response.status}`);
        }

        const result = await response.json();
        setData(result);
      } catch (err: any) {
        console.error("Virtual CFO fetch failed:", err);
        setError("Virtual CFO is currently analyzing offline ledgers.");
      } finally {
        setLoading(false);
      }
    }

    fetchCFOBriefing();
  }, []);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      {/* Header */}
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
        
        {loading && (
          <div className="flex items-center gap-2 text-indigo-400 text-sm font-medium bg-indigo-950/30 px-3 py-1.5 rounded-full border border-indigo-900/50">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>Compiling Briefing...</span>
          </div>
        )}
      </div>

      {/* Body */}
      <div className="p-6 flex-1">
        {error ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 py-8 gap-3">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : !data && !loading ? (
          <div className="text-slate-500 text-sm py-8 text-center">No briefing available.</div>
        ) : (
          <div className={`space-y-8 transition-opacity duration-500 ${loading ? 'opacity-30' : 'opacity-100'}`}>
            
            {/* Top Metrics Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Gross Margin */}
              <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Gross Margin</span>
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                </div>
                <div className="text-2xl font-bold text-slate-100">
                  {data?.metrics?.gross_margin ? `${data.metrics.gross_margin.toFixed(1)}%` : '--'}
                </div>
              </div>

              {/* Burn Rate */}
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

              {/* Runway */}
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

            {/* Strategic Insights */}
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