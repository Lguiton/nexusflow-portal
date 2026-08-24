'use client';

import React, { useState, useRef } from 'react';
import { Search, Sparkles, Terminal, CheckCircle2, ArrowRight, Loader2, AlertCircle, Database, Webhook, ListChecks } from 'lucide-react';
import { useClientId } from './ClientContext'; 
import DynamicChartEngine from './DynamicChartEngine';

interface AgentArtifact {
  agent_name: string;
  domain: string;
  output_summary: string;
  raw_artifacts?: Record<string, any>;
}

interface SearchResponse {
  query: string;
  synthesized_insight: string;
  agent_breakdown: AgentArtifact[];
  confidence_score: number;
  status: string;
}

interface CognitiveSearchBarProps {
  onQueryResult?: (data: any) => void;
}

const MAX_QUERY_LENGTH = 1000;
const REQUEST_TIMEOUT_MS = 30000;

export default function CognitiveSearchBar({ onQueryResult }: CognitiveSearchBarProps) {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResponse | null>(null);
  
  const abortControllerRef = useRef<AbortController | null>(null);

  const contextValue = useClientId();
  const activeClientId = typeof contextValue === 'object' && contextValue !== null 
    ? (contextValue as any).clientId || 'CLI-001' 
    : String(contextValue || 'CLI-001');

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedQuery = query.trim();

    if (!trimmedQuery) return;

    if (trimmedQuery.length > MAX_QUERY_LENGTH) {
      setError(`Query exceeds maximum allowed length of ${MAX_QUERY_LENGTH} characters.`);
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    setError(null);
    setResult(null); 

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

    const timeoutId = setTimeout(() => {
      controller.abort();
    }, REQUEST_TIMEOUT_MS);

    try {
      const res = await fetch(`${apiUrl}/api/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: trimmedQuery, client_id: activeClientId }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      const data = await res.json();

      if (!res.ok || data.status === 'ERROR') {
        throw new Error(data.synthesized_insight || data.detail || `Server returned status ${res.status}`);
      }

      setResult(data);
      
      if (onQueryResult) {
        onQueryResult(data);
      }
      
    } catch (err: any) {
      if (err.name === 'AbortError') {
        setError('The search request timed out or was cancelled. Please try again.');
      } else {
        console.error("Cognitive Search error:", err);
        setError(err.message || "Failed to reach FastAPI backend.");
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  // --- SMART INSIGHT RENDERER ---
  const renderInsight = () => {
    if (!result) return null;

    try {
      // Attempt to parse the response as JSON to detect structured agent payloads
      const parsed = JSON.parse(result.synthesized_insight);
      
      // ==========================================
      // 1. BI Visualization Architect (Agent #11)
      // ==========================================
      if (parsed.recharts_config && parsed.recommended_chart_type) {
        const rawType = parsed.recommended_chart_type.toLowerCase();
        let mappedType: 'bar' | 'pie' | 'stacked_bar' | 'pareto' = 'bar';
        if (rawType.includes('pie')) mappedType = 'pie';
        if (rawType.includes('stack')) mappedType = 'stacked_bar';
        
        const xAxisKey = parsed.recharts_config.xAxis || parsed.recharts_config.xAxisKey || 'name';
        const dataKeys = parsed.recharts_config.dataKeys || ['value'];
        const data = parsed.recharts_config.data || [];

        return (
          <div className="bg-slate-900/80 border border-cyan-900/50 rounded-xl p-6 mt-2 shadow-inner">
            <DynamicChartEngine 
              chartType={mappedType}
              data={data}
              config={{ xAxisKey, dataKeys }}
            />
            {parsed.insights && (
              <div className="mt-6 bg-cyan-950/40 p-4 rounded-lg text-sm text-cyan-50 border border-cyan-800/50 flex items-start gap-3">
                <Sparkles className="w-5 h-5 text-cyan-400 flex-shrink-0 mt-0.5" />
                <span className="leading-relaxed">{parsed.insights}</span>
              </div>
            )}
          </div>
        );
      }

      // ==========================================
      // 2. External Telemetry Scout (Agent #12)
      // ==========================================
      if (parsed.duckdb_schema_mapping && parsed.target_endpoint) {
        return (
          <div className="bg-slate-900/80 border border-indigo-900/50 rounded-xl p-6 mt-2 shadow-inner">
            <div className="flex items-center gap-2 mb-5 text-indigo-400 font-bold border-b border-slate-800 pb-3">
              <Webhook className="w-5 h-5" />
              <span>Telemetry Ingestion Strategy</span>
            </div>
            
            <div className="space-y-5">
              {/* Target Endpoint */}
              <div>
                <div className="text-xs text-slate-400 uppercase font-semibold mb-1.5 flex items-center gap-1.5">
                  <Terminal className="w-3.5 h-3.5"/> Target Endpoint
                </div>
                <code className="text-sm font-mono bg-slate-950 border border-slate-800 rounded px-3 py-2 text-emerald-400 block break-all shadow-inner">
                  {parsed.target_endpoint}
                </code>
              </div>
              
              {/* DuckDB Schema Table */}
              <div>
                <div className="text-xs text-slate-400 uppercase font-semibold mb-1.5 flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5"/> DuckDB Schema Mapping
                </div>
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-1 shadow-inner overflow-hidden">
                  <table className="w-full text-sm text-left">
                    <tbody>
                      {Object.entries(parsed.duckdb_schema_mapping).map(([col, type]) => (
                        <tr key={col} className="border-b border-slate-800/50 last:border-0 hover:bg-slate-900/50 transition-colors">
                          <td className="py-2.5 px-4 text-cyan-300 font-mono text-xs w-1/2 border-r border-slate-800/50">{col}</td>
                          <td className="py-2.5 px-4 text-indigo-300 font-mono text-xs font-semibold">{String(type)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Strategic Insights */}
              {parsed.insights && parsed.insights.length > 0 && (
                <div>
                  <div className="text-xs text-slate-400 uppercase font-semibold mb-2 flex items-center gap-1.5">
                    <ListChecks className="w-3.5 h-3.5"/> Pipeline Considerations
                  </div>
                  <ul className="space-y-2">
                    {parsed.insights.map((insight: string, idx: number) => (
                      <li key={idx} className="bg-indigo-950/20 border border-indigo-900/30 p-3 rounded-md text-sm text-indigo-100 flex items-start gap-2.5 shadow-sm">
                        <Sparkles className="w-4 h-4 text-indigo-400 flex-shrink-0 mt-0.5" />
                        <span className="leading-relaxed">{insight}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        );
      }

    } catch (e) {
      // If it's not JSON, it just falls through to render standard text
    }

    // Default Fallback: Standard text response for normal agent chats
    return (
      <p className="text-base text-white leading-relaxed font-semibold bg-cyan-950/20 border border-cyan-900/40 p-4 rounded-lg break-words whitespace-pre-wrap shadow-inner">
        {result.synthesized_insight}
      </p>
    );
  };

  return (
    <div className="w-full bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-md text-slate-100 my-6">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-lg font-bold flex items-center gap-2 text-white">
            <Sparkles className="text-cyan-400 w-5 h-5" />
            Universal Cognitive Search
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Semantic routing across Data Analyst, Science, and RAG sub-agents.
          </p>
        </div>
      </div>

      <form onSubmit={handleSearch} className="relative flex items-center">
        <Search className="absolute left-4 w-5 h-5 text-slate-500 pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          maxLength={MAX_QUERY_LENGTH}
          placeholder="Ask anything (e.g., 'What was our total mrr for the year 2022?')..."
          className="w-full bg-slate-950 border border-slate-800 rounded-xl py-3 pl-12 pr-32 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors shadow-inner"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="absolute right-2 z-10 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 rounded-lg text-xs font-semibold text-white transition-colors flex items-center gap-1.5 cursor-pointer shadow-md"
        >
          {loading ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Routing...
            </>
          ) : (
            <>
              Execute <ArrowRight className="w-3.5 h-3.5" />
            </>
          )}
        </button>
      </form>

      {/* Error State */}
      {error && (
        <div className="mt-4 bg-rose-950/40 border border-rose-800/60 rounded-xl p-4 flex items-center gap-3 text-rose-300 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Answer & Insight Section */}
      {result && (
        <div className="mt-6 space-y-4 animate-in fade-in duration-200">
          <div className="bg-slate-950 border border-cyan-800/50 rounded-xl p-5 shadow-lg">
            <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-800">
              <span className="text-xs font-bold text-cyan-400 uppercase tracking-wider flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" /> Cognitive Insight Synthesized
              </span>
              <span className="text-xs font-mono text-slate-400 bg-slate-900 px-2.5 py-1 rounded-md border border-slate-800">
                Confidence: {(result.confidence_score * 100).toFixed(0)}%
              </span>
            </div>
            
            <p className="text-xs text-slate-400 uppercase font-semibold mb-1">Synthesized Answer:</p>
            
            {/* INJECT THE DYNAMIC RENDERER HERE */}
            {renderInsight()}

          </div>

          {/* Sub-Agent Breakdown */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {result.agent_breakdown.map((agent, idx) => (
              <div key={idx} className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-4 shadow-inner">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold text-indigo-400">{agent.agent_name}</span>
                  <span className="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-300 font-mono border border-slate-700">
                    {agent.domain}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mb-2">{agent.output_summary}</p>
                {agent.raw_artifacts && (
                  <div className="bg-slate-900 border border-slate-800/60 rounded p-2 text-[11px] font-mono text-cyan-300 overflow-x-auto shadow-inner">
                    <Terminal className="w-3 h-3 inline mr-1 text-slate-500" />
                    {JSON.stringify(agent.raw_artifacts)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
