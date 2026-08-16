'use client';

import React, { useState, useMemo } from 'react';
import { BarChart3, Table as TableIcon, Code2, Database } from 'lucide-react';
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  Cell
} from 'recharts';

interface SwarmVisualizerProps {
  data: any;
}

export function SwarmVisualizer({ data }: SwarmVisualizerProps) {
  const [activeTab, setActiveTab] = useState<'chart' | 'table' | 'sql'>('chart');

  // 1. Extract the Data Analyst's artifacts from the swarm payload
  const analystArtifact = useMemo(() => {
    if (!data?.agent_breakdown) return null;
    return data.agent_breakdown.find((a: any) => 
      a.agent_name.includes('Analyst') && a.raw_artifacts?.results?.length > 0
    );
  }, [data]);

  if (!analystArtifact) return null;

  const results = analystArtifact.raw_artifacts.results;
  const sql = analystArtifact.raw_artifacts.sql;
  const intent = analystArtifact.raw_artifacts.intent;

  // 2. Dynamically determine axes based on what DuckDB returned
  const keys = Object.keys(results[0] || {});
  const xKey = keys.find(k => typeof results[0][k] === 'string' && k !== 'client_id' && k !== 'id') || keys[0];
  const yKey = keys.find(k => typeof results[0][k] === 'number') || keys[1] || keys[0];

  return (
    <div className="w-full bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg mt-6">
      {/* Header & Tabs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-800 bg-slate-950/50 p-4">
        <div className="flex items-center gap-2 mb-4 sm:mb-0">
          <Database className="w-5 h-5 text-emerald-400" />
          <h3 className="text-sm font-bold text-white tracking-wide uppercase">
            Data Extraction Payload
          </h3>
          <span className="ml-2 px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950/60 text-emerald-400 border border-emerald-800">
            {results.length} Rows
          </span>
        </div>

        <div className="flex bg-slate-900 rounded-lg p-1 border border-slate-800">
          <button
            onClick={() => setActiveTab('chart')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
              activeTab === 'chart' ? 'bg-slate-800 text-cyan-400 shadow' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" /> Chart
          </button>
          <button
            onClick={() => setActiveTab('table')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
              activeTab === 'table' ? 'bg-slate-800 text-emerald-400 shadow' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <TableIcon className="w-3.5 h-3.5" /> Table
          </button>
          <button
            onClick={() => setActiveTab('sql')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
              activeTab === 'sql' ? 'bg-slate-800 text-indigo-400 shadow' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Code2 className="w-3.5 h-3.5" /> Intent & SQL
          </button>
        </div>
      </div>

      {/* Content Area */}
      <div className="p-6">
        
        {/* CHART VIEW */}
        {activeTab === 'chart' && (
          <div className="h-[300px] w-full">
            {results.length === 1 && Object.keys(results[0]).length === 1 ? (
               // Edge case: A single aggregate number (e.g. SUM of MRR)
               <div className="h-full flex flex-col items-center justify-center bg-slate-950/50 rounded-lg border border-slate-800">
                 <p className="text-sm text-slate-400 uppercase font-semibold mb-2">{yKey}</p>
                 <p className="text-5xl font-bold text-cyan-400">
                   {typeof results[0][yKey] === 'number' && results[0][yKey] > 1000 
                     ? `$${results[0][yKey].toLocaleString(undefined, { minimumFractionDigits: 2 })}` 
                     : results[0][yKey]}
                 </p>
               </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={results} margin={{ top: 10, right: 10, left: 0, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                  <XAxis 
                    dataKey={xKey} 
                    stroke="#64748b" 
                    fontSize={11} 
                    tickLine={false} 
                    axisLine={false}
                    tick={{ fill: '#64748b' }}
                  />
                  <YAxis 
                    stroke="#64748b" 
                    fontSize={11} 
                    tickLine={false} 
                    axisLine={false}
                    tickFormatter={(value) => value > 999 ? `$${(value/1000).toFixed(0)}k` : value}
                  />
                  <Tooltip 
                    cursor={{ fill: '#1e293b', opacity: 0.4 }}
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '8px', fontSize: '12px', color: '#f1f5f9' }}
                    itemStyle={{ color: '#22d3ee', fontWeight: 'bold' }}
                  />
                  <Bar dataKey={yKey} radius={[4, 4, 0, 0]}>
                    {results.map((entry: any, index: number) => (
                      <Cell key={`cell-${index}`} fill={index % 2 === 0 ? '#0891b2' : '#0d9488'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        )}

        {/* TABLE VIEW */}
        {activeTab === 'table' && (
          <div className="overflow-x-auto border border-slate-800 rounded-lg max-h-[300px] overflow-y-auto custom-scrollbar">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="text-xs uppercase bg-slate-950/80 text-slate-400 sticky top-0 border-b border-slate-800">
                <tr>
                  {keys.map((key) => (
                    <th key={key} className="px-4 py-3 font-semibold">{key.replace('_', ' ')}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 bg-slate-900/50">
                {results.map((row: any, i: number) => (
                  <tr key={i} className="hover:bg-slate-800/30 transition-colors">
                    {keys.map((key) => (
                      <td key={key} className="px-4 py-2.5 whitespace-nowrap">
                        {typeof row[key] === 'number' && key.toLowerCase().includes('mrr') || key.toLowerCase().includes('result') || key.toLowerCase().includes('amount') 
                          ? `$${row[key].toLocaleString(undefined, { minimumFractionDigits: 2 })}` 
                          : row[key]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* SQL & INTENT VIEW */}
        {activeTab === 'sql' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-[300px]">
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 flex flex-col">
              <h4 className="text-xs text-indigo-400 font-bold uppercase mb-2">LLM JSON Intent</h4>
              <pre className="text-[11px] text-slate-300 font-mono overflow-auto flex-1 custom-scrollbar">
                {JSON.stringify(intent, null, 2)}
              </pre>
            </div>
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 flex flex-col">
              <h4 className="text-xs text-indigo-400 font-bold uppercase mb-2">Compiled DuckDB Query</h4>
              <div className="text-[12px] text-emerald-300 font-mono overflow-auto flex-1 bg-slate-900/50 p-3 rounded custom-scrollbar border border-slate-800/60">
                {sql}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}