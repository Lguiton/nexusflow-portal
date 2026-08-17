'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Activity, ChevronDown, Cpu, ArrowLeft, Database, Shield, LineChart, BrainCircuit, Terminal, PieChart, Globe } from 'lucide-react';

// --- EXACT 13-AGENT REGISTRY MAPPING YOUR BACKEND TREE ---
const AGENT_REGISTRY = [
  { id: "00", name: "Orchestrator", domain: "Semantic Routing", icon: BrainCircuit, status: "Active", capabilities: ["Intent classification", "Agent delegation", "Payload aggregation"], latestReport: "Processed dynamic queries across microservices. Average routing latency: < 50ms." },
  { id: "01", name: "Ingestion Engine", domain: "Data Pipeline", icon: Database, status: "Active", capabilities: ["CSV parsing", "API webhook listening", "Data normalization"], latestReport: "Batch ingestion pipeline active. Normalizing incoming streams into target schema." },
  { id: "02", name: "Data Engineer", domain: "Data Pipeline", icon: Database, status: "Active", capabilities: ["Schema auditing", "Null value handling", "Data hygiene"], latestReport: "Normalized currency values to USD and validated ETL pipeline schemas." },
  { id: "03", name: "Schema Mapper", domain: "Database", icon: Database, status: "Active", capabilities: ["DuckDB optimization", "Multi-tenant isolation", "Index generation"], latestReport: "Tenant boundary enforced. Embedded DuckDB indices optimized for column-store reads." },
  { id: "04", name: "Data Analyst", domain: "Execution", icon: LineChart, status: "Active", capabilities: ["Text-to-SQL translation", "Safe intent building", "Ledger aggregations"], latestReport: "Converted natural language prompts into optimized columnar SQL queries." },
  { id: "05", name: "BI Engineer", domain: "Analytics", icon: LineChart, status: "Active", capabilities: ["Dashboard metric generation", "Variance analysis", "KPI tracking"], latestReport: "Continuous tracking enabled. SaaS subscription metrics updating in real-time." },
  { id: "06", name: "Report Generator", domain: "Exports", icon: Database, status: "Standby", capabilities: ["PDF synthesis", "Automated CSV generation", "Email delivery"], latestReport: "Ready for export generation. Stakeholder report schedules synchronized." },
  { id: "07", name: "Predictive Forecaster", domain: "Predictive", icon: LineChart, status: "Active", capabilities: ["ARIMA modeling", "Growth trajectory", "Statistical projections"], latestReport: "Generated 3-month MRR growth trajectory assuming 5-12% MoM scaling." },
  { id: "08", name: "Virtual CFO", domain: "Finance", icon: LineChart, status: "Active", capabilities: ["Margin calculation", "Burn rate analysis", "Strategic advisory"], latestReport: "Synthesized executive briefing. Cash runway and gross margins calculated." },
  { id: "09", name: "Ops Shield", domain: "Cybersecurity", icon: Shield, status: "Active", capabilities: ["Semantic firewalling", "Prompt injection defense", "IDOR prevention"], latestReport: "Intercepted malicious payload. Privilege escalation attempt blocked (403)." },
  { id: "10", name: "SaaS Strategist", domain: "Strategy", icon: BrainCircuit, status: "Active", capabilities: ["Margin expansion modeling", "Tier elasticity", "Competitor indexing"], latestReport: "Competitor index updated. Market elasticity indicators stable." },
  { id: "11", name: "BI Vis. Architect", domain: "Analytics", icon: PieChart, status: "Active", capabilities: ["Recharts JSON config", "Categorical data modeling", "Numerical frequency distribution"], latestReport: "Generated optimal JSON configurations for vertical, horizontal, Pareto, and stacked bar charts." },
  { id: "12", name: "Telemetry Scout", domain: "Ingestion", icon: Globe, status: "Active", capabilities: ["Live API polling", "Webhook mapping", "Nested JSON flattening"], latestReport: "Mapped external real-time JSON streams to DuckDB flat schema." },
];

