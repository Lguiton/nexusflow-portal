"use client";

import React, { useState, useEffect, useRef, FormEvent, ChangeEvent } from "react";
import { Terminal, CheckCircle, Loader2, AlertCircle } from "lucide-react";
import { useClientId } from "./ClientContext";

interface LogStep {
  agent: string;
  status: "PROCESSING" | "COMPLETE";
  payload: Record<string, any> | null;
  stepId?: string;
}

export default function SwarmLogStreamer({ sessionId }: { sessionId: string }) {
  let clientId = "default_client";
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) {
      clientId = clientCtx.clientId;
    }
  } catch (e) {
    // Fallback if context is unhydrated
  }

  const [logs, setLogs] = useState<LogStep[]>([]);
  const [connected, setConnected] = useState<boolean>(false);
  const [errored, setErrored] = useState<boolean>(false);
  const [inputPrompt, setInputPrompt] = useState<string>("");
  
  const wsRef = useRef<WebSocket | null>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);
  const pendingByAgent = useRef<Map<string, number[]>>(new Map());

  useEffect(() => {
    if (!sessionId || !clientId) return;

    let isCurrent = true;

    setLogs([]);
    pendingByAgent.current.clear();
    if (isCurrent) {
      setErrored(false);
      setConnected(false);
    }

    const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = typeof window !== "undefined" && window.location.host ? window.location.host : "localhost:8000";
    const wsUrl = `${protocol}//${host}/ws/swarm/${clientId}/${sessionId}`;

    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      if (isCurrent) setConnected(true);
    };

    socket.onmessage = (event: MessageEvent) => {
      if (!isCurrent) return;
      try {
        const data: LogStep = JSON.parse(event.data);
        
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
      } catch (err) {
        console.error("Malformed swarm message:", err);
      }
    };

    socket.onerror = () => {
      if (isCurrent) setErrored(true);
    };

    socket.onclose = () => {
      if (isCurrent) setConnected(false);
    };

    wsRef.current = socket;
    
    return () => {
      isCurrent = false;
      socket.close();
    };
  }, [clientId, sessionId]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const sendQuery = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || !inputPrompt.trim()) return;
    socket.send(JSON.stringify({ prompt: inputPrompt }));
    setInputPrompt("");
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-2xl text-slate-100 flex flex-col h-[500px]">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-indigo-400" />
          <h3 className="font-semibold text-sm">NexusFlow Live Swarm Telemetry</h3>
        </div>
        <span
          className={`text-xs px-2.5 py-1 rounded-full border ${
            errored
              ? "bg-red-950 text-red-300 border-red-800"
              : connected
              ? "bg-indigo-950 text-indigo-300 border-indigo-800"
              : "bg-slate-800 text-slate-400 border-slate-700"
          }`}
        >
          {errored ? "Connection error" : connected ? `Client: ${clientId}` : "Connecting..."}
        </span>
      </div>

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
        {errored && (
          <div className="flex items-center gap-2 text-red-400 text-xs">
            <AlertCircle className="w-4 h-4" />
            Lost connection to swarm backend.
          </div>
        )}
        <div ref={terminalEndRef} />
      </div>

      <form onSubmit={sendQuery} className="mt-4 flex gap-2">
        <input
          type="text"
          value={inputPrompt}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setInputPrompt(e.target.value)}
          disabled={!connected}
          placeholder="Ask swarm anything (e.g. 'Forecast ARR for Q3 with historical context')..."
          className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 font-sans disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!connected}
          className="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors font-sans shadow-lg shadow-indigo-600/20 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Stream Swarm
        </button>
      </form>
    </div>
  );
}