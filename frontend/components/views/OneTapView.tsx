"use client";

import React, { useState } from "react";
import {
  Sparkles,
  TrendingUp,
  BarChart3,
  ShieldAlert,
  Compass,
  FileText,
  Loader2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ArrowUpRight,
} from "lucide-react";
import { useClientId } from "../ClientContext";
import type { ViewId } from "../AppShell";

// Task 58 (UX-06): the SMB "One-Tap Interface". Six fixed buttons, each
// bound to a real, already-live backend endpoint -- no new agents, no
// new business logic, just a simplified front door onto work every one
// of these endpoints already does elsewhere in the console. The
// six-button-to-endpoint mapping below is the actual product decision
// that was previously lost (see docs/Eivanta_Session_Handoff_26Aug2026.md,
// Task 58) -- it was rebuilt with the founder rather than guessed, and
// this file is now the durable record of that mapping.
//
// Per the founder's explicit choice: results stay plain text/metrics (no
// embedded charts here -- that's what the Analytics/Ledger tabs are for),
// and a "View full analytics" / "View in Ledger" link is offered on the
// three buttons where a fuller chart view already exists, rather than
// duplicating chart rendering in two places.
type ButtonId = "cfo_briefing" | "forecast" | "numbers" | "expense_scan" | "strategy" | "report";

interface ButtonConfig {
  id: ButtonId;
  label: string;
  description: string;
  endpoint: string;
  icon: React.ElementType;
  linkView?: ViewId;
  linkLabel?: string;
}

const BUTTONS: ButtonConfig[] = [
  {
    id: "cfo_briefing",
    label: "How's my business doing?",
    description: "A quick executive read on margin, burn, and cash runway.",
    endpoint: "/api/v1/finance/cfo-briefing",
    icon: Sparkles,
    linkView: "analytics",
    linkLabel: "View full analytics",
  },
  {
    id: "forecast",
    label: "What's coming next month?",
    description: "A revenue trend forecast built from your ledger history.",
    endpoint: "/api/v1/predictive/forecast",
    icon: TrendingUp,
    linkView: "analytics",
    linkLabel: "View full analytics",
  },
  {
    id: "numbers",
    label: "Show me my numbers",
    description: "Total revenue, expenses, and net profit at a glance.",
    endpoint: "/api/v1/finance/analytics-summary",
    icon: BarChart3,
    linkView: "analytics",
    linkLabel: "View full analytics",
  },
  {
    id: "expense_scan",
    label: "Scan my expenses for red flags",
    description: "A statistical anomaly check across your expense categories.",
    endpoint: "/api/v1/finance/comptroller-audit",
    icon: ShieldAlert,
    linkView: "ledger",
    linkLabel: "View transactions in Ledger",
  },
  {
    id: "strategy",
    label: "What should I do next?",
    description: "A data-grounded strategic recommendation for your business.",
    endpoint: "/api/v1/saas/strategy",
    icon: Compass,
  },
  {
    id: "report",
    label: "Generate a report I can share",
    description: "A stakeholder-ready summary you can hand off.",
    endpoint: "/api/v1/reports/stakeholder",
    icon: FileText,
  },
];

interface ResultState {
  loading: boolean;
  error: string | null;
  data: any | null;
}

interface OneTapViewProps {
  onNavigateToView?: (view: ViewId) => void;
}

export default function OneTapView({ onNavigateToView }: OneTapViewProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const [expandedId, setExpandedId] = useState<ButtonId | null>(null);
  const [results, setResults] = useState<Partial<Record<ButtonId, ResultState>>>({});

  const runButton = async (btn: ButtonConfig) => {
    if (expandedId === btn.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(btn.id);

    // Don't re-run a call that already succeeded this session -- a tap
    // that re-opens an already-answered card should feel instant, and
    // every one of these endpoints is a real (sometimes budget-gated LLM)
    // call, not a free cache lookup.
    const existing = results[btn.id];
    if (existing && !existing.error && !existing.loading) return;

    setResults((prev) => ({ ...prev, [btn.id]: { loading: true, error: null, data: null } }));
    try {
      const res = await fetch(`${backendUrl}${btn.endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
      });
      if (res.status === 402) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Monthly AI usage cap reached.");
      }
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      const data = await res.json();
      setResults((prev) => ({ ...prev, [btn.id]: { loading: false, error: null, data } }));
    } catch (err: any) {
      setResults((prev) => ({
        ...prev,
        [btn.id]: { loading: false, error: err?.message || "Something went wrong. Please try again.", data: null },
      }));
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-white">One-Tap Insights</h2>
        <p className="text-sm text-slate-400">
          Tap a question for an instant, real answer pulled from your own data -- no dashboards to navigate.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {BUTTONS.map((btn) => {
          const Icon = btn.icon;
          const isOpen = expandedId === btn.id;
          const result = results[btn.id];
          return (
            <div key={btn.id} className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
              <button
                onClick={() => runButton(btn)}
                className="w-full flex items-center gap-3 p-5 text-left hover:bg-slate-800/50 transition-colors"
              >
                <div className="p-2 bg-teal-500/10 border border-teal-500/20 rounded-lg shrink-0">
                  <Icon className="w-5 h-5 text-teal-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-bold text-white">{btn.label}</h3>
                  <p className="text-xs text-slate-500">{btn.description}</p>
                </div>
                {isOpen ? (
                  <ChevronUp className="w-4 h-4 text-slate-500 shrink-0" />
                ) : (
                  <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
                )}
              </button>

              {isOpen && (
                <div className="border-t border-slate-800 p-5 bg-slate-950/40">
                  {result?.loading ? (
                    <div className="flex items-center gap-2 text-teal-400 text-sm">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Working on it...
                    </div>
                  ) : result?.error ? (
                    <div className="flex items-center gap-2 text-rose-400 text-sm">
                      <AlertCircle className="w-4 h-4 shrink-0" />
                      {result.error}
                    </div>
                  ) : result?.data ? (
                    <ResultRenderer buttonId={btn.id} data={result.data} />
                  ) : null}

                  {btn.linkView && onNavigateToView && (
                    <button
                      onClick={() => onNavigateToView(btn.linkView as ViewId)}
                      className="mt-4 flex items-center gap-1 text-xs text-teal-400 hover:text-teal-300 transition-colors"
                    >
                      {btn.linkLabel}
                      <ArrowUpRight className="w-3 h-3" />
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</p>
      <p className="text-base font-bold text-slate-100">{value}</p>
    </div>
  );
}

function InsightList({ items }: { items: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="space-y-1.5 text-xs text-slate-300 leading-relaxed">
      {items.map((s, i) => (
        <li key={i}>• {s}</li>
      ))}
    </ul>
  );
}

function fmtUsd(n: unknown): string {
  const num = Number(n);
  return Number.isFinite(num) ? `$${num.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—";
}

function ResultRenderer({ buttonId, data }: { buttonId: ButtonId; data: any }) {
  switch (buttonId) {
    case "cfo_briefing":
      return <CfoBriefingResult data={data} />;
    case "forecast":
      return <ForecastResult data={data} />;
    case "numbers":
      return <NumbersResult data={data} />;
    case "expense_scan":
      return <ExpenseScanResult data={data} />;
    case "strategy":
      return <StrategyResult data={data} />;
    case "report":
      return <ReportResult data={data} />;
    default:
      return null;
  }
}

// backend/agents/virtual_cfo.py generate_cfo_briefing: { status?, metrics:
// {gross_margin, burn_rate, cash_runway_months}, insights: string[] }.
// NO_DATA/ERROR states already return a self-explanatory insights[0], so
// this renders whatever came back rather than special-casing each status.
function CfoBriefingResult({ data }: { data: any }) {
  const metrics = data?.metrics ?? {};
  const hasMetrics = metrics.gross_margin != null || metrics.burn_rate != null || metrics.cash_runway_months != null;
  return (
    <div className="space-y-3">
      {hasMetrics && (
        <div className="grid grid-cols-3 gap-3">
          <Metric label="Gross Margin" value={metrics.gross_margin != null ? `${metrics.gross_margin}%` : "—"} />
          <Metric label="Monthly Burn" value={metrics.burn_rate != null ? fmtUsd(metrics.burn_rate) : "—"} />
          <Metric label="Cash Runway" value={metrics.cash_runway_months != null ? `${metrics.cash_runway_months} mo` : "—"} />
        </div>
      )}
      <InsightList items={data?.insights ?? []} />
    </div>
  );
}

// backend/agents/predictive_forecaster.py generate_forecast: only
// status === "FORECASTED" carries real projection numbers; every other
// status (insufficient history, error) carries its explanation in
// projections[0] instead -- same pattern ForecastCard.tsx already uses.
function ForecastResult({ data }: { data: any }) {
  if (data?.status !== "FORECASTED") {
    return <p className="text-xs text-slate-400">{data?.projections?.[0] ?? "Not enough ledger history yet for a forecast."}</p>;
  }
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Metric label="Projected Next Quarter" value={data.projected_q4_revenue != null ? fmtUsd(data.projected_q4_revenue) : "—"} />
        <Metric
          label="Growth Rate / Period"
          value={typeof data.projected_growth_rate === "number" ? `${data.projected_growth_rate.toFixed(1)}%` : "—"}
        />
      </div>
      <p className="text-[11px] text-slate-500">
        Based on {data.periods_used ?? "?"} month(s) of ledger revenue. Fit (r²): {typeof data.r_squared === "number" ? data.r_squared.toFixed(2) : "—"}.
        {data.revenue_risk?.note ? ` ${data.revenue_risk.note}` : ""}
      </p>
    </div>
  );
}

// /api/v1/finance/analytics-summary: pure arithmetic, no LLM -- { status,
// total_revenue, total_expense, net_profit, trend_note }.
function NumbersResult({ data }: { data: any }) {
  if (data?.status === "NO_DATA") {
    return <p className="text-xs text-slate-400">{data.trend_note}</p>;
  }
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <Metric label="Revenue" value={fmtUsd(data?.total_revenue ?? 0)} />
        <Metric label="Expenses" value={fmtUsd(data?.total_expense ?? 0)} />
        <Metric label="Net Profit" value={fmtUsd(data?.net_profit ?? 0)} />
      </div>
      {data?.trend_note && <p className="text-[11px] text-slate-500">{data.trend_note}</p>}
    </div>
  );
}

// /api/v1/finance/comptroller-audit: real z-score anomaly check, no LLM --
// { total_transactions_audited, flagged_count, expense_breakdown_by_category,
// flagged_items, audit_status }.
function ExpenseScanResult({ data }: { data: any }) {
  if (data?.audit_status === "NO_DATA") {
    return <p className="text-xs text-slate-400">No ledger data has been ingested yet.</p>;
  }
  const flagged: any[] = data?.flagged_items ?? [];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Metric label="Transactions Audited" value={String(data?.total_transactions_audited ?? 0)} />
        <Metric label="Flagged" value={String(data?.flagged_count ?? 0)} />
      </div>
      {flagged.length === 0 ? (
        <p className="text-xs text-emerald-400">No anomalies found -- expenses look consistent with category norms.</p>
      ) : (
        <ul className="space-y-1.5 text-xs text-slate-300">
          {flagged.slice(0, 5).map((item, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <span className="text-rose-400 shrink-0">⚠</span>
              <span>
                {fmtUsd(item.amount)} in {item.category} — {item.reason}
              </span>
            </li>
          ))}
          {flagged.length > 5 && <li className="text-slate-500">+{flagged.length - 5} more</li>}
        </ul>
      )}
    </div>
  );
}

// backend/agents/saas_strategist.py generate_strategy: { agent, status,
// strategies: string[], metrics? }.
function StrategyResult({ data }: { data: any }) {
  return <InsightList items={data?.strategies ?? []} />;
}

// backend/agents/report_generator.py generate_stakeholder_report: { agent,
// status, summary_metrics: {total_revenue, total_expenses, net_income,
// records_audited, top_category, revenue_trend_pct}, executive_sections:
// [{title, summary}] }.
function ReportResult({ data }: { data: any }) {
  const metrics = data?.summary_metrics ?? {};
  const sections: any[] = data?.executive_sections ?? [];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Metric label="Total Revenue" value={metrics.total_revenue != null ? fmtUsd(metrics.total_revenue) : "—"} />
        <Metric label="Net Income" value={metrics.net_income != null ? fmtUsd(metrics.net_income) : "—"} />
      </div>
      <div className="space-y-2">
        {sections.map((sec, i) => (
          <div key={i}>
            <p className="text-xs font-bold text-slate-200">{sec.title}</p>
            <p className="text-xs text-slate-400 leading-relaxed">{sec.summary}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
