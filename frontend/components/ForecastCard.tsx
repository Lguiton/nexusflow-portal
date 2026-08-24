"use client";

import { useCallback, useEffect, useState } from "react";
import { Lock, TrendingUp, Loader2, AlertCircle } from "lucide-react";
import { useClientId } from "./ClientContext";

// Forecast status card. There is no dedicated "run the forecast" endpoint
// wired into this frontend yet -- predictive_forecaster is a real, tracked
// agent module (see backend/agent_registry.py's EXPECTED_AGENTS), but no
// route in backend/main.py currently exposes a forecast number to the
// dashboard. Rather than invent a number, this reuses the real, already-
// wired POST /api/v1/insights/known-gaps endpoint and looks for the real
// "forecast_insufficient_history" gap entry (see backend/gaps.py) that
// OnboardingChecklist.tsx already keys off of -- so the message shown here
// is always the backend's real, current reason, never a hardcoded "4 of 6
// months" placeholder.
interface Gap {
  key: string;
  title: string;
  detail: string;
}

interface KnownGapsResponse {
  gaps: Gap[];
}

interface ForecastCardProps {
  refreshTrigger?: number;
}

export default function ForecastCard({ refreshTrigger = 0 }: ForecastCardProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [gaps, setGaps] = useState<Gap[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchGaps = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/api/v1/insights/known-gaps`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
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
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchGaps(controller.signal);
    return () => controller.abort();
  }, [fetchGaps, refreshTrigger]);

  const forecastGap = gaps?.find((g) => g.key === "forecast_insufficient_history") ?? null;

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
        ) : (
          <div className="flex items-center gap-3 w-full">
            <span className="w-10 h-10 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center shrink-0">
              <TrendingUp className="w-5 h-5" />
            </span>
            <div>
              <p className="text-sm font-bold text-slate-100">Enough history is on file to forecast</p>
              <p className="text-xs text-slate-500 mt-1">This dashboard doesn't have a forecast number wired in yet -- predictive_forecaster has no endpoint exposed to the frontend today.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
