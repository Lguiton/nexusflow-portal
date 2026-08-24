'use client';

import { useState, useEffect } from 'react';
import { ClientProvider } from '../components/ClientContext';
import AppShell from '../components/AppShell';
import type { ViewId } from '../components/AppShell';
import CommandPalette from '../components/CommandPalette';
import OverviewView from '../components/views/OverviewView';
import AnalyticsView from '../components/views/AnalyticsView';
import LedgerView from '../components/views/LedgerView';
import SwarmView from '../components/views/SwarmView';
import TrustView from '../components/views/TrustView';
import type { HealthData } from '../components/SystemHealthStrip';

// One-page NexusFlow Console. Replaces the previous layout, which stacked
// every real widget vertically down one very tall page (Header -> System
// tiles -> Onboarding -> Search -> KPIs -> Swarm telemetry -> Analytics ->
// Charts -> CFO/Data Engineer -> Gaps/Assumptions -> Suggestions/Ledger ->
// Ingestion). On a page that tall, a periodic re-render (the Live Swarm
// Telemetry panel's WebSocket heartbeat, in particular) could visibly
// shift the scroll position, which is what "it snaps back to the middle
// every few seconds" was actually about even after that panel's own
// scrollIntoView bug was fixed -- a tall single-scroll page makes any
// layout shift anywhere on it feel like the whole page moved.
//
// This version keeps every real widget exactly as it was (same data
// fetching, same endpoints, same error/empty states) and only changes how
// they're organized: five short, independently-scrolled sections behind a
// sidebar, matching the approved NexusFlow Console design mockup.
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
  const [activeView, setActiveView] = useState<ViewId>('overview');
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [healthLoading, setHealthLoading] = useState<boolean>(true);
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [dashboardRefreshTrigger, setDashboardRefreshTrigger] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    async function fetchHealth() {
      try {
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
        const res = await fetch(`${backendUrl}/api/v1/health`);
        if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
        const data: HealthData = await res.json();
        if (!cancelled) setHealth(data);
      } catch (err) {
        console.error("Health check failed:", err);
        if (!cancelled) setHealth(null);
      } finally {
        if (!cancelled) setHealthLoading(false);
      }
    }
    fetchHealth();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const bumpRefresh = () => setDashboardRefreshTrigger((prev) => prev + 1);

  return (
    <ClientProvider>
      <AppShell
        activeView={activeView}
        onChangeView={setActiveView}
        onOpenCommandPalette={() => setCommandPaletteOpen(true)}
        health={health}
        healthChecked={!healthLoading}
      >
        {activeView === 'overview' && (
          <OverviewView
            health={health}
            healthLoading={healthLoading}
            refreshTrigger={dashboardRefreshTrigger}
            onUploadSuccess={bumpRefresh}
          />
        )}
        {activeView === 'analytics' && (
          <AnalyticsView refreshTrigger={dashboardRefreshTrigger} />
        )}
        {activeView === 'ledger' && (
          <LedgerView
            refreshTrigger={dashboardRefreshTrigger}
            onUploadSuccess={bumpRefresh}
            onApplied={bumpRefresh}
          />
        )}
        {activeView === 'swarm' && (
          <SwarmView searchResult={searchResult} onQueryResult={(data) => setSearchResult(data)} />
        )}
        {activeView === 'trust' && (
          <TrustView refreshTrigger={dashboardRefreshTrigger} />
        )}
      </AppShell>

      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onSelectAction={(id) => setActiveView(id as ViewId)}
      />
    </ClientProvider>
  );
}
