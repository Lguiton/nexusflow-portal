"use client";

import React, { useState, useEffect } from 'react';
import { Terminal, AlertCircle } from 'lucide-react';
import { useClientId } from "./ClientContext";

interface LogEntry {
  timestamp: string;
  agent: string;
  status: string;
  message: string;
}

const RECONNECT_DELAY_MS = 3000;

export default function SwarmLogStreamer({ sessionId = "active_dashboard_session" }: { sessionId?: string }) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [authFailed, setAuthFailed] = useState<boolean>(false);

  let currentClientId = "default_client";
  let authToken: string | null = null;
  let authReady = false;
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) {
      currentClientId = clientCtx.clientId;
    }
    authToken = clientCtx?.authToken ?? null;
    authReady = clientCtx?.authReady ?? false;
  } catch (e) {}

  useEffect(() => {
    // Previously connected to `${backendWsUrl}/ws/swarm/${sessionId}` --
    // TWO real bugs here. (1) The real route is
    // "/ws/swarm/{client_id}/{session_id}", two path segments -- this was
    // missing {client_id} entirely, so it never matched the route at all.
    // (2) The handshake requires a verified ?token= query param (see
    // swarm.py -- there's no dev-fallback branch there); nothing was ever
    // attaching one. Either bug alone would keep this permanently stuck
    // on "Connecting...".
    if (!authReady) return;

    if (!authToken) {
      setAuthFailed(true);
      setIsConnected(false);
      return;
    }
    setAuthFailed(false);

    let cancelled = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (cancelled) return;
      const backendWsUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
      ws = new WebSocket(
        `${backendWsUrl}/ws/swarm/${currentClientId}/${sessionId}?token=${encodeURIComponent(authToken as string)}`
      );

      ws.onopen = () => {
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const newLog: LogEntry = {
            timestamp: new Date().toLocaleTimeString(),
            agent: data.agent || "System",
            status: data.status || "INFO",
            message: data.message || JSON.stringify(data)
          };
          setLogs(prev => [newLog, ...prev.slice(0, 49)]); // Keep last 50 logs
        } catch (err) {
          console.error("Failed to parse WebSocket telemetry:", err);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        if (cancelled) return;
        // 4008 = WS_4008_POLICY_VIOLATION (backend rejected the token).
        // Retrying immediately with the same token would just fail again
        // in a tight loop -- surface it instead and let a genuine
        // authToken/authReady change (e.g. a fresh dev-login) trigger the
        // next attempt via the effect's own dependency array.
        if (event.code === 4008) {
          setAuthFailed(true);
          return;
        }
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [sessionId, currentClientId, authToken, authReady]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800 mb-4">
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-indigo-400" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-white">NexusFlow Live Swarm Telemetry</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : authFailed ? 'bg-rose-500' : 'bg-amber-500'}`}></span>
          <span className="text-xs text-slate-400 font-mono">
            {isConnected ? 'WS Stream Active' : authFailed ? 'Authentication Failed' : 'Connecting...'}
          </span>
        </div>
      </div>

      <div className="bg-slate-950 rounded-lg p-4 font-mono text-xs h-48 overflow-y-auto space-y-2 border border-slate-900">
        {authFailed ? (
          <div className="flex items-center gap-2 text-rose-400">
            <AlertCircle className="w-4 h-4" />
            <p>Unable to authenticate the telemetry stream. Check that the dev-login endpoint is reachable.</p>
          </div>
        ) : logs.length === 0 ? (
          <p className="text-slate-500 italic">Awaiting live swarm telemetry stream...</p>
        ) : (
          logs.map((log, idx) => (
            <div key={idx} className="flex items-start gap-3 border-b border-slate-900/50 pb-1">
              <span className="text-slate-500">{log.timestamp}</span>
              <span className="text-indigo-400 font-semibold">[{log.agent}]</span>
              <span className={`px-1.5 rounded text-[10px] ${log.status === 'CONNECTED' ? 'bg-emerald-950 text-emerald-400' : 'bg-slate-800 text-slate-300'}`}>
                {log.status}
              </span>
              <span className="text-slate-300">{log.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
