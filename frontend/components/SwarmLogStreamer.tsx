"use client";

import React, { useState, useEffect, useRef, FormEvent, ChangeEvent } from "react";
import { Terminal, CheckCircle, Loader2, AlertCircle, Shield } from "lucide-react";
import { useClientId } from "./ClientContext";

interface LogStep {
  agent: string;
  status: "PROCESSING" | "COMPLETE" | "ERROR";
  payload: Record<string, any> | null;
  stepId?: string;
}

const MAX_PROMPT_LENGTH = 500;
const SUBMISSION_COOLDOWN_MS = 1000;

function decodeTokenClientId(token: string): string | null {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(atob(base64).split('').map(c => {
      return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
    }).join(''));
    return JSON.parse(jsonPayload).client_id || null;
  } catch (e) {
    return null;
  }
}

export default function SwarmLogStreamer({ sessionId = "demo_session" }: { sessionId?: string }) {
  let clientId = "default_client";
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId && typeof clientCtx.clientId === "string") {
      clientId = clientCtx.clientId.trim();
    }
  } catch (e) {}

  const [logs, setLogs] = useState<LogStep[]>([]);
  const [connected, setConnected] = useState<boolean>(false);
  const [errored, setErrored] = useState<boolean>(false);
  const [authError, setAuthError] = useState<boolean>(false);
  const [inputPrompt, setInputPrompt] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [verifiedTenant, setVerifiedTenant] = useState<string>("Initializing...");
  
  const wsRef = useRef<WebSocket | null>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);
  const pendingByAgent = useRef<Map<string, number[]>>(new Map());
  const lastSubmitTime = useRef<number>(0);

  useEffect(() => {
    if (!sessionId) return;

    const authToken = typeof window !== "undefined" ? sessionStorage.getItem("nexus_access_token") : null;

    if (!authToken) {
      setAuthError(true);
      setErrored(true);
      return;
    }

    const tokenClientId = decodeTokenClientId(authToken);
    if (!tokenClientId) {
      setAuthError(true);
      setErrored(true);
      return;
    }

    setVerifiedTenant(tokenClientId);

    let isCurrent = true;
    setLogs([]);
    pendingByAgent.current.clear();
    setErrored(false);
    setConnected(false);

    const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = typeof window !== "undefined" && window.location.hostname ? `${window.location.hostname}:8000` : "127.0.0.1:8000";
    
    const wsUrl = `${protocol}//${host}/ws/swarm/${encodeURIComponent(tokenClientId)}/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(authToken)}`;
    const socket = new WebSocket(wsUrl);

    socket.onopen = () => { if (isCurrent) setConnected(true); };

    socket.onmessage = (event: MessageEvent) => {
      if (!isCurrent) return;
      try {
        const rawData = JSON.parse(event.data);
        const data: LogStep = {
          agent: typeof rawData.agent === "string" ? rawData.agent.slice(0, 50) : "UnknownAgent",
          status: ["PROCESSING", "COMPLETE", "ERROR"].includes(rawData.status) ? rawData.status : "COMPLETE",
          payload: rawData.payload && typeof rawData.payload === "object" ? rawData.payload : {},
          stepId: typeof rawData.stepId === "string" ? rawData.stepId.slice(0, 64) : undefined
        };
        
        setLogs((prev: LogStep[]) => {
          if (data.stepId) {
            const existingIndex = prev.findIndex((l: LogStep) => l.stepId === data.stepId);
            if (existingIndex !== -1) {
              const updated = [...prev];
              updated[existingIndex] = data;
              return updated;
            }
            return [...prev, data];
          }
          const queue = pendingByAgent.current.get(data.agent) ?? [];
          if (data.status === "PROCESSING") {
            const newIndex = prev.length;
            pendingByAgent.current.set(data.agent, [...queue, newIndex]);
            return [...prev, data];
          }
          if (data.status === "COMPLETE" && queue.length > 0) {
            const [targetIndex, ...rest] = queue;
            pendingByAgent.current.set(data.agent, rest);
            const updated = [...prev];
            updated[targetIndex] = data;
            return updated;
          }
          return [...prev, data];
        });
      } catch (err) {}
    };

    socket.onerror = () => { if (isCurrent) setErrored(true); };

    socket.onclose = (event) => {
      if (isCurrent) {
        setConnected(false);
        if (event.code === 4008) {
          setAuthError(true);
          setErrored(true);
        }
      }
    };

    wsRef.current = socket;
    return () => { isCurrent = false; socket.close(); };
  }, [sessionId, authError]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // DEV-ONLY: Authenticate Button Logic
  const handleDevAuth = async () => {
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/auth/dev-token?client_id=${clientId}`);
      const data = await res.json();
      if (data.access_token) {
        sessionStorage.setItem("nexus_access_token", data.access_token);
        setAuthError(false);
        setErrored(false);
      }
    } catch (err) {
      console.error("Failed to fetch dev token", err);
    }
  };

  const sendQuery = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    const trimmed = inputPrompt.trim();
    if (!trimmed || trimmed.length > MAX_PROMPT_LENGTH) return;

    const now = Date.now();
    if (now - lastSubmitTime.current < SUBMISSION_COOLDOWN_MS) return;
    lastSubmitTime.current = now;

    setIsSubmitting(true);
    try {
      socket.send(JSON.stringify({ prompt: trimmed, client_id: clientId }));
      setInputPrompt("");
    } catch (err) {
    } finally {
      setTimeout(() => setIsSubmitting(false), 400);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-2xl text-slate-100 flex flex-col h-[500px]">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-indigo-400" />
          <h3 className="font-semibold text-sm flex items-center gap-2">
            NexusFlow Live Swarm Telemetry
            <Shield className="w-4 h-4 text-emerald-400" />
          </h3>
        </div>
        <span
          className={`text-xs px-2.5 py-1 rounded-full border ${
            authError
              ? "bg-red-950 text-red-300 border-red-800"
              : connected
              ? "bg-emerald-950 text-emerald-300 border-emerald-800"
              : "bg-slate-800 text-slate-400 border-slate-700"
          }`}
        >
          {authError ? "Unauthorized" : connected ? `Verified Tenant: ${verifiedTenant}` : "Authenticating..."}
        </span>
      </div>

      {authError && (
        <div className="bg-red-950/40 border border-red-900/60 rounded-lg p-3 mb-3 text-red-300 text-xs flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>Enterprise Security Blocked Connection: Valid JWT Token Required.</span>
          </div>
          <button 
            onClick={handleDevAuth} 
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-2 rounded text-xs font-semibold transition-colors flex justify-center items-center"
          >
            Generate Secure Dev Token to Unlock
          </button>
        </div>
      )}

      {errored && !authError && (
        <div className="flex items-center gap-2 text-red-400 text-xs mb-3">
          <AlertCircle className="w-4 h-4" />
          Backend rejected connection. Make sure Uvicorn is running on port 8000.
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-3 pr-2 font-mono text-xs">
        {logs.map((log: LogStep, idx: number) => (
          <div
            key={log.stepId ?? `${log.agent}-${idx}-${log.status}`}
            className="flex items-start gap-3 bg-slate-950/60 p-3 rounded-lg border border-slate-800/80"
          >
            {log.status === "PROCESSING" ? (
              <Loader2 className="w-4 h-4 text-amber-400 animate-spin mt-0.5 shrink-0" />
            ) : (
              <CheckCircle className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
            )}
            <div className="flex-1 overflow-hidden">
              <div className="flex items-center justify-between">
                <span className="font-bold text-indigo-300">{log.agent}</span>
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded ${
                    log.status === "COMPLETE"
                      ? "bg-emerald-950 text-emerald-300"
                      : "bg-amber-950 text-amber-300"
                  }`}
                >
                  {log.status}
                </span>
              </div>
              {log.payload && Object.keys(log.payload).length > 0 && (
                <pre className="mt-2 text-[11px] text-slate-300 bg-slate-900 p-2 rounded overflow-x-auto">
                  {JSON.stringify(log.payload, null, 2)}
                </pre>
              )}
            </div>
          </div>
        ))}
        <div ref={terminalEndRef} />
      </div>

      <form onSubmit={sendQuery} className="mt-4 flex flex-col gap-1.5">
        <div className="flex gap-2">
          <input
            type="text"
            value={inputPrompt}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setInputPrompt(e.target.value)}
            disabled={!connected || isSubmitting || authError}
            maxLength={MAX_PROMPT_LENGTH}
            placeholder={authError ? "Waiting for Dev Token..." : "Ask swarm anything..."}
            className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 font-sans disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!connected || !inputPrompt.trim() || isSubmitting || authError}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors font-sans shadow-lg shadow-indigo-600/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Stream Swarm
          </button>
        </div>
        <div className="flex justify-between px-1 text-[10px] text-slate-500">
          <span>JWT Signature Verified Channel</span>
          <span>{inputPrompt.length}/{MAX_PROMPT_LENGTH} chars</span>
        </div>
      </form>
    </div>
  );
}