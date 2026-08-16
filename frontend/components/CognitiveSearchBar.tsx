'use client';

import React, { useState, useRef } from 'react';
import { Search, Sparkles, Terminal, CheckCircle2, ArrowRight, Loader2, AlertCircle } from 'lucide-react';
import { useClientId } from './ClientContext'; 

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

// Security guard: Maximum query length to prevent payload flooding/abuse
const MAX_QUERY_LENGTH = 1000;
// Request timeout in milliseconds (30 seconds)
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

    // Hardening: Enforce max query length
    if (trimmedQuery.length > MAX_QUERY_LENGTH) {
      setError(`Query exceeds maximum allowed length of ${MAX_QUERY_LENGTH} characters.`);
      return;
    }

    // Cancel any ongoing search request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    setError(null);
    setResult(null); 

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

    // Set up timeout timer
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
          className="w-full bg-slate-950 border border-slate-800 rounded-xl py-3 pl-12 pr-32 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors"
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
            <p className="text-base text-white leading-relaxed font-semibold bg-cyan-950/20 border border-cyan-900/40 p-4 rounded-lg">
              {result.synthesized_insight}
            </p>
          </div>

          {/* Sub-Agent Breakdown */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {result.agent_breakdown.map((agent, idx) => (
              <div key={idx} className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-4">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold text-indigo-400">{agent.agent_name}</span>
                  <span className="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-300 font-mono">
                    {agent.domain}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mb-2">{agent.output_summary}</p>
                {agent.raw_artifacts && (
                  <div className="bg-slate-900 border border-slate-800/60 rounded p-2 text-[11px] font-mono text-cyan-300 overflow-x-auto">
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