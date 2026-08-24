"use client";

import React, { useState } from "react";
import { 
  LayoutDashboard, 
  Terminal, 
  Database, 
  Cpu, 
  Settings, 
  ChevronLeft, 
  ChevronRight, 
  ShieldCheck, 
  Command 
} from "lucide-react";

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  onOpenCommandPalette: () => void;
}

export default function Sidebar({ activeTab, setActiveTab, onOpenCommandPalette }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  const navItems = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "telemetry", label: "Live Swarm Telemetry", icon: Terminal },
    { id: "sql-lab", label: "SQL Lab / Query Editor", icon: Database },
    { id: "fleet", label: "Agent Fleet Manager", icon: Cpu },
    { id: "settings", label: "Global Settings", icon: Settings },
  ];

  return (
    <aside 
      className={`h-screen bg-slate-950 border-r border-slate-800/80 text-slate-100 flex flex-col transition-all duration-300 z-40 sticky top-0 ${
        collapsed ? "w-20" : "w-64"
      }`}
    >
      {/* Brand Header */}
      <div className="p-4 border-b border-slate-800/80 flex items-center justify-between">
        {!collapsed && (
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0 shadow-lg shadow-indigo-600/30">
              <ShieldCheck className="w-5 h-5 text-white" />
            </div>
            <div className="truncate">
              <h1 className="font-bold text-sm tracking-tight text-white">NexusFlow</h1>
              <p className="text-[10px] text-indigo-400 font-mono tracking-wider">ANALYTICS v2.2</p>
            </div>
          </div>
        )}
        {collapsed && (
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center mx-auto shadow-lg shadow-indigo-600/30">
            <ShieldCheck className="w-5 h-5 text-white" />
          </div>
        )}
        <button 
          onClick={() => setCollapsed(!collapsed)}
          className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Quick Command Palette Trigger Button */}
      <div className="p-3 border-b border-slate-800/50">
        <button
          onClick={onOpenCommandPalette}
          className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-indigo-300 hover:border-indigo-500/50 transition-all text-xs font-mono group ${
            collapsed ? "justify-center" : "justify-between"
          }`}
          title="Open Command Palette (Cmd+K)"
        >
          <div className="flex items-center gap-2">
            <Command className="w-4 h-4 text-indigo-400 group-hover:scale-110 transition-transform" />
            {!collapsed && <span>Quick Search...</span>}
          </div>
          {!collapsed && (
            <kbd className="px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-400">
              ⌘K
            </kbd>
          )}
        </button>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 p-3 space-y-1.5 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-medium transition-all ${
                isActive
                  ? "bg-indigo-600/10 border border-indigo-500/30 text-indigo-300 shadow-sm"
                  : "text-slate-400 hover:bg-slate-900 hover:text-slate-200 border border-transparent"
              } ${collapsed ? "justify-center" : ""}`}
              title={collapsed ? item.label : undefined}
            >
              <Icon className={`w-4 h-4 shrink-0 ${isActive ? "text-indigo-400" : "text-slate-500"}`} />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </button>
          );
        })}
      </nav>

      {/* User / System Footer status */}
      <div className="p-3 border-t border-slate-800/80 bg-slate-950/50">
        {!collapsed ? (
          <div className="flex items-center gap-3 px-2 py-1.5">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
            <div className="truncate text-xs">
              <p className="font-medium text-slate-300">10 Agents Active</p>
              <p className="text-[10px] text-slate-500">Secure Microservice Net</p>
            </div>
          </div>
        ) : (
          <div className="flex justify-center py-1">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" title="10 Agents Active" />
          </div>
        )}
      </div>
    </aside>
  );
}
