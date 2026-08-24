"use client";

import React from "react";
import { LineChart, BarChart3, AreaChart, Table } from "lucide-react";

interface ChartViewToggleProps {
  currentView: string;
  onViewChange: (view: string) => void;
}

export default function ChartViewToggle({ currentView, onViewChange }: ChartViewToggleProps) {
  const views = [
    { id: "line", label: "Line Chart", icon: LineChart },
    { id: "bar", label: "Bar Comparison", icon: BarChart3 },
    { id: "area", label: "Cumulative Area", icon: AreaChart },
    { id: "table", label: "Raw Data Table", icon: Table },
  ];

  return (
    <div className="flex items-center gap-1 bg-slate-950 border border-slate-800/80 p-1 rounded-xl shadow-inner">
      {views.map((v) => {
        const Icon = v.icon;
        const isActive = currentView === v.id;
        return (
          <button
            key={v.id}
            onClick={() => onViewChange(v.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              isActive
                ? "bg-indigo-600 text-white shadow-lg shadow-indigo-600/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
            }`}
            title={v.label}
          >
            <Icon className="w-3.5 h-3.5 shrink-0" />
            <span className="hidden sm:inline">{v.label}</span>
          </button>
        );
      })}
    </div>
  );
}
