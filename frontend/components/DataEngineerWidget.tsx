'use client';

import React, { useState, useEffect } from 'react';
import { Database, ShieldAlert, CheckCircle2, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { useClientId } from "./ClientContext";

interface DataEngineerResponse {
  agent: string;
  status: string;
  recommendations: string[];
}

export default function DataEngineerWidget({ refreshTrigger = 0 }: { refreshTrigger?: number }) {
  const [data, setData] = useState<DataEngineerResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  let currentClientId = "default_client";
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) {
      currentClientId = clientCtx.clientId;
    }
  } catch (e) {}

  const fetchAudit = async () => {
    setLoading(true);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const token = typeof window !== 'undefined' ? sessionStorage.getItem('nexus_access_token') : null;

      const res = await fetch(`${backendUrl}/api/v1/data/schema-audit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-client-id': currentClientId,
          ...(token ? { 'Authorization': `Bearer ${token}` } : {})
        }
      });

      if (!res.ok) throw new Error("Schema audit failed.");
      const result = await res.json();
      setData(result);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to fetch schema audit.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAudit();
  }, [currentClientId, refreshTrigger]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-lg flex flex-col overflow-hidden">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
            <Database className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              Data Engineer Audit (Agent #02)
            </h2>
            <p className="text-xs text-slate-400">Automated pipeline integrity & schema hygiene</p>
          </div>
        </div>
        <button 
          onClick={fetchAudit} 
          disabled={loading}
          className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-colors flex items-center gap-1 text-xs"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Re-Audit</span>
        </button>
      </div>

      <div className="p-6 flex-1">
        {loading && !data ? (
          <div className="text-emerald-400 flex items-center justify-center py-8 gap-2">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>Analyzing pipeline schema...</span>
          </div>
        ) : error ? (
          <div className="text-rose-400 text-sm py-4 flex items-center gap-2">
            <ShieldAlert className="w-4 h-4" />
            <span>{error}</span>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between text-xs text-slate-400 bg-slate-950/40 p-3 rounded-lg border border-slate-800/60">
              <span>Agent Status: <strong className="text-emerald-400">{data?.status}</strong></span>
              <span>Tenant: <strong className="text-indigo-400">{currentClientId}</strong></span>
            </div>

            <div className="space-y-2.5">
              <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2 mb-2">
                <Sparkles className="w-4 h-4 text-emerald-400" />
                Pipeline & Hygiene Recommendations
              </h3>
              {data?.recommendations?.map((rec, idx) => (
                <div key={idx} className="flex items-start gap-3 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
                  <p className="text-sm text-slate-300 leading-relaxed">{rec}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
