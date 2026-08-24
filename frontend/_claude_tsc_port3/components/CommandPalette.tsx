"use client";

import React, { useState, useEffect } from "react";
import { Search, Waypoints, Database, BarChart3, ShieldCheck, LayoutDashboard, X, ArrowRight } from "lucide-react";

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectAction: (actionId: string) => void;
}

export default function CommandPalette({ isOpen, onClose, onSelectAction }: CommandPaletteProps) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (isOpen) {
          onClose();
        }
      }
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // ids match AppShell's ViewId ("overview" | "analytics" | "ledger" |
  // "swarm" | "trust") -- this used to list a placeholder action set
  // (sql-lab, fleet, settings) that didn't correspond to anything real in
  // the app. Now every action navigates to a real section.
  const actions = [
    { id: "overview", label: "Go to Overview", category: "Navigation", icon: LayoutDashboard },
    { id: "analytics", label: "Go to Analytics", category: "Navigation", icon: BarChart3 },
    { id: "ledger", label: "Go to Ledger & Data", category: "Navigation", icon: Database },
    { id: "swarm", label: "Open Live Swarm Telemetry", category: "Navigation", icon: Waypoints },
    { id: "trust", label: "Go to Trust & Gaps", category: "Navigation", icon: ShieldCheck },
  ];

  const filteredActions = actions.filter(action =>
    action.label.toLowerCase().includes(query.toLowerCase()) ||
    action.category.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-start justify-center pt-20 px-4 animate-in fade-in duration-200">
      <div 
        className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden text-slate-100 flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center px-4 py-3 border-b border-slate-800 gap-3">
          <Search className="w-5 h-5 text-indigo-400 shrink-0" />
          <input
            autoFocus
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command or search metrics (e.g. 'Dashboard', 'Telemetry')..."
            className="flex-1 bg-transparent border-none text-sm text-slate-100 focus:outline-none placeholder:text-slate-500 font-sans"
          />
          <button 
            onClick={onClose}
            className="p-1 rounded-lg bg-slate-800/50 hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="max-h-80 overflow-y-auto p-2 space-y-1">
          {filteredActions.length === 0 ? (
            <div className="py-8 text-center text-slate-500 text-xs font-mono">
              No matching commands found for &ldquo;{query}&rdquo;
            </div>
          ) : (
            filteredActions.map((action) => {
              const Icon = action.icon;
              return (
                <button
                  key={action.id}
                  onClick={() => {
                    onSelectAction(action.id);
                    onClose();
                  }}
                  className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl hover:bg-indigo-600/10 hover:border-indigo-500/30 border border-transparent text-left group transition-all"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-center text-indigo-400 group-hover:scale-105 transition-transform">
                      <Icon className="w-4 h-4" />
                    </div>
                    <div>
                      <p className="text-xs font-medium text-slate-200 group-hover:text-indigo-300">{action.label}</p>
                      <p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">{action.category}</p>
                    </div>
                  </div>
                  <ArrowRight className="w-4 h-4 text-slate-600 group-hover:text-indigo-400 group-hover:translate-x-0.5 transition-all" />
                </button>
              );
            })
          )}
        </div>

        <div className="px-4 py-2.5 bg-slate-950 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-500 font-mono">
          <span>Navigate with arrow keys or click</span>
          <span>ESC to close</span>
        </div>
      </div>
    </div>
  );
}
