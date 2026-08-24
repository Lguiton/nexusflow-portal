"use client";

import { useCallback, useEffect, useState } from "react";
import { ListChecks, Loader2, AlertCircle, CheckCircle2, Circle, Lock } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-05: lightweight first-insight onboarding checklist. Per founder
// decision (2026-08-23), this is a progress checklist, not a full guided
// modal tour -- pure frontend, reusing two endpoints that already exist
// (/api/v1/finance/kpi-summary and /api/v1/insights/known-gaps) rather than
// adding a new one. Every checklist item's status is derived from real
// signals already computed elsewhere, never a fabricated "you did this"
// flag.
interface KpiSummary {
  ledger_row_count: number;
}

interface KnownGap {
  key: string;
  title: string;
  detail: string;
}

interface KnownGapsResponse {
  row_count: number;
  gaps: KnownGap[];
}

type ItemStatus = "done" | "available" | "locked";

interface ChecklistItem {
  key: string;
  title: string;
  detail: string;
  status: ItemStatus;
}

interface OnboardingChecklistProps {
  refreshTrigger?: number;
}

export default function OnboardingChecklist({ refreshTrigger = 0 }: OnboardingChecklistProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [items, setItems] = useState<ChecklistItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProgress = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const headers = {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      };
      const [kpiRes, gapsRes] = await Promise.all([
        fetch(`${backendUrl}/api/v1/finance/kpi-summary`, { method: "POST", headers, body: JSON.stringify({}), signal }),
        fetch(`${backendUrl}/api/v1/insights/known-gaps`, { method: "POST", headers, body: JSON.stringify({}), signal }),
      ]);
      if (!kpiRes.ok) throw new Error(`KPI summary lookup failed: ${kpiRes.status}`);
      if (!gapsRes.ok) throw new Error(`Known gaps lookup failed: ${gapsRes.status}`);

      const kpi: KpiSummary = await kpiRes.json();
      const gapsData: KnownGapsResponse = await gapsRes.json();
      const gapKeys = new Set(gapsData.gaps.map((g) => g.key));

      const hasData = (kpi.ledger_row_count ?? 0) > 0;
      const mrrUnlocked = hasData && !gapKeys.has("mrr_unavailable");
      const forecastUnlocked = hasData && !gapKeys.has("forecast_insufficient_history");

      const built: ChecklistItem[] = [
        {
          key: "upload_data",
          title: "Upload your ledger data",
          detail: hasData
            ? `${kpi.ledger_row_count} row(s) on file.`
            : "Upload a CSV to unlock CFO briefings, forecasts, and the rest of this dashboard.",
          status: hasData ? "done" : "available",
        },
        {
          key: "mrr",
          title: "Unlock real Monthly Recurring Revenue",
          detail: mrrUnlocked
            ? "MRR is being tracked from your recurring-flagged rows."
            : "Include a 'recurring' or 'is_recurring' column on your next upload to unlock true MRR.",
          status: !hasData ? "locked" : mrrUnlocked ? "done" : "available",
        },
        {
          key: "forecast",
          title: "Unlock 12-month forecasting",
          detail: forecastUnlocked
            ? "You have enough monthly history for statistically meaningful forecasts."
            : "Keep uploading -- forecasting unlocks once enough distinct months of history are on file.",
          status: !hasData ? "locked" : forecastUnlocked ? "done" : "available",
        },
      ];
      setItems(built);
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Onboarding checklist fetch failed:", err);
      setError(err.message || "Unable to load onboarding progress right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchProgress(controller.signal);
    return () => controller.abort();
  }, [fetchProgress, refreshTrigger]);

  const doneCount = (items ?? []).filter((i) => i.status === "done").length;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
            <ListChecks className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Getting Started</h2>
            <p className="text-xs text-slate-400">Your progress unlocking NexusFlow's analysis</p>
          </div>
        </div>
        {items && (
          <span className="text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-2.5 py-1 shrink-0">
            {doneCount}/{items.length}
          </span>
        )}
      </div>

      <div className="p-6 flex-1">
        {error ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !items ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-emerald-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Checking your progress...</p>
          </div>
        ) : (
          <ul className="space-y-3 animate-in fade-in duration-500">
            {(items ?? []).map((item) => (
              <li key={item.key} className="flex items-start gap-3">
                {item.status === "done" ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                ) : item.status === "locked" ? (
                  <Lock className="w-5 h-5 text-slate-600 shrink-0 mt-0.5" />
                ) : (
                  <Circle className="w-5 h-5 text-slate-500 shrink-0 mt-0.5" />
                )}
                <div className="min-w-0">
                  <p className={`text-sm font-medium ${item.status === "done" ? "text-slate-300 line-through decoration-slate-600" : item.status === "locked" ? "text-slate-500" : "text-slate-200"}`}>
                    {item.title}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">{item.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
