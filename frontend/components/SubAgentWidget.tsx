'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Activity, ChevronDown, Cpu, ArrowLeft, Database, Shield, LineChart, BrainCircuit, Terminal } from 'lucide-react';

// --- MOCK AGENT DATABASE (NOW ENHANCED WITH STATUS & REPORTS) ---
const AGENT_REGISTRY = [
  { id: "00", name: "Orchestrator", domain: "Semantic Routing", icon: BrainCircuit, status: "Active", capabilities: ["Intent classification", "Agent delegation", "Payload aggregation"], latestReport: "Processed 142 dynamic queries in the last 24h. Average routing latency: 124ms. Semantic matching confidence > 98%." },
  { id: "01", name: "Ingestion Engine", domain: "Data Pipeline", icon: Database, status: "Idle", capabilities: ["CSV parsing", "API webhook listening", "Data normalization"], latestReport: "Awaiting next batch. Last ingestion (batch_9902) completed successfully. 4,200 rows normalized into target schema." },
  { id: "02", name: "Data Cleanser", domain: "Data Pipeline", icon: Database, status: "Standby", capabilities: ["Anomaly scrubbing", "Null value handling", "Type casting"], latestReport: "Scrubbed 14 anomalous string entries from 'Amount' column in last ledger upload. Replaced nulls with 0.0." },
  { id: "03", name: "Schema Mapper", domain: "Database", icon: Database, status: "Active", capabilities: ["DuckDB optimization", "Multi-tenant isolation", "Index generation"], latestReport: "Tenant boundary enforced. Embedded DuckDB indices optimized for column-store analytical reads." },
  { id: "04", name: "Data Analyst", domain: "Execution", icon: LineChart, status: "Idle", capabilities: ["Text-to-SQL translation", "Safe intent building", "Ledger aggregations"], latestReport: "Last query executed: 'SELECT category, SUM(amount)...'. Returned 12 aggregated rows in 45ms." },
  { id: "05", name: "BI Engineer", domain: "Analytics", icon: LineChart, status: "Active", capabilities: ["Dashboard metric generation", "Variance analysis", "KPI tracking"], latestReport: "Continuous tracking enabled. Detected a 4.2% positive variance in Month-over-Month SaaS subscription revenue." },
  { id: "06", name: "Report Generator", domain: "Exports", icon: Database, status: "Standby", capabilities: ["PDF synthesis", "Automated CSV generation", "Email delivery"], latestReport: "Generated End-of-Month executive summary PDF. Dispatched to 4 stakeholder emails at 08:00 UTC." },
  { id: "07", name: "Forecaster", domain: "Predictive", icon: LineChart, status: "Idle", capabilities: ["ARIMA modeling", "Confidence intervals", "Time-series projection"], latestReport: "Projecting Q4 metrics. Upper bound confidence interval suggests $1.2M ARR target is reachable by December." },
  { id: "08", name: "Churn Predictor", domain: "Predictive", icon: BrainCircuit, status: "Active", capabilities: ["Risk scoring", "Usage drop-off alerts", "Retention modeling"], latestReport: "Flagged 3 enterprise accounts with dropping login velocity. Recommended proactive CSM outreach." },
  { id: "09", name: "Revenue Optimizer", domain: "Strategy", icon: LineChart, status: "Standby", capabilities: ["Upsell pathing", "Expansion MRR tracking", "Cohort analysis"], latestReport: "Analyzed Q2 cohort. Identified a 15% upsell opportunity in the mid-market tier based on feature usage." },
  { id: "10", name: "Pricing Strategist", domain: "Strategy", icon: BrainCircuit, status: "Idle", capabilities: ["Margin expansion modeling", "Tier elasticity", "Competitor indexing"], latestReport: "Competitor index updated. Recommended exploring a 5% price increase on Pro tiers to match market elasticity." },
  { id: "11", name: "Virtual CFO", domain: "Finance", icon: LineChart, status: "Active", capabilities: ["Cash runway modeling", "Burn rate limits", "Capital allocation"], latestReport: "Runway modeled at 18.4 months. Burn rate is stable. Recommending shifting 10% of idle capital to high-yield reserves." },
  { id: "12", name: "Comptroller", domain: "Audit", icon: Shield, status: "Active", capabilities: ["Policy violation flags", "Expense categorization", "Anomaly detection"], latestReport: "Audited recent ledger payload. Flagged 2 high-value marketing anomalies lacking documentation." },
  { id: "13", name: "Risk Assessor", domain: "Audit", icon: Shield, status: "Standby", capabilities: ["Vendor concentration risk", "Unusual spend velocity", "Compliance checks"], latestReport: "Vendor concentration remains within safe bounds. AWS spend accounts for 34% of COGS, within expected 40% limit." },
  { id: "14", name: "Market Researcher", domain: "Strategy", icon: BrainCircuit, status: "Idle", capabilities: ["SaaS benchmark comparisons", "Macro trend analysis", "Growth metrics"], latestReport: "Cross-referenced internal growth (12% YoY) against B2B SaaS benchmarks (10% YoY). Outperforming baseline." },
  { id: "15", name: "SaaS Strategist", domain: "Advisory", icon: BrainCircuit, status: "Idle", capabilities: ["High-level operational advice", "Executive summaries", "Growth tactics"], latestReport: "Awaiting strategic prompts. Last advice generated: 'Optimizing the onboarding funnel for self-serve users'." },
  { id: "16", name: "Sentiment Analyzer", domain: "Analytics", icon: BrainCircuit, status: "Active", capabilities: ["Support ticket parsing", "CSAT projection", "Feedback loops"], latestReport: "Ingested 45 recent Zendesk tickets. Overall sentiment is trending positive (78%). Minor complaints regarding UI speed." },
  { id: "17", name: "Security Guardrail", domain: "Security", icon: Shield, status: "Active", capabilities: ["SQL injection prevention", "Hallucination trapping", "Boundary enforcement"], latestReport: "0 security breaches detected. 100% of generated SQL passed the strict boundary isolation checks." },
  { id: "18", name: "Prompt Engineer", domain: "Optimization", icon: Cpu, status: "Standby", capabilities: ["Context window compression", "Token efficiency", "Dynamic system prompts"], latestReport: "Compressed system context payload by 14% to reduce LLM token costs without sacrificing reasoning quality." },
  { id: "19", name: "System Monitor", domain: "Infrastructure", icon: Activity, status: "Active", capabilities: ["API latency tracking", "Agent timeout restarts", "Swarm health pings"], latestReport: "All 20 sub-agents responding normally. FastAPI backend latency stable at < 60ms. System healthy." },
];

export default function SubAgentWidget({ activeCount = 20 }: { activeCount?: number }) {
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
              {activeCount} / 20 Active
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
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Swarm Directory</p>
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
                    
                    {/* Render a dot indicating status on the list view */}
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