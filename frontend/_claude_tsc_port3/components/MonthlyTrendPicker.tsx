"use client";

import React, { useState } from "react";
import {
  LineChart, Line, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { LineChart as LineIcon, AreaChart as AreaIcon, ChevronDown } from "lucide-react";

// Same real monthly_totals data POST /api/v1/bi/chart-suite already
// returns (month, total_amount -- only present once 2+ distinct months
// are on file, see bi_visualization_architect.generate_chart_suite). This
// just adds a client-side toggle over how that one real series is drawn,
// matching the pattern CategoryChartPicker already established for
// category_breakdown. Line and Area only -- both are honest views of the
// same single-series real time data; nothing here changes what's plotted.

type TrendKind = "line" | "area";

const OPTIONS: { id: TrendKind; label: string; icon: React.ElementType }[] = [
  { id: "line", label: "Line", icon: LineIcon },
  { id: "area", label: "Area", icon: AreaIcon },
];

interface MonthlyTrendPickerProps {
  data: any[];
  config: { xAxisKey: string; dataKeys: string[] };
}

export default function MonthlyTrendPicker({ data, config }: MonthlyTrendPickerProps) {
  const [kind, setKind] = useState<TrendKind>("line");
  const [open, setOpen] = useState(false);
  const valueKey = config.dataKeys[0];

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
          <div className="absolute top-full right-0 mt-1.5 z-10 bg-slate-800 border border-slate-700 rounded-lg p-1 flex flex-col min-w-[110px] shadow-xl">
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

      {kind === "line" && (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey={config.xAxisKey} stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} />
            <Line type="monotone" dataKey={valueKey} stroke="#5b6ef0" strokeWidth={2.5} dot={{ r: 3, fill: "#0f172a", strokeWidth: 2, stroke: "#5b6ef0" }} />
          </LineChart>
        </ResponsiveContainer>
      )}

      {kind === "area" && (
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="monthlyTrendAreaFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#5b6ef0" stopOpacity={0.45} />
                <stop offset="95%" stopColor="#5b6ef0" stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey={config.xAxisKey} stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b", color: "#f8fafc", borderRadius: "8px" }} />
            <Area type="monotone" dataKey={valueKey} stroke="#5b6ef0" strokeWidth={2.5} fill="url(#monthlyTrendAreaFill)" />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