export default function SubAgentWidget({ activeCount = 13 }: { activeCount?: number }) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<any>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown if clicked outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setSelectedAgent(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm hover:border-slate-700 transition-colors" ref={dropdownRef}>
      {/* Base Card UI */}
      <div 
        className="cursor-pointer flex flex-col h-full group"
        onClick={() => !isOpen && setIsOpen(true)}
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 group-hover:text-cyan-400 transition-colors">
            Sub-Agent Network
          </span>
          <Activity className="w-5 h-5 text-cyan-400" />
        </div>
        <div className="mt-4 flex items-end justify-between">
          <div>
            <p className="text-2xl font-bold text-white">
              {activeCount} / 13 Active
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Ready for Ingestion & Analytics
            </p>
          </div>
          <ChevronDown className={`w-5 h-5 text-slate-500 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`} />
        </div>
      </div>

      {/* Floating Dropdown Menu */}
      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-80 sm:w-96 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50 overflow-hidden flex flex-col max-h-[32rem] animate-in fade-in slide-in-from-top-2 duration-200">
          
          {selectedAgent ? (
            // --- DETAILED AGENT VIEW ---
            <div className="p-4 flex flex-col h-full">
              <button 
                onClick={() => setSelectedAgent(null)}
                className="flex items-center gap-2 text-xs text-slate-400 hover:text-white transition-colors mb-4 w-fit"
              >
                <ArrowLeft className="w-3 h-3" /> Back to Network
              </button>
              
              <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-cyan-950/50 border border-cyan-900 rounded-lg">
                    <selectedAgent.icon className="w-5 h-5 text-cyan-400" />
                  </div>
                  <div>
                    <h4 className="font-bold text-white text-sm">Agent #{selectedAgent.id}</h4>
                    <p className="text-xs font-mono text-cyan-400">{selectedAgent.name}</p>
                  </div>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto custom-scrollbar pr-2 space-y-5">
                {/* Capabilities Section */}
                <div>
                  <p className="text-xs text-slate-500 uppercase font-semibold mb-2 tracking-wider">Core Capabilities</p>
                  <ul className="space-y-2">
                    {selectedAgent.capabilities.map((cap: string, i: number) => (
                      <li key={i} className="text-sm text-slate-300 bg-slate-950 px-3 py-2 rounded-md border border-slate-800 flex items-center gap-2">
                        <Cpu className="w-3 h-3 text-slate-500" /> {cap}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Live Activity Report Section */}
                <div>
                  <p className="text-xs text-slate-500 uppercase font-semibold mb-2 tracking-wider flex items-center gap-2">
                    <Terminal className="w-3.5 h-3.5" /> Latest Output Report
                  </p>
                  <div className="bg-slate-950 border border-slate-800 rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-2 pb-2 border-b border-slate-800/50">
                       <span className={`w-2 h-2 rounded-full ${
                         selectedAgent.status === 'Active' ? 'bg-emerald-500 animate-pulse' : 
                         selectedAgent.status === 'Standby' ? 'bg-amber-500' : 'bg-slate-500'
                       }`}></span>
                       <span className="text-[10px] font-mono text-slate-400">
                         STATE: {selectedAgent.status.toUpperCase()}
                       </span>
                    </div>
                    <p className="text-xs text-cyan-100/70 leading-relaxed font-mono">
                      &gt; {selectedAgent.latestReport}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            // --- MAIN DIRECTORY LIST ---
            <>
              <div className="p-3 border-b border-slate-800 bg-slate-950/50">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Swarm Directory (13 Active)</p>
              </div>
              <div className="overflow-y-auto flex-1 p-2 space-y-1 custom-scrollbar">
                {AGENT_REGISTRY.map((agent) => (
                  <button
                    key={agent.id}
                    onClick={() => setSelectedAgent(agent)}
                    className="w-full text-left flex items-center justify-between p-2 rounded-lg hover:bg-slate-800/50 transition-colors group"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-mono text-slate-500 group-hover:text-cyan-500">#{agent.id}</span>
                      <span className="text-sm font-medium text-slate-300 group-hover:text-white">{agent.name}</span>
                    </div>
                    
                    {/* Render status domain and indicator dot */}
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase tracking-wider text-slate-500 bg-slate-950 px-2 py-0.5 rounded border border-slate-800 hidden sm:block">
                        {agent.domain}
                      </span>
                      <span className={`w-1.5 h-1.5 rounded-full ${
                         agent.status === 'Active' ? 'bg-emerald-500' : 
                         agent.status === 'Standby' ? 'bg-amber-500' : 'bg-slate-600'
                      }`}></span>
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
