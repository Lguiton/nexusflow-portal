"use client";

import { useState } from "react";
import { Radar, UploadCloud, Loader2, AlertCircle, Sparkles } from "lucide-react";
import { useClientId } from "./ClientContext";

// Real UI entry point for External Telemetry Scout, added 26 Aug 2026.
// Previously this agent was real and reachable, but only via /api/search's
// keyword routing (a tenant would have to guess a trigger phrase like
// "external telemetry" or "sample payload" in a free-text query, and there
// was no dashboard control that let them attach a sample_payload at all).
// This card calls the new dedicated POST /api/v1/telemetry/map-schema
// endpoint directly -- same agent (backend/agents/external_telemetry_scout.py),
// no routing keywords required.
//
// The schema mapping and sample row shown below are real, deterministic
// output (JSON flattening + type inference -- see _flatten_json /
// _infer_duckdb_type in that file), not an LLM guess. The "insights" list
// is the one part that is LLM-generated commentary on top of the already-
// real mapping; if no OpenAI client is configured for this tenant, the
// agent itself returns a real fallback sentence saying so, shown as-is.
interface TelemetryScoutResult {
  agent: string;
  status: "COMPLETED" | "ERROR";
  duckdb_schema_mapping?: Record<string, string>;
  sample_row?: Record<string, unknown>;
  insights: string[];
}

const TYPE_COLORS: Record<string, string> = {
  BIGINT: "text-cyan-400 bg-cyan-500/10",
  DOUBLE: "text-violet-400 bg-violet-500/10",
  BOOLEAN: "text-amber-400 bg-amber-500/10",
  VARCHAR: "text-slate-300 bg-slate-500/10",
};

const EXAMPLE_PAYLOAD = `{
  "event_id": "evt_9f2c1a",
  "amount_cents": 4599,
  "is_test": false,
  "customer": { "id": "cus_881", "region": "us-east-1" },
  "tags": ["renewal", "webhook"]
}`;

export default function TelemetryScoutCard() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  const authHeaders: Record<string, string> = authToken ? { Authorization: `Bearer ${authToken}` } : {};

  const [payloadText, setPayloadText] = useState("");
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TelemetryScoutResult | null>(null);

  const handleFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => setPayloadText(String(reader.result ?? ""));
    reader.readAsText(file);
  };

  const handleSubmit = async () => {
    if (!payloadText.trim()) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(payloadText);
      } catch (e: any) {
        throw new Error(`Not valid JSON: ${e.message}`);
      }
      const res = await fetch(`${backendUrl}/api/v1/telemetry/map-schema`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ sample_payload: parsed, query: query.trim() }),
      });
      if (res.status === 402) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Monthly AI usage cap reached.");
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      setResult(await res.json());
    } catch (err: any) {
      setError(err.message || "Schema mapping failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
          <Radar className="w-5 h-5 text-cyan-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">External Telemetry Scout</h2>
          <p className="text-xs text-slate-400">Paste a sample JSON payload from an external API or webhook to get a proposed DuckDB schema mapping.</p>
        </div>
      </div>

      <div className="p-6 space-y-4">
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Sample payload (JSON)</label>
            <label className="flex items-center gap-1.5 text-[11px] text-slate-500 hover:text-cyan-400 cursor-pointer transition-colors">
              <UploadCloud className="w-3.5 h-3.5" />
              Upload .json
              <input
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
          <textarea
            value={payloadText}
            onChange={(e) => setPayloadText(e.target.value)}
            placeholder={EXAMPLE_PAYLOAD}
            rows={7}
            spellCheck={false}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg py-2.5 px-3 text-xs font-mono text-slate-200 placeholder-slate-700 focus:outline-none focus:border-cyan-500 transition-colors resize-y"
          />
        </div>

        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={'Optional: what should the commentary focus on? (e.g. "naming clarity")'}
            className="flex-1 bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-cyan-500 transition-colors"
          />
          <button
            onClick={handleSubmit}
            disabled={submitting || !authReady || !payloadText.trim()}
            className="bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5 shrink-0"
          >
            {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            Map Schema
          </button>
        </div>

        {error && (
          <p className="text-xs text-rose-400 flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" /> {error}
          </p>
        )}

        {result && result.status === "COMPLETED" && (
          <div className="border-t border-slate-800 pt-4 space-y-4">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">
                Proposed DuckDB Schema ({Object.keys(result.duckdb_schema_mapping ?? {}).length} column{Object.keys(result.duckdb_schema_mapping ?? {}).length === 1 ? "" : "s"})
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                {Object.entries(result.duckdb_schema_mapping ?? {}).map(([col, type]) => (
                  <div key={col} className="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs">
                    <span className="text-slate-300 font-mono truncate mr-2">{col}</span>
                    {/* eslint-disable-next-line security/detect-object-injection -- type comes from Object.entries(result.duckdb_schema_mapping) and is used only to look up a CSS class in a fixed local table, with a safe fallback */}
                    <span className={`px-1.5 py-0.5 rounded font-mono text-[10px] font-semibold shrink-0 ${TYPE_COLORS[type] ?? "text-slate-400 bg-slate-500/10"}`}>
                      {type}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {result.insights?.length > 0 && (
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Scout Commentary</p>
                <ul className="space-y-1.5">
                  {result.insights.map((insight, i) => (
                    <li key={i} className="text-xs text-slate-400 leading-relaxed flex gap-2">
                      <span className="text-cyan-500 shrink-0">•</span>
                      {insight}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-[10.5px] text-slate-600 leading-relaxed">
              This mapping is proposed only -- nothing is created or altered in your ledger schema by this card. Use it to review column names and types before wiring a real ingestion pipeline for this source.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
