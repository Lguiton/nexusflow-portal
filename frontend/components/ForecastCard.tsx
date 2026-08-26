"use client";

import { useCallback, useEffect, useState } from "react";
import { Lock, TrendingUp, TrendingDown, Loader2, AlertCircle } from "lucide-react";
import { useClientId } from "./ClientContext";

// Forecast status card. Readiness gating (below MIN_PERIODS_FOR_FORECAST
// months on file) still reuses the real, already-wired
// POST /api/v1/insights/known-gaps endpoint and its real
// "forecast_insufficient_history" gap entry (see backend/gaps.py), same as
// before -- the message shown there is always the backend's real, current
// reason, never a hardcoded placeholder.
//
// Track 4 quick win: once enough history exists, this now actually calls
// the real, already-live POST /api/v1/predictive/forecast endpoint
// (backend/agents/predictive_forecaster.py) instead of showing "not wired
// in yet" -- every number below (baseline revenue, projected next-quarter
// revenue, growth rate, r_squared, revenue risk level) is the agent's real
// computed output, never invented client-side.
interface Gap {
  key: string;
  title: string;
  detail: string;
}

interface KnownGapsResponse {
  gaps: Gap[];
}

interface RevenueRisk {
  risk_level: string;
  consecutive_declining_months: number;
  overall_growth_rate_pct_per_month: number;
  note: string;
}

interface ForecastResult {
  agent: string;
  status: string;
  baseline_revenue: number | null;
  periods_used?: number;
  r_squared?: number;
  projected_growth_rate?: number;
  projected_q4_revenue?: number | null;
  revenue_risk?: RevenueRisk;
  projections?: string[];
}

interface ForecastCardProps {
  refreshTrigger?: number;
}

const RISK_COLORS: Record<string, string> = {
  LOW: "text-emerald-400 bg-emerald-500/10",
  MODERATE: "text-amber-400 bg-amber-500/10",
  ELEVATED: "text-amber-400 bg-amber-500/10",
  HIGH: "text-rose-400 bg-rose-500/10",
};

export default function ForecastCard({ refreshTrigger = 0 }: ForecastCardProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [gaps, setGaps] = useState<Gap[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [forecast, setForecast] = useState<ForecastResult | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  const authHeaders = authToken ? { Authorization: `Bearer ${authToken}` } : {};

  const fetchGaps = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${backendUrl}/api/v1/insights/known-gaps`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        signal,
      });
      if (!response.ok) throw new Error(`Known-gaps request failed: ${response.status}`);
      const json: KnownGapsResponse = await response.json();
      setGaps(json.gaps ?? []);
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Forecast card fetch failed:", err);
      setError(err.message || "Unable to check forecast readiness right now.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authToken, authReady, backendUrl]);

  useEffect(() => {
    const controller = new AbortController();
    fetchGaps(controller.signal);
    return () => controller.abort();
  }, [fetchGaps, refreshTrigger]);

  const forecastGap = gaps?.find((g) => g.key === "forecast_insufficient_history") ?? null;

  useEffect(() => {
    if (loading || forecastGap || gaps === null) return;
    const controller = new AbortController();
    (async () => {
      setForecastLoading(true);
      setForecastError(null);
      try {
        const res = await fetch(`${backendUrl}/api/v1/predictive/forecast`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          signal: controller.signal,
        });
        if (res.status === 402) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "Monthly AI usage cap reached.");
        }
        if (!res.ok) throw new Error(`Forecast request failed: ${res.status}`);
        const data: ForecastResult = await res.json();
        setForecast(data);
      } catch (err: any) {
        if (err.name === "AbortError") return;
        console.error("Forecast generation failed:", err);
        setForecastError(err.message || "Unable to generate a forecast right now.");
      } finally {
        if (!controller.signal.aborted) setForecastLoading(false);
      }
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, forecastGap, gaps, refreshTrigger, backendUrl, authToken]);

  const riskLevel = forecast?.revenue_risk?.risk_level;
  const riskClass = (riskLevel && RISK_COLORS[riskLevel]) || "text-slate-400 bg-slate-500/10";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
          <TrendingUp className="w-5 h-5 text-cyan-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Forecast — Predictive Forecaster</h2>
          <p className="text-xs text-slate-400">predictive_forecaster</p>
        </div>
      </div>

      <div className="p-6 flex-1 flex items-center">
        {error ? (
          <div className="flex items-center gap-3 text-slate-400">
            <AlertCircle className="w-6 h-6 text-rose-500/50 shrink-0" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading ? (
          <div className="flex items-center gap-3 text-cyan-400">
            <Loader2 className="w-5 h-5 animate-spin" />
            <p className="text-sm font-medium">Checking forecast readiness...</p>
          </div>
        ) : forecastGap ? (
          <div className="flex items-center gap-3 w-full">
            <span className="w-10 h-10 rounded-lg bg-amber-500/10 text-amber-400 flex items-center justify-center shrink-0">
              <Lock className="w-5 h-5" />
            </span>
            <div>
              <p className="text-sm font-bold text-slate-100">{forecastGap.title}</p>
              <p className="text-xs text-slate-500 mt-1">{forecastGap.detail}</p>
            </div>
          </div>
        ) : forecastLoading ? (
          <div className="flex items-center gap-3 text-cyan-400">
            <Loader2 className="w-5 h-5 animate-spin" />
            <p className="text-sm font-medium">Generating forecast...</p>
          </div>
        ) : forecastError ? (
          <div className="flex items-center gap-3 text-slate-400">
            <AlertCircle className="w-6 h-6 text-rose-500/50 shrink-0" />
            <p className="text-sm">{forecastError}</p>
          </div>
        ) : forecast && forecast.status === "FORECASTED" ? (
          <div className="w-full space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Projected Next Quarter</p>
                <p className="text-xl font-bold text-slate-100">
                  {forecast.projected_q4_revenue != null ? `$${forecast.projected_q4_revenue.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Growth Rate / Period</p>
                <p className="text-xl font-bold text-slate-100 flex items-center gap-1.5">
                  {typeof forecast.projected_growth_rate === "number" && forecast.projected_growth_rate < 0 ? (
                    <TrendingDown className="w-4 h-4 text-rose-400" />
                  ) : (
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  )}
                  {typeof forecast.projected_growth_rate === "number" ? `${forecast.projected_growth_rate.toFixed(1)}%` : "—"}
                </p>
              </div>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500">
                Fit (r²): <span className="text-slate-300 font-mono">{forecast.r_squared?.toFixed(2) ?? "—"}</span>
              </span>
              {riskLevel && (
                <span className={`px-2 py-0.5 rounded font-semibold ${riskClass}`}>{riskLevel} risk</span>
              )}
            </div>
            <p className="text-[11px] text-slate-600 leading-relaxed">
              Based on {forecast.periods_used ?? "?"} month(s) of real ledger revenue, linear-trend regression.
              {forecast.revenue_risk?.note ? ` ${forecast.revenue_risk.note}` : ""}
            </p>
          </div>
        ) : (
          <div className="flex items-center gap-3 w-full">
            <span className="w-10 h-10 rounded-lg bg-slate-500/10 text-slate-400 flex items-center justify-center shrink-0">
              <TrendingUp className="w-5 h-5" />
            </span>
            <div>
              <p className="text-sm font-bold text-slate-100">No forecast available</p>
              <p className="text-xs text-slate-500 mt-1">{forecast?.projections?.[0] ?? "The forecast agent did not return a result."}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
