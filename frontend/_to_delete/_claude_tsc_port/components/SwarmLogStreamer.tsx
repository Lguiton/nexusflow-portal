"use client";

import React, { useEffect, useRef, useState } from 'react';
import { Terminal, AlertCircle, Shield } from 'lucide-react';
import { useClientId } from "./ClientContext";

interface LogEntry {
  timestamp: string;
  agent: string;
  status: string;
  message: string;
  stepId?: string;
}

const RECONNECT_DELAY_MS = 3000;
const MAX_LOGS = 50;

export default function SwarmLogStreamer({ sessionId = "active_dashboard_session" }: { sessionId?: string }) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [authFailed, setAuthFailed] = useState<boolean>(false);

  let currentClientId = "default_client";
  let authToken: string | null = null;
  let authReady = false;
  let retryLogin: (() => void) | undefined;
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) {
      currentClientId = clientCtx.clientId;
    }
    authToken = clientCtx?.authToken ?? null;
    authReady = clientCtx?.authReady ?? false;
    retryLogin = clientCtx?.retryLogin;
  } catch (e) {}

  // Fixed 2026-08-23 -- this used to be a sentinel div at the bottom of the
  // log list plus `terminalEndRef.current?.scrollIntoView({behavior:
  // "smooth"})`. scrollIntoView walks up through EVERY scrollable ancestor,
  // not just this panel's own `overflow-y-auto` box -- so on every new log
  // line (the backend sends a HEARTBEAT over the WebSocket every 5 seconds,
  // see backend/routers/swarm.py) it was also smooth-scrolling the whole
  // page/window to bring this panel into view, fighting any manual
  // scrolling and snapping the page back to this section every few
  // seconds. That's the reported "choppy scroll / pulls back to the
  // middle" bug.
  //
  // Fix: scroll only this panel's own log container directly via
  // `scrollTop`, which never touches any ancestor's scroll position. Same
  // auto-scroll-to-latest-entry behavior, but scoped to exactly the one
  // element that should move.
  const logContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = logContainerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    // Route is "/ws/swarm/{client_id}/{session_id}" plus a verified
    // ?token= query param -- see backend/routers/swarm.py. The backend
    // itself rejects any token whose embedded client_id doesn't match the
    // path client_id, closing with code 4008 (WS_4008_POLICY_VIOLATION) --
    // the same code it uses for a missing/invalid token. Both cases are
    // therefore already handled correctly below without needing a
    // separate client-side JWT decode/compare.
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
            message: data.message || JSON.stringify(data),
            stepId: typeof data.stepId === "string" ? data.stepId : undefined,
          };
          // Update-in-place by stepId when the backend sends one (so a
          // PROCESSING row can later be replaced by its own COMPLETE row
          // instead of appending a second one); today's real messages
          // (CONNECTED / HEARTBEAT) don't send a stepId, so this simply
          // falls through to appending, same as before.
          setLogs((prev) => {
            if (newLog.stepId) {
              const existingIndex = prev.findIndex((l) => l.stepId === newLog.stepId);
              if (existingIndex !== -1) {
                const updated = [...prev];
                updated[existingIndex] = newLog;
                return updated;
              }
            }
            return [...prev, newLog].slice(-MAX_LOGS);
          });
        } catch (err) {
          console.error("Failed to parse WebSocket telemetry:", err);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        if (cancelled) return;
        // 4008 = WS_4008_POLICY_VIOLATION (backend rejected the token, or
        // a token/path client_id mismatch). Retrying immediately with the
        // same token would just fail again in a tight loop -- surface it
        // instead and let a genuine authToken/authReady change (a fresh
        // dev-login, e.g. via the Retry Authentication button) trigger
        // the next attempt via the effect's own dependency array.
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
          <span className="text-xs text-slate-400 font-mono flex items-center gap-1">
            {isConnected ? (
              <>
                <Shield className="w-3 h-3 text-emerald-400" />
                Verified Tenant: {currentClientId}
              </>
            ) : authFailed ? (
              'Authentication Failed'
            ) : (
              'Connecting...'
            )}
          </span>
        </div>
      </div>

      <div ref={logContainerRef} className="bg-slate-950 rounded-lg p-4 font-mono text-xs h-48 overflow-y-auto space-y-2 border border-slate-900">
        {authFailed ? (
          <div className="flex flex-col items-center justify-center gap-3 text-rose-400 py-4">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              <p>Unable to authenticate the telemetry stream.</p>
            </div>
            {retryLogin && (
              <button
                onClick={() => retryLogin && retryLogin()}
                className="bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded text-xs font-semibold transition-colors"
              >
                Retry Authentication
              </button>
            )}
          </div>
        ) : logs.length === 0 ? (
          <p className="text-slate-500 italic">Awaiting live swarm telemetry stream...</p>
        ) : (
          logs.map((log, idx) => (
            <div
              key={log.stepId ?? `${log.agent}-${idx}-${log.timestamp}`}
              className="flex items-start gap-3 border-b border-slate-900/50 pb-1"
            >
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
