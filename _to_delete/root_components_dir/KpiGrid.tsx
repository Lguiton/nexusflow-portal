"use client";

import React from 'react';
import KpiCard from './KpiCard';
import { Database, Activity, CheckCircle2, Zap } from 'lucide-react';

export default function KpiGrid() {
  // TODO: In the next step, we will wire this up to a custom hook
  // to fetch the real DuckDB row_count from your FastAPI backend.
  const currentIngestionRows = "14,230"; // Placeholder for UI testing

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {/* 1. Data Ingestion Volume - Ready to wire up */}
      <KpiCard
        title="Data Ingestion Volume"
        value={currentIngestionRows}
        icon={Database}
        trend="Active"
        status="normal"
        footerText="Rows processed"
      />

      {/* 2. Registered Agents - Blocked on startup registry */}
      <KpiCard
        title="Registered Agents"
        value="-- / 13"
        icon={Zap}
        trend="Pending"
        status="warning"
        footerText="Awaiting backend registry"
      />

      {/* 3. Task Success Rate - Blocked on persistent counters */}
      <KpiCard
        title="Task Success Rate"
        value="--%"
        icon={CheckCircle2}
        status="warning"
        footerText="Awaiting task counters"
      />

      {/* 4. Avg Execution Time - Blocked on real routing */}
      <KpiCard
        title="Avg Execution Time"
        value="-- s"
        icon={Activity}
        status="warning"
        footerText="Awaiting swarm routing"
      />
    </div>
  );
}
