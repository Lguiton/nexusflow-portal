"use client";

import React, { useMemo, useState } from "react";
import {
  BarChart, Bar, PieChart, Pie, Cell, ComposedChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { BarChart3, PieChart as PieIcon, TrendingUp, ChevronDown } from "lucide-react";

// Category Insights chart-type picker. Same real category_breakdown data
// POST /api/v1/bi/chart-suite already returns (grounded in this tenant's
// actual ledger, via bi_visualization_architect) -- this only adds a
// client-side toggle over how that one dataset is drawn.
//
// Deliberately Bar / Pie / Pareto, not the four options (including
// Histogram) sketched in the earlier static mockup. A histogram of
// per-transaction amounts is a genuinely different dataset (transaction
// count per amount bucket) from category totals -- that's already its own
// real panel below ("Transaction Amount Distribution"). Toggling this
// picker to "Histogram" would have silently swapped in unrelated data
// under a chart-type label, which isn't something to wire into real
// production code even though it looked fine in a static mockup.
const COLORS = ["#5b6ef0", "#7d8cf5", "#f2596b", "#f2596b", "#f0a93b", "#2fd199", "#33c1f0"];

type ChartKind = "bar" | "pie" | "pareto";

const OPTIONS: { id: ChartKind; label: string; icon: React.ElementType }[] = [
  { id: "bar", label: "Bar", icon: BarChart3 },
  { id: "pie", label: "Pie", icon: PieIcon },
  { id: "pareto", label: "Pareto", icon: TrendingUp },
];

interface CategoryChartPickerProps {
  data: any[];
  config: { xAxisKey: string; dataKeys: string[] };
}

export default function CategoryChartPicker({ data, config }: CategoryChartPickerProps) {
  const [kind, setKind] = useState<ChartKind>("bar");
  const [open, setOpen] = useState(false);
  const valueKey = config.dataKeys[0];

  const paretoData = useMemo(() => {
    const sorted = [...data].sort((a, b) => Math.abs(b[valueKey] ?? 0) - Math.abs(a[valueKey] ?? 0));
    const total = sorted.reduce((sum, row) => sum + Math.abs(row[valueKey] ?? 0), 0);
    let running = 0;
    return sorted.map((row) => {
      running += Math.abs(row[valueKey] ?? 0);
      return { ...row, cumulative_pct: total > 0 ? Math.round((running / total) * 1000) / 10 : 0 };
    });
  }, [data, valueKey]);

  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-sm p-4 text-center font-mono">No data available for visualization.</div>;
  }

  const activeOption = OPTIONS.find((o) => o.id === kind)!;

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
                className={`flex items-center gap-2 px-2.5 py-2 rounded-md text-xs font-medium text-left ${kind === opt.id ? "bg-cyan-500/15 text-cyan-300" : "text-slate-300 hover:bg-slate-700"}`}
                onClick={() => { setKind(opt.id); setOpen(false); }}
              >
                <opt.icon className="w-3.5 h-3.5" />
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {kind === "bar" && (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey={config.xAxisKey} stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} cursor={{ fill: "#1e293b" }} />
            <Bar dataKey={valueKey} radius={[4, 4, 0, 0]}>
              {data.map((_, idx) => <Cell key={idx} fill={COLORS[idx % COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}

      {kind === "pie" && (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={data} cx="50%" cy="50%" innerRadius={55} outerRadius={80} paddingAngle={4} dataKey={valueKey} nameKey={config.xAxisKey}>
              {data.map((_, idx) => <Cell key={idx} fill={COLORS[idx % COLORS.length]} />)}
            </Pie>
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} />
            <Legend wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }} />
          </PieChart>
        </ResponsiveContainer>
      )}

      {kind === "pareto" && (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={paretoData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey={config.xAxisKey} stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis yAxisId="left" stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis yAxisId="right" orientation="right" stroke="#2fd199" fontSize={11} tickLine={false} axisLine={false} domain={[0, 100]} unit="%" />
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} />
            <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
            <Bar yAxisId="left" dataKey={valueKey} name="Category total" fill="#5b6ef0" radius={[4, 4, 0, 0]} />
            <Line yAxisId="right" type="monotone" dataKey="cumulative_pct" name="Cumulative %" stroke="#2fd199" strokeWidth={2.5} dot={{ r: 3, fill: "#0f172a", strokeWidth: 2, stroke: "#2fd199" }} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
