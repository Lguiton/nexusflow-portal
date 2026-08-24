"use client";

import React, { useState } from "react";
import { Calendar, ChevronDown } from "lucide-react";

interface TimeRangeSelectorProps {
  onRangeChange?: (range: string) => void;
}

export default function TimeRangeSelector({ onRangeChange }: TimeRangeSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedRange, setSelectedRange] = useState("Q3 2026");

  const ranges = [
    { id: "30d", label: "Last 30 Days" },
    { id: "q3-2026", label: "Q3 2026" },
    { id: "ytd", label: "Year-to-Date (YTD)" },
    { id: "custom", label: "Custom Range..." },
  ];

  const handleSelect = (rangeLabel: string, rangeId: string) => {
    setSelectedRange(rangeLabel);
    setIsOpen(false);
    if (onRangeChange) {
      onRangeChange(rangeId);
    }
  };

  return (
    <div className="relative inline-block text-left">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-200 hover:border-indigo-500/50 hover:bg-slate-800/80 transition-all text-xs font-medium shadow-sm"
      >
        <Calendar className="w-4 h-4 text-indigo-400" />
        <span>Time Range: <strong className="text-white">{selectedRange}</strong></span>
        <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-48 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl z-30 overflow-hidden py-1 animate-in fade-in duration-150">
          {ranges.map((r) => (
            <button
              key={r.id}
              onClick={() => handleSelect(r.label, r.id)}
              className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                selectedRange === r.label 
                  ? "bg-indigo-600/20 text-indigo-300 font-medium border-l-2 border-indigo-500" 
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
