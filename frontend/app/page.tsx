'use client';

import { useState, useEffect } from 'react';
import { Cpu, Server, ShieldCheck } from 'lucide-react';
import SubAgentWidget from '../components/SubAgentWidget';
import SwarmLogStreamer from '../components/SwarmLogStreamer';
import { ClientProvider } from '../components/ClientContext'; 
import CognitiveSearchBar from '../components/CognitiveSearchBar';
import AdvancedAnalyticsDashboard from '../components/AdvancedAnalyticsDashboard';
import VirtualCFOWidget from '../components/VirtualCFOWidget';
import DataEngineerWidget from '../components/DataEngineerWidget';
import ETLDropzone from '../components/ETLDropzone';
import { SwarmVisualizer } from '../components/SwarmVisualizer';

interface HealthData {
  status: string;
  docker_boundary_secure: boolean;
  active_sub_agents: number;
  version: string;
}

interface SearchResult {
  query: string;
  synthesized_insight: string;
  agent_breakdown: Array<{
    agent_name: string;
    domain: string;
    output_summary: string;
    raw_artifacts?: unknown;
  }>;
  confidence_score: number;
  status: string;
}

export default function CoreDashboard() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [dashboardRefreshTrigger, setDashboardRefreshTrigger] = useState<number>(0);

  useEffect(() => {
    async function fetchHealth() {
      try {
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
        const res = await fetch(`${backendUrl}/api/v1/health`);
        if (res.ok) {
          const data: HealthData = await res.json();
          setHealth(data);
        }
      } catch (err) {
        console.error("Health check failed:", err);
      } finally {
        setLoading(false);
      }
    }
    fetchHealth();
  }, []);

  return (
    <ClientProvider>
      <div className="min-h-screen bg-slate-950 text-slate-100 font-sans p-6 md:p-12 space-y-8">
        
        {/* Header */}
        <header className="flex justify-between items-center pb-8 border-b border-slate-800">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <Cpu className="text-indigo-500 w-7 h-7" />
              NexusFlow Analytics
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Enterprise AI Systems & Business Intelligence Gateway
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              Supervisor Online
            </span>
          </div>
        </header>

        {/* Top Metrics Cards */}
        <main className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">System State</span>
              <Server className="w-5 h-5 text-indigo-400" />
            </div>
            <div className="mt-4">
              <p className="text-2xl font-bold text-white">{loading ? "Checking..." : health?.status || "OFFLINE"}</p>
              <p className="text-xs text-slate-500 mt-1">FastAPI Engine v{health?.version || "1.0.0"}</p>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Runtime Security</span>
              <ShieldCheck className="w-5 h-5 text-emerald-400" />
            </div>
            <div className="mt-4">
              <p className="text-2xl font-bold text-white">{health?.docker_boundary_secure ? "ISOLATED" : "CHECKING"}</p>
              <p className="text-xs text-slate-500 mt-1">RevSecOps & SysAdmin Policy Enforced</p>
            </div>
          </div>

          <SubAgentWidget activeCount={health?.active_sub_agents} />
        </main>

        <section><CognitiveSearchBar onQueryResult={(data) => setSearchResult(data)} /></section>
        <section><SwarmLogStreamer sessionId="active_dashboard_session" /></section>

        {searchResult && (
          <section className="animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
            <SwarmVisualizer data={searchResult} />
          </section>
        )}

        <section><AdvancedAnalyticsDashboard /></section>

        {/* Financial & Data Engineering Intelligence Grid */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <VirtualCFOWidget refreshTrigger={dashboardRefreshTrigger} />
          <DataEngineerWidget refreshTrigger={dashboardRefreshTrigger} />
        </section>

        {/* Automated Data Ingestion Section */}
        <section>
          <ETLDropzone onUploadSuccess={() => setDashboardRefreshTrigger(prev => prev + 1)} />
        </section>

      </div>
    </ClientProvider>
  );
}
