"use client";

import { useCallback, useEffect, useState } from "react";
import { BarChart3, RefreshCw, Loader2, AlertCircle, Sparkles } from 'lucide-react';
import { useClientId } from "./ClientContext";
import DynamicChartEngine from "./DynamicChartEngine";
import CategoryChartPicker from "./CategoryChartPicker";
import MonthlyTrendPicker from "./MonthlyTrendPicker";

// Real replacement for the deleted MRRChartWidget.tsx (which was 100%
// hardcoded mock pie/bar data under an "MRR" label) -- this widget fetches
// the real /api/v1/bi/chart-suite endpoint (backed by
// bi_visualization_architect.generate_chart_suite, grounded entirely in
// this tenant's actual ledger data via db_manager) and renders whichever
// of the charts that endpoint returns:
//   - category_breakdown: pie/pareto (recommended) from real category
//     totals, with a picker for bar/pie/donut/pareto/stacked/box
//   - monthly_trend: real monthly revenue (only present once 2+ distinct
//     months are on file), with a line/area picker
//   - amount_distribution: a real transaction-amount histogram
//   - category_monthly_breakdown: real category totals broken out by
//     month -- not rendered as its own tile, folded into the category
//     picker's "Stacked" view (same category dimension as
//     category_breakdown, just a second real dataset backing one more
//     way to look at it)
//   - category_amount_stats: real per-category min/Q1/median/Q3/max --
//     likewise folded into the category picker's "Box Plot" view instead
//     of a separate tile
// Each panel is rendered only if the backend actually included it; there
// is no client-side fallback data of any kind.

interface ChartSection {
  chart_type: 'bar' | 'pie' | 'stacked_bar' | 'pareto' | 'line' | 'histogram';
  config: { xAxisKey: string; dataKeys: string[] };
  data: any[];
}

// The two category-picker-only sections never reach DynamicChartEngine (see
// FOLDED_INTO_CATEGORY_PICKER below), so they don't need a chart_type at
// all -- CategoryChartPicker's own stackedSection/boxSection props only
// look at config/data.
interface ChartSectionLike {
  config: { xAxisKey: string; dataKeys: string[] };
  data: any[];
}

interface ChartSuitePayload {
  agent: string;
  status: string;
  charts: {
    category_breakdown?: ChartSection;
    monthly_trend?: ChartSection;
    amount_distribution?: ChartSection;
    category_monthly_breakdown?: ChartSectionLike;
    category_amount_stats?: ChartSectionLike;
  };
  insights: string[];
}

interface DataVisualizationWidgetProps {
  refreshTrigger?: number;
}

const PANEL_TITLES: Record<string, string> = {
  category_breakdown: "Revenue & Cost by Category",
  monthly_trend: "Monthly Revenue Trend",
  amount_distribution: "Transaction Amount Distribution",
};

// These two keys are real chart-suite sections, but they're rendered as
// extra VIEWS inside the category_breakdown tile (via CategoryChartPicker)
// rather than as their own separate tiles -- see the module comment above.
const FOLDED_INTO_CATEGORY_PICKER = new Set(["category_monthly_breakdown", "category_amount_stats"]);

export default function DataVisualizationWidget({ refreshTrigger = 0 }: DataVisualizationWidgetProps) {
  const clientCtx = useClientId() as any;
  const currentClientId = clientCtx?.clientId || "CLI-001";
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [data, setData] = useState<ChartSuitePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchChartSuite = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;

    setLoading(true);
    setError(null);

    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/api/v1/bi/chart-suite`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        signal,
      });

      if (!response.ok) {
        throw new Error(`Chart suite request failed: ${response.status}`);
      }

      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Chart suite fetch failed:", err);
      setError(err.message || "Chart data is currently unavailable.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchChartSuite(controller.signal);
    return () => controller.abort();
  }, [fetchChartSuite, refreshTrigger]);

  const chartEntries = data
    ? (Object.entries(data.charts || {}) as Array<[string, ChartSection]>)
        .filter(([key]) => !FOLDED_INTO_CATEGORY_PICKER.has(key))
    : [];

  const stackedSection = data?.charts?.category_monthly_breakdown ?? null;
  const boxSection = data?.charts?.category_amount_stats ?? null;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
            <BarChart3 className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              Data Visualization Suite (Agent #0?)
            </h2>
            <p className="text-xs text-slate-400">Real charts grounded in this tenant's actual ledger data</p>
          </div>
        </div>

        <button
          onClick={() => fetchChartSuite()}
          disabled={loading}
          className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed border border-slate-700"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          Refresh Charts
        </button>
      </div>

      <div className="p-6 flex-1 flex flex-col">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 py-8 gap-3">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center h-full text-cyan-400 py-8 gap-3">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Building charts from real ledger data...</p>
          </div>
        ) : data?.status === "NO_DATA" ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 py-8 gap-3 text-center">
            <BarChart3 className="w-8 h-8 text-slate-600" />
            <p className="text-sm">{data.insights?.[0] || "No ledger data has been ingested yet for this tenant."}</p>
          </div>
        ) : data?.status === "ERROR" ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 py-8 gap-3 text-center">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{data.insights?.[0] || "Chart generation failed."}</p>
          </div>
        ) : (
          <div className="space-y-8 animate-in fade-in duration-500 flex-1">
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              {chartEntries.map(([key, section]) => (
                <div key={key} className="bg-slate-950/50 border border-slate-800/80 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-slate-300 mb-3">
                    {/* eslint-disable-next-line security/detect-object-injection -- key is a backend chart-section name used only to look up a display label in a fixed local table, with a safe string fallback -- a read, not a write, so no prototype-sensitive effect */}
                    {PANEL_TITLES[key] || key}
                  </h3>
                  {key === "category_breakdown" ? (
                    // Real category totals, plus two more real datasets
                    // (stacked-by-month, per-category spread) folded into
                    // the same picker -- see FOLDED_INTO_CATEGORY_PICKER
                    // above for why those aren't separate tiles.
                    <CategoryChartPicker
                      data={section.data}
                      config={section.config}
                      stackedSection={stackedSection}
                      boxSection={boxSection}
                    />
                  ) : key === "monthly_trend" ? (
                    // Same real single-series monthly data, with a
                    // line/area toggle instead of the fixed line render.
                    <MonthlyTrendPicker data={section.data} config={section.config} />
                  ) : (
                    <DynamicChartEngine
                      chartType={section.chart_type}
                      data={section.data}
                      config={section.config}
                    />
                  )}
                </div>
              ))}
            </div>

            {data?.insights && data.insights.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-cyan-400" />
                  What the real data shows
                </h3>
                <div className="space-y-2">
                  {data.insights.map((insight, idx) => (
                    <p key={idx} className="text-sm text-slate-400 bg-slate-800/30 p-3 rounded-lg border border-slate-700/30">
                      {insight}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
