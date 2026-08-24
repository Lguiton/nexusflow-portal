"use client";

import React, { useState, useEffect } from 'react';
import { Activity } from 'lucide-react';
import { useClientId } from './ClientContext';

// The `activeCount` prop this component used to accept was destructured
// but never actually read anywhere in the body -- this widget has always
// fetched its own real data from /api/v1/metrics/swarm independently.
// That fetch, however, sent NO Authorization header at all, and
// GET /api/v1/metrics/swarm requires a valid JWT (Depends on
// verify_jwt_and_get_client_id) -- so every request was rejected with 401,
// `res.ok` was always false, and agents/capacity stayed at their initial
// "--" placeholders forever, regardless of real swarm state. This is the
// real cause of the "Sub-Agent Network: -- / -- Active" seen permanently
// on the dashboard -- a separate bug from the /api/v1/health field-name
// mismatch, not the same one.
export default function SubAgentWidget() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [agents, setAgents] = useState<string>("--");
  const [capacity, setCapacity] = useState<string>("--");

  useEffect(() => {
    if (!authReady) return;

    async function fetchSwarmMetrics() {
      try {
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
        const res = await fetch(`${backendUrl}/api/v1/metrics/swarm`, {
          headers: {
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
        });
        if (res.ok) {
          const data = await res.json();
          setAgents(data.registered_agents.toString());
          setCapacity(data.total_capacity.toString());
        } else {
          console.error(`Sub-agent metrics request failed: ${res.status}`);
        }
      } catch (err) {
        console.error("Failed to fetch sub-agent metrics:", err);
      }
    }
    fetchSwarmMetrics();
  }, [authToken, authReady]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Sub-Agent Network</span>
        <Activity className="w-5 h-5 text-cyan-400" />
      </div>
      <div className="mt-4">
        <p className="text-2xl font-bold text-white">
          {agents} / {capacity} <span className="text-lg font-semibold text-slate-300">Active</span>
        </p>
        <p className="text-xs text-slate-500 mt-1">Ready for Ingestion & Analytics</p>
      </div>
    </div>
  );
}
