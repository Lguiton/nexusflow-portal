"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, AlertCircle, Loader2 } from "lucide-react";
import { useClientId } from "./ClientContext";

// Sub-Agent Directory. The 11 rows in TRACKED_ORDER are real, live status --
// sourced from GET /api/v1/metrics/swarm's `agent_status_map` (did this
// agent's Python module import cleanly at server startup?) and
// `agent_failures` (the real exception message, if it didn't). This is not
// a design mockup with hardcoded "VERIFIED" badges -- if a real agent
// module fails to import, its dot and label reflect that here, live.
//
// INDUCTED (27 Aug 2026, founder decision): scenario_modeler added here and
// to backend/agent_registry.py's EXPECTED_AGENTS as Agent #14 -- the
// platform's operating model is now 14 agents (Orchestrator + 13
// specialists), up from 13. See scenario_modeler.py's own header comment
// for the full history (it was a hardcoded stub until this same week).
//
// UPDATED (26 Aug 2026): bi_visualization_architect and external_telemetry_scout
// were confirmed real, live-routed modules (see backend/agent_registry.py's
// resolved comment) and added to EXPECTED_AGENTS, so both moved here from
// UNTRACKED -- they now report real live status same as the original 8.
//
// REMOVED (26 Aug 2026): this used to also render an UNTRACKED section for
// Ingestion Engine, Schema Mapper, and Data Analyst -- the last three names
// from the original 13-agent roster spec. All three are resolved, not
// missing (Ingestion Engine and Schema Mapper were folded into
// db_manager.py from the start; Data Analyst was a narration-only stub,
// confirmed retired, with no file left in the repo -- its duties were
// absorbed by BI Engineer). Per founder decision, a live status widget
// shouldn't permanently carry three rows whose entire content is "this
// doesn't need to exist" -- that history is recorded in the Master Build
// List instead. Also corrected the same day: TRACKED_META for
// predictive_forecaster, saas_strategist, report_generator, and ops_shield
// previously claimed "no dedicated endpoint confirmed wired yet" for all
// four -- false. Confirmed via backend/main.py: all four have real,
// dedicated endpoints (or, for ops_shield, run inline on every search
// request), not module-only stubs.
const TRACKED_ORDER = [
  "orchestrator",
  "virtual_cfo",
  "data_engineer",
  "bi_engineer",
  "predictive_forecaster",
  "saas_strategist",
  "report_generator",
  "ops_shield",
  "bi_visualization_architect",
  "external_telemetry_scout",
  "scenario_modeler",
];

const TRACKED_META: Record<string, { label: string; description: string }> = {
  orchestrator: { label: "Orchestrator", description: "Routes every Cognitive Search query to the specialist agent best suited to answer it." },
  virtual_cfo: { label: "Virtual CFO", description: "Generates CFO-style financial briefings grounded in this tenant's real ledger, not a template narrative." },
  data_engineer: { label: "Data Engineer", description: "Audits ledger schema and data quality for this tenant on demand." },
  bi_engineer: { label: "BI Engineer", description: "Powers the statistical/BI analytics summary (revenue, expense, net profit) computed directly from the ledger." },
  // BUG FIX (confirmed live 26 Aug 2026): all four of the descriptions below
  // used to claim "no dedicated endpoint confirmed wired yet" -- disproven
  // by reading backend/main.py directly, not assumed. Each is real.
  predictive_forecaster: { label: "Predictive Forecaster", description: "Generates revenue forecasts (POST /api/v1/predictive/forecast), with a backtesting endpoint (/api/v1/finance/forecast-accuracy) that compares every past forecast against real ledger revenue once it occurs. Forecasts require 4+ distinct months of ledger history -- reports INSUFFICIENT_HISTORY rather than a fabricated projection until then." },
  saas_strategist: { label: "SaaS Strategist", description: "Produces growth and strategy recommendations from this tenant's real usage data via POST /api/v1/saas/strategy -- powers the \"What should I do next?\" one-tap insight." },
  report_generator: { label: "Report Generator", description: "Compiles stakeholder-ready reports from metrics computed elsewhere via POST /api/v1/reports/stakeholder -- powers the \"Generate a report I can share\" one-tap insight." },
  ops_shield: { label: "Ops Shield", description: "A real LLM-backed semantic firewall that screens every /api/search query for prompt injection, cross-tenant access attempts, and malicious intent before it reaches the orchestrator -- fails closed (blocks the request) if the check itself errors out." },
  bi_visualization_architect: { label: "BI Visualization Architect", description: "Builds the pie/line/histogram chart suite from real ledger data (POST /api/v1/bi/chart-suite) -- confirmed real and wired, and now also registry-tracked." },
  // UPDATED (26 Aug 2026): now has a real dedicated UI entry point --
  // the Ledger & Data tab's "External Telemetry Scout" card calls
  // POST /api/v1/telemetry/map-schema directly, no routing keyword guess
  // required. Still also reachable via the orchestrator's router from
  // /api/search, unchanged.
  external_telemetry_scout: { label: "External Telemetry Scout", description: "Maps a sample external API/webhook JSON payload into a proposed DuckDB schema, via a real card on the Ledger & Data tab (POST /api/v1/telemetry/map-schema) or by routing a /api/search query containing terms like \"external telemetry\" or \"sample payload\"." },
  // INDUCTED (27 Aug 2026, founder decision): Agent #14 -- rebuilt from a
  // hardcoded stub into a real what-if simulator this same week (see
  // backend/agents/scenario_modeler.py's header comment).
  scenario_modeler: { label: "Scenario Modeler", description: "Runs what-if simulations (price change, new hire, churned account) against this tenant's real most-recent-month revenue/expense data, via a real card on the Analytics tab (POST /api/v1/predictive/scenario) -- projects monthly net and cash-runway impact before vs. after." },
};

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
  // eslint-disable-next-line security/detect-object-injection -- k comes from Object.keys(statusMap) filtered against the fixed TRACKED_ORDER allowlist -- never external input
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
              // eslint-disable-next-line security/detect-object-injection -- key comes from trackedKeys, itself Object.keys(statusMap) filtered against the fixed TRACKED_ORDER allowlist -- never external input
              const isUp = statusMap[key] === true;
              // eslint-disable-next-line security/detect-object-injection -- key comes from trackedKeys, itself Object.keys(statusMap) filtered against the fixed TRACKED_ORDER allowlist -- never external input
              const meta = TRACKED_META[key] ?? { label: key, description: "No description on file." };
              // eslint-disable-next-line security/detect-object-injection -- key comes from trackedKeys, itself Object.keys(statusMap) filtered against the fixed TRACKED_ORDER allowlist -- never external input
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
          </div>
        )}
      </div>
    </div>
  );
}
