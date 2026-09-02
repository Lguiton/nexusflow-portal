'use client';

import React from 'react';
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer 
} from 'recharts';
import { Table, TrendingUp, Lightbulb, GitMerge, ShieldCheck } from 'lucide-react';

// --- TYPE DEFINITIONS ---
interface AgentContribution {
  agent_name: string;
  domain: string;
  output_summary: string;
  raw_artifacts?: any;
}

interface CognitiveSearchResponse {
  query: string;
  synthesized_insight: string;
  agent_breakdown: AgentContribution[];
  confidence_score: number;
  status: string;
}

// --- SUB-COMPONENTS ---

// 1. Analyst: DuckDB Data Table
const AnalystTable = ({ artifacts }: { artifacts: any }) => {
  const results = artifacts?.results || [];
  if (results.length === 0) return <div className="text-slate-400">No data returned from ledger.</div>;

  const headers = Object.keys(results[0]);

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700 bg-slate-800/50">
      <table className="w-full text-left text-sm text-slate-300">
        <thead className="bg-slate-800 text-xs uppercase text-slate-400">
          <tr>
            {headers.map((header) => (
              <th key={header} className="px-6 py-3 font-medium">{header.replace('_', ' ')}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {results.map((row: any, i: number) => (
            <tr key={i} className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors">
              {headers.map((header) => (
                <td key={header + i} className="px-6 py-4">
                  {/* eslint-disable-next-line security/detect-object-injection -- header comes from Object.keys(results[0]) -- reading the object's own real keys back off itself, not attacker-controlled */}
                  {typeof row[header] === 'number' 
                    // eslint-disable-next-line security/detect-object-injection -- header comes from Object.keys(results[0]) -- reading the object's own real keys back off itself, not attacker-controlled
                    ? row[header].toLocaleString(undefined, { maximumFractionDigits: 2 }) 
                    // eslint-disable-next-line security/detect-object-injection -- header comes from Object.keys(results[0]) -- reading the object's own real keys back off itself, not attacker-controlled
                    : row[header]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// 2. Forecaster: Recharts Confidence Interval Graph
const ForecasterChart = ({ insight, artifacts }: { insight: string; artifacts: any }) => {
  const mockTimeSeriesData = [
    { month: 'Jul', expected: 120000, lower: 118000, upper: 122000 },
    { month: 'Aug', expected: 125000, lower: 120000, upper: 130000 },
    { month: 'Sep', expected: 132000, lower: 122000, upper: 142000 },
    { month: 'Oct', expected: 141000, lower: 125000, upper: 157000 },
    { month: 'Nov', expected: 152000, lower: 130000, upper: 174000 },
  ];

  return (
    <div className="space-y-6">
      <div className="bg-indigo-900/20 border border-indigo-500/30 p-4 rounded-lg text-indigo-200 text-sm leading-relaxed">
        <strong>Prediction Model:</strong> {artifacts?.model_type || 'Statistical Projection'} <br />
        {insight}
      </div>
      
      <div className="h-72 w-full bg-slate-900 rounded-lg p-4 border border-slate-800">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={mockTimeSeriesData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis dataKey="month" stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} />
            <YAxis stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} tickFormatter={(val) => `$${val / 1000}k`} />
            <Tooltip 
              contentStyle={{ backgroundColor: '#1e293b', borderColor: '#334155', color: '#f8fafc' }}
              formatter={(value: any) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))}
            />
            <Area type="monotone" dataKey={["lower", "upper"] as any} stroke="none" fill="#6366f1" fillOpacity={0.15} name="95% Confidence Interval"/>
            <Area type="monotone" dataKey="expected" stroke="#818cf8" strokeWidth={2} fill="url(#colorExpected)" name="Expected Trajectory"/>
            <defs>
              <linearGradient id="colorExpected" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#818cf8" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#818cf8" stopOpacity={0}/>
              </linearGradient>
            </defs>
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

// 3. Strategist: Executive Insight Card
const StrategistCard = ({ insight }: { insight: string }) => {
  return (
    <div className="relative bg-gradient-to-br from-emerald-900/40 to-slate-900 border border-emerald-500/30 p-6 rounded-xl overflow-hidden">
      <div className="absolute -right-4 -top-4 opacity-10">
        <Lightbulb className="w-32 h-32 text-emerald-400" />
      </div>
      <h3 className="text-emerald-400 font-semibold mb-3 flex items-center gap-2">
        <Lightbulb className="w-5 h-5" />
        Executive Strategic Advisory
      </h3>
      <p className="text-slate-200 text-lg leading-relaxed relative z-10 font-light">
        {insight}
      </p>
    </div>
  );
};

// --- MAIN WRAPPER COMPONENT ---

export function SwarmVisualizer({ data }: { data: CognitiveSearchResponse | null }) {
  if (!data) return null;

  const workerAgent = data.agent_breakdown.find(a => a.agent_name !== "Orchestrator Agent #00");
  
  if (!workerAgent) return null;

  const renderContent = () => {
    if (workerAgent.agent_name.includes("Agent #04")) {
      return <AnalystTable artifacts={workerAgent.raw_artifacts} />;
    }
    if (workerAgent.agent_name.includes("Agent #07")) {
      return <ForecasterChart insight={data.synthesized_insight} artifacts={workerAgent.raw_artifacts} />;
    }
    if (workerAgent.agent_name.includes("Agent #15")) {
      return <StrategistCard insight={data.synthesized_insight} />;
    }
    return <div className="text-slate-400">Awaiting specialized agent rendering...</div>;
  };

  const getAgentIcon = () => {
    if (workerAgent.agent_name.includes("Agent #04")) return <Table className="w-5 h-5 text-blue-400" />;
    if (workerAgent.agent_name.includes("Agent #07")) return <TrendingUp className="w-5 h-5 text-indigo-400" />;
    return <Lightbulb className="w-5 h-5 text-emerald-400" />;
  };

  return (
    <div className="w-full max-w-5xl mx-auto mt-8 bg-slate-900 border border-slate-800 rounded-xl shadow-2xl overflow-hidden">
      <div className="bg-slate-950/50 border-b border-slate-800 p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <GitMerge className="w-5 h-5 text-slate-500" />
          <span className="text-sm font-medium text-slate-400">
            Routed via <strong>Orchestrator #00</strong> →
          </span>
          <div className="flex items-center gap-2 px-3 py-1 bg-slate-800 rounded-full border border-slate-700">
            {getAgentIcon()}
            <span className="text-sm font-medium text-slate-200">{workerAgent.agent_name}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-emerald-500 text-sm font-medium">
          <ShieldCheck className="w-4 h-4" />
          <span>Confidence: {(data.confidence_score * 100).toFixed(0)}%</span>
        </div>
      </div>
      <div className="p-6">
        {renderContent()}
      </div>
    </div>
  );
}