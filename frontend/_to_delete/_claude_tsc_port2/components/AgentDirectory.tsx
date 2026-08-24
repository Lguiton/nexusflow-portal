"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, AlertCircle, Loader2 } from "lucide-react";
import { useClientId } from "./ClientContext";

// Sub-Agent Directory. The 8 rows in TRACKED_ORDER are real, live status --
// sourced from GET /api/v1/metrics/swarm's `agent_status_map` (did this
// agent's Python module import cleanly at server startup?) and
// `agent_failures` (the real exception message, if it didn't). This is not
// a design mockup with hardcoded "VERIFIED" badges -- if a real agent
// module fails to import, its dot and label reflect that here, live.
//
// The 5 rows in UNTRACKED are honestly disclosed, not fabricated: they are
// named in backend/agent_registry.py's own "OPEN QUESTION" comment as part
// of the originally-described 13-agent roster, but are not covered by
// get_swarm_metrics()'s health check. bi_visualization_architect is
// separately confirmed real and wired (backend/main.py imports and calls
// it directly for /api/v1/bi/chart-suite) despite not being tracked by the
// registry; the other four remain genuinely unconfirmed. Same "say the
// real gap out loud" approach as KnownGapsPanel, applied to the roster.
const TRACKED_ORDER = [
  "orchestrator",
  "virtual_cfo",
  "data_engineer",
  "bi_engineer",
  "predictive_forecaster",
  "saas_strategist",
  "report_generator",
  "ops_shield",
];

const TRACKED_META: Record<string, { label: string; description: string }> = {
  orchestrator: { label: "Orchestrator", description: "Routes every Cognitive Search query to the specialist agent best suited to answer it." },
  virtual_cfo: { label: "Virtual CFO", description: "Generates CFO-style financial briefings grounded in this tenant's real ledger, not a template narrative." },
  data_engineer: { label: "Data Engineer", description: "Audits ledger schema and data quality for this tenant on demand." },
  bi_engineer: { label: "BI Engineer", description: "Powers the statistical/BI analytics summary (revenue, expense, net profit) computed directly from the ledger." },
  predictive_forecaster: { label: "Predictive Forecaster", description: "Intended to generate revenue forecasts once enough monthly history exists -- module is tracked as loaded, but no forecast endpoint is wired to this dashboard yet." },
  saas_strategist: { label: "SaaS Strategist", description: "Intended to produce growth and strategy recommendations from this tenant's real usage data -- module is tracked as loaded, no dedicated endpoint confirmed wired yet." },
  report_generator: { label: "Report Generator", description: "Intended to compile stakeholder-ready reports from metrics already computed elsewhere -- module is tracked as loaded, no dedicated endpoint confirmed wired yet." },
  ops_shield: { label: "Ops Shield", description: "Intended to screen search queries for policy violations -- module is tracked as loaded, no dedicated endpoint confirmed wired yet." },
};

const UNTRACKED: { label: string; tier: string; description: string }[] = [
  { label: "BI Visualization Architect", tier: "WIRED, UNTRACKED", description: "Builds the pie/line/histogram chart suite from real ledger data (POST /api/v1/bi/chart-suite). Confirmed real and wired via backend/main.py, but not one of the 8 modules the registry health-check tracks." },
  { label: "Ingestion Engine", tier: "NOT BUILT YET", description: "Named in the original 13-agent roster spec; CSV ingestion is currently handled inline by the upload endpoint instead of a standalone module." },
  { label: "Schema Mapper", tier: "FOLDED IN", description: "Confirmed not a standalone agent -- its job (DuckDB indexing, tenant isolation) lives directly in the database layer (db_manager.py)." },
  { label: "Data Analyst", tier: "UNCONFIRMED", description: "Named in the original roster spec; not yet independently confirmed as a built module." },
  { label: "External Telemetry Scout", tier: "UNCONFIRMED", description: "Named in the original roster spec; not yet independently confirmed as a built module." },
];

