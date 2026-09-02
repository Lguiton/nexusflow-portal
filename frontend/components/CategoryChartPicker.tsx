"use client";

import React, { useMemo, useState } from "react";
import {
  BarChart, Bar, PieChart, Pie, Cell, ComposedChart, Line, Rectangle,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import {
  BarChart3, PieChart as PieIcon, Circle as DonutIcon, TrendingUp,
  Layers, BoxSelect, ChevronDown,
} from "lucide-react";
import BoxPlotChart from "./BoxPlotChart";

// Category Insights chart-type picker. The core (Bar / Pie / Donut /
// Pareto) reads the same real category_breakdown data POST
// /api/v1/bi/chart-suite already returns (grounded in this tenant's
// actual ledger, via bi_visualization_architect) -- just a client-side
// toggle over how that one dataset is drawn.
//
// Stacked and Box Plot are different: they read two ADDITIONAL real
// datasets (category_monthly_breakdown, category_amount_stats) that the
// backend only includes once there's enough real data to back them (see
// generate_chart_suite's gating). Their option is only shown at all when
// that data is actually present -- no option here ever renders a chart
// with fabricated or borrowed-from-elsewhere data.
//
// Deliberately no "Histogram" option here. A histogram of per-transaction
// amounts is a genuinely different dataset (transaction count per amount
// bucket) from category totals -- that's already its own real panel
// below ("Transaction Amount Distribution"). Toggling this picker to
// "Histogram" would have silently swapped in unrelated data under a
// chart-type label.
const COLORS = ["#5b6ef0", "#7d8cf5", "#f2596b", "#8b6ef5", "#f0a93b", "#2fd199", "#33c1f0", "#5fd3ff"];

type ChartKind = "bar" | "pie" | "donut" | "pareto" | "stacked" | "box";

// BUG FIX (27 Aug 2026): the Bar view's YAxis had no tickFormatter at all --
// every other chart on the dashboard (Transaction Scatter, Pareto's left
// axis) formats its numbers as currency, but this one showed bare signed
// integers. Harmless in itself, but category_breakdown mixes positive
// revenue and negative expense totals (see the directionalBarShape note
// below), so a negative tick renders as e.g. "-40000" with no "$" -- easy
// to misread as a second positive tick, especially once real screenshots
// get cropped and the leading "-" sits right at the crop edge. Confirmed
// via a live render: without this formatter the axis is numerically
// correct and monotonic, but visually ambiguous. maximumFractionDigits: 0
// matches the Pie/Donut tooltip's existing currency formatting elsewhere
// in this same file.
const formatCurrencyTick = (v: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);

// BUG FIX (confirmed live 26 Aug 2026): category_breakdown mixes revenue
// (positive) and expense (negative) category totals. Recharts draws a
// negative bar's rectangle downward from the zero baseline -- its "top"
// edge (in the [topLeft, topRight, bottomRight, bottomLeft] radius sense)
// sits AT the baseline, and its "bottom" edge is the bar's actual tip, far
// from zero. A fixed radius=[4,4,0,0] rounds the corners nearest zero
// regardless of sign, which is correct for a positive bar (tip is at the
// top) but rounds the WRONG end of a negative bar -- confirmed via a
// rendered repro against this tenant's real data: the large negative
// Payroll bar had its near-zero end rounded and its actual tip left sharp,
// reading as visually "flipped" next to every positive bar in the same
// chart. This swaps which end gets rounded based on the real signed value,
// so the rounded end is always the bar's tip, never its base.
const directionalBarShape = (key: string) => (props: any) => {
  const { x, y, width, height, payload, fill } = props;
  // eslint-disable-next-line security/detect-object-injection -- key is a dataKeys entry from the typed config prop the parent sets internally, never external input
  const value = payload?.[key] ?? 0;
  const radius: [number, number, number, number] = value < 0 ? [0, 0, 4, 4] : [4, 4, 0, 0];
  return <Rectangle x={x} y={y} width={width} height={height} radius={radius} fill={fill} />;
};

interface ChartSectionLike {
  config: { xAxisKey: string; dataKeys: string[] };
  data: any[];
}

interface CategoryChartPickerProps {
  data: any[];
  config: { xAxisKey: string; dataKeys: string[] };
  // Real category-by-month totals, powering the Stacked view -- omitted
  // (null/undefined) when the backend withheld it (fewer than 2 months or
  // only 1 category on file). See db_manager.get_category_monthly_breakdown.
  stackedSection?: ChartSectionLike | null;
  // Real per-category min/Q1/median/Q3/max, powering the Box Plot view --
  // omitted when there's no category data to summarize. See
  // db_manager.get_category_amount_stats.
  boxSection?: ChartSectionLike | null;
}

export default function CategoryChartPicker({ data, config, stackedSection, boxSection }: CategoryChartPickerProps) {
  const hasStacked = !!stackedSection?.data?.length;
  const hasBox = !!boxSection?.data?.length;

  const OPTIONS = useMemo(() => {
    const base: { id: ChartKind; label: string; icon: React.ElementType }[] = [
      { id: "bar", label: "Bar", icon: BarChart3 },
      { id: "pie", label: "Pie", icon: PieIcon },
      { id: "donut", label: "Donut", icon: DonutIcon },
      { id: "pareto", label: "Pareto", icon: TrendingUp },
    ];
    if (hasStacked) base.push({ id: "stacked", label: "Stacked", icon: Layers });
    if (hasBox) base.push({ id: "box", label: "Box Plot", icon: BoxSelect });
    return base;
  }, [hasStacked, hasBox]);

  const [kind, setKind] = useState<ChartKind>("bar");
  const [open, setOpen] = useState(false);
  const valueKey = config.dataKeys[0];

  const paretoData = useMemo(() => {
    // eslint-disable-next-line security/detect-object-injection -- valueKey is config.dataKeys[0], from the typed config prop the parent sets internally, never external input
    const sorted = [...data].sort((a, b) => Math.abs(b[valueKey] ?? 0) - Math.abs(a[valueKey] ?? 0));
    // eslint-disable-next-line security/detect-object-injection -- valueKey is config.dataKeys[0], from the typed config prop the parent sets internally, never external input
    const total = sorted.reduce((sum, row) => sum + Math.abs(row[valueKey] ?? 0), 0);
    let running = 0;
    return sorted.map((row) => {
      // eslint-disable-next-line security/detect-object-injection -- valueKey is config.dataKeys[0], from the typed config prop the parent sets internally, never external input
      running += Math.abs(row[valueKey] ?? 0);
      return { ...row, cumulative_pct: total > 0 ? Math.round((running / total) * 1000) / 10 : 0 };
    });
  }, [data, valueKey]);

  // BUG FIX (confirmed live 26 Aug 2026): category_breakdown mixes revenue
  // (positive) and expense (negative) category totals in one chart -- a pie
  // slice's size can't be negative, so Pie/Donut rendered nothing but their
  // legend for any tenant with both revenue and expense categories (i.e.
  // every real tenant). Confirmed via a rendered repro against this
  // tenant's real category_breakdown before this fix: blank chart area,
  // legend only. Fixed by sizing slices on magnitude (Math.abs) so every
  // category actually renders a slice; the tooltip below still shows the
  // REAL signed dollar amount (via _realAmount, not the magnitude used for
  // sizing), so a slice never gets relabeled as if it were revenue.
  const pieData = useMemo(
    // eslint-disable-next-line security/detect-object-injection -- valueKey is config.dataKeys[0], from the typed config prop the parent sets internally, never external input
    () => data.map((row) => ({ ...row, _magnitude: Math.abs(row[valueKey] ?? 0), _realAmount: row[valueKey] ?? 0 })),
    [data, valueKey]
  );
  const pieTooltipFormatter = (value: any, name: any, itemProps: any) => {
    const real = itemProps?.payload?._realAmount ?? value;
    const formatted = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(real);
    return [formatted, name];
  };

  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-sm p-4 text-center font-mono">No data available for visualization.</div>;
  }

  // The selected view can become unavailable if the backing data
  // disappears on a refresh (e.g. a stacked view mid-select while a
  // re-fetch drops below the 2-month floor) -- fall back to Bar rather
  // than render a stale/empty chart under a label that no longer applies.
  const activeOption = OPTIONS.find((o) => o.id === kind) ?? OPTIONS[0];
  const effectiveKind = activeOption.id;

  return (
    <div>
      <div className="flex items-center justify-end mb-2 relative">
        <button
          className="flex items-center gap-1.5 text-xs font-semibold bg-slate-950 border border-slate-700 rounded-full px-3 py-1.5 text-slate-200 hover:border-cyan-500/50"
          onClick={() => setOpen((o) => !o)}
        >
          <activeOption.icon className="w-3.5 h-3.5 text-slate-400" />
          {activeOption.label}
          <ChevronDown className={`w-3 h-3 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        {open && (
          <div className="absolute top-full right-0 mt-1.5 z-10 bg-slate-800 border border-slate-700 rounded-lg p-1 flex flex-col min-w-[130px] shadow-xl">
            {OPTIONS.map((opt) => (
              <button
                key={opt.id}
                className={`flex items-center gap-2 px-2.5 py-2 rounded-md text-xs font-medium text-left ${effectiveKind === opt.id ? "bg-cyan-500/15 text-cyan-300" : "text-slate-300 hover:bg-slate-700"}`}
                onClick={() => { setKind(opt.id); setOpen(false); }}
              >
                <opt.icon className="w-3.5 h-3.5" />
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {effectiveKind === "bar" && (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey={config.xAxisKey} stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} tickFormatter={formatCurrencyTick} width={64} />
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} cursor={{ fill: "#1e293b" }} formatter={(value: any) => formatCurrencyTick(Number(value))} />
            <Bar dataKey={valueKey} shape={directionalBarShape(valueKey)}>
              {data.map((_, idx) => <Cell key={idx} fill={COLORS[idx % COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}

      {effectiveKind === "pie" && (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={pieData} cx="50%" cy="50%" outerRadius={90} paddingAngle={2} dataKey="_magnitude" nameKey={config.xAxisKey}>
              {pieData.map((_, idx) => <Cell key={idx} fill={COLORS[idx % COLORS.length]} />)}
            </Pie>
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} formatter={pieTooltipFormatter} />
            <Legend wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }} />
          </PieChart>
        </ResponsiveContainer>
      )}
      {effectiveKind === "pie" && (
        <p className="text-[10px] text-slate-500 mt-1 text-center">
          Slice size reflects dollar magnitude, revenue and expense categories combined -- hover a slice for its real signed amount.
        </p>
      )}

      {effectiveKind === "donut" && (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={80} paddingAngle={4} dataKey="_magnitude" nameKey={config.xAxisKey}>
              {pieData.map((_, idx) => <Cell key={idx} fill={COLORS[idx % COLORS.length]} />)}
            </Pie>
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} formatter={pieTooltipFormatter} />
            <Legend wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }} />
          </PieChart>
        </ResponsiveContainer>
      )}
      {effectiveKind === "donut" && (
        <p className="text-[10px] text-slate-500 mt-1 text-center">
          Slice size reflects dollar magnitude, revenue and expense categories combined -- hover a slice for its real signed amount.
        </p>
      )}

      {effectiveKind === "pareto" && (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={paretoData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey={config.xAxisKey} stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis yAxisId="left" stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} tickFormatter={formatCurrencyTick} width={64} />
            <YAxis yAxisId="right" orientation="right" stroke="#2fd199" fontSize={11} tickLine={false} axisLine={false} domain={[0, 100]} unit="%" />
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} />
            <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
            <Bar yAxisId="left" dataKey={valueKey} name="Category total" fill="#5b6ef0" shape={directionalBarShape(valueKey)} />
            <Line yAxisId="right" type="monotone" dataKey="cumulative_pct" name="Cumulative %" stroke="#2fd199" strokeWidth={2.5} dot={{ r: 3, fill: "#0f172a", strokeWidth: 2, stroke: "#2fd199" }} />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {effectiveKind === "stacked" && hasStacked && (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={stackedSection!.data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey={stackedSection!.config.xAxisKey} stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} tickFormatter={formatCurrencyTick} width={64} />
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} cursor={{ fill: "#1e293b" }} />
            <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
            {stackedSection!.config.dataKeys.map((cat, idx) => (
              <Bar key={cat} dataKey={cat} stackId="category-months" fill={COLORS[idx % COLORS.length]} radius={idx === stackedSection!.config.dataKeys.length - 1 ? [4, 4, 0, 0] : undefined} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}

      {effectiveKind === "box" && hasBox && <BoxPlotChart data={boxSection!.data} />}
    </div>
  );
}
