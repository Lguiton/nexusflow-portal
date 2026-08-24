"use client";

import { useCallback, useEffect, useState } from "react";
import { HelpCircle, Loader2, AlertCircle, Info } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-03: "What I don't know yet" panel. Every entry rendered here comes
// straight from POST /api/v1/insights/known-gaps -- a real, currently-true
// limitation for this tenant (see backend/gaps.py), never a placeholder or
// invented caveat. Trust-building by being upfront about real gaps rather
// than only showing what works.
interface Gap {
  key: string;
  title: string;
  detail: string;
}

interface KnownGapsResponse {
  client_id: string;
  row_count: number;
  gaps: Gap[];
}

interface KnownGapsPanelProps {
  refreshTrigger?: number;
}

export default function KnownGapsPanel({ refreshTrigger = 0 }: KnownGapsPanelProps) {
  const clientCtx = useClientId() as any;
  const currentClientId = clientCtx?.clientId || "CLI-001";
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [data, setData] = useState<KnownGapsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchGaps = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/api/v1/insights/known-gaps`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        signal,
      });
      if (!response.ok) {
        throw new Error(`Known-gaps request failed: ${response.status}`);
      }
      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Known-gaps fetch failed:", err);
      setError(err.message || "Unable to load known limitations right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [currentClientId, authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchGaps(controller.signal);
    return () => controller.abort();
  }, [fetchGaps, refreshTrigger]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-sky-500/10 border border-sky-500/20 rounded-lg">
          <HelpCircle className="w-5 h-5 text-sky-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">What NexusFlow Doesn't Know Yet</h2>
          <p className="text-xs text-slate-400">Real, current limitations for this tenant -- not a hedge, an actual list</p>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-sky-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Checking current data coverage...</p>
          </div>
        ) : data && data.gaps.length === 0 ? (
          <div className="flex items-center gap-3 text-emerald-400 py-4">
            <Info className="w-5 h-5 shrink-0" />
            <p className="text-sm">No known gaps for this tenant right now.</p>
          </div>
        ) : (
          <div className="space-y-3 animate-in fade-in duration-500">
            {(data?.gaps ?? []).map((gap) => (
              <div key={gap.key} className="flex gap-3 items-start bg-slate-800/30 p-3.5 rounded-lg border border-slate-700/30">
                <Info className="w-4 h-4 text-sky-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-slate-200">{gap.title}</p>
                  <p className="text-xs text-slate-400 mt-1 leading-relaxed">{gap.detail}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