interface SwarmMetrics {
  registered_agents: number;
  total_capacity: number;
  agent_status_map: Record<string, boolean>;
  agent_failures: Record<string, string>;
}

export default function AgentDirectory() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [data, setData] = useState<SwarmMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openRow, setOpenRow] = useState<string | null>(null);

  const fetchSwarmMetrics = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const res = await fetch(`${backendUrl}/api/v1/metrics/swarm`, {
        headers: { ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}) },
        signal,
      });
      if (!res.ok) throw new Error(`Swarm metrics request failed: ${res.status}`);
      setData(await res.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Agent directory fetch failed:", err);
      setError(err.message || "Unable to load agent roster right now.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchSwarmMetrics(controller.signal);
    return () => controller.abort();
  }, [fetchSwarmMetrics]);

  const toggle = (key: string) => setOpenRow((prev) => (prev === key ? null : key));

  const statusMap = data?.agent_status_map ?? {};
  const failures = data?.agent_failures ?? {};
  const trackedKeys = Object.keys(statusMap).length > 0
    ? TRACKED_ORDER.filter((k) => k in statusMap)
    : [];
  const verifiedCount = trackedKeys.filter((k) => statusMap[k]).length;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5">
        <h2 className="text-lg font-bold text-white">Sub-Agent Directory</h2>
        <p className="text-xs text-slate-400 mt-0.5">
          {loading && !data
            ? "Checking live module status..."
            : `${verifiedCount} of ${TRACKED_ORDER.length} registry-tracked modules verified live · click an agent for its job description`}
        </p>
      </div>

      <div className="p-4 flex-1">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-cyan-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Checking live module status...</p>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {trackedKeys.map((key) => {
              const isUp = statusMap[key] === true;
              const meta = TRACKED_META[key] ?? { label: key, description: "No description on file." };
              const failureReason = failures[key];
              const open = openRow === key;
              return (
                <div key={key} className="border border-slate-800 rounded-lg bg-slate-950/50 overflow-hidden">
                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left"
                    onClick={() => toggle(key)}
                    aria-expanded={open}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isUp ? "bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.25)]" : "bg-rose-500 shadow-[0_0_0_3px_rgba(244,63,94,0.25)]"}`} />
                    <span className="text-[13px] font-semibold text-slate-200">{meta.label}</span>
                    <span className={`ml-auto mr-1 text-[10px] font-mono ${isUp ? "text-emerald-400" : "text-rose-400"}`}>
                      {isUp ? "VERIFIED" : "DEGRADED"}
                    </span>
                    <ChevronDown className={`w-3.5 h-3.5 text-slate-500 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
                  </button>
                  {open && (
                    <div className="px-3 pb-3 pl-[26px] text-[11.5px] text-slate-400 leading-relaxed">
                      <p>{meta.description}</p>
                      {!isUp && failureReason && (
                        <p className="mt-1.5 text-rose-400/90 font-mono text-[10.5px]">Import error: {failureReason}</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {UNTRACKED.map((agent) => {
              const open = openRow === agent.label;
              return (
                <div key={agent.label} className="border border-slate-800 rounded-lg bg-slate-950/50 overflow-hidden">
                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left"
                    onClick={() => toggle(agent.label)}
                    aria-expanded={open}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${agent.tier === "WIRED, UNTRACKED" ? "bg-cyan-400 shadow-[0_0_0_3px_rgba(34,211,238,0.25)]" : "bg-slate-600"}`} />
                    <span className="text-[13px] font-semibold text-slate-200">{agent.label}</span>
                    <span className="ml-auto mr-1 text-[10px] font-mono text-slate-500">{agent.tier}</span>
                    <ChevronDown className={`w-3.5 h-3.5 text-slate-500 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
                  </button>
                  {open && (
                    <div className="px-3 pb-3 pl-[26px] text-[11.5px] text-slate-400 leading-relaxed">
                      <p>{agent.description}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
