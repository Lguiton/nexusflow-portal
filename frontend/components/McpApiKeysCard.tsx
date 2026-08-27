"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Plug, Loader2, Copy, Check, Trash2, AlertCircle, ShieldOff } from "lucide-react";
import { useClientId } from "./ClientContext";

// INT-01: lets an owner/admin generate a scoped, revocable API key for the
// read-only MCP tool server (backend/mcp_server.py, mounted at /mcp) --
// used to connect an external MCP client (Claude Desktop, another workflow
// tool) to this ONE tenant's analytics, without sharing a real login.
// The raw key is only ever shown once, right after creation -- this
// component (like BYOKSettingsCard) never receives it again afterward.
interface ApiKeyRow {
  key_id: number;
  label: string | null;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  active: boolean;
}

export default function McpApiKeysCard() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;
  const role: string | undefined = clientCtx?.user?.role;

  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<number | null>(null);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  const canManage = role === "owner" || role === "admin";

  const fetchKeys = useCallback(async () => {
    if (!authToken) return;
    setLoading(true);
    try {
      const res = await fetch(`${backendUrl}/api/v1/settings/api-keys`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setKeys(data.api_keys || []);
      }
    } catch (err) {
      console.error("Failed to load API keys:", err);
    } finally {
      setLoading(false);
    }
  }, [authToken, backendUrl]);

  useEffect(() => {
    if (!authReady || !canManage) {
      setLoading(false);
      return;
    }
    fetchKeys();
  }, [authReady, canManage, fetchKeys]);

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    setNewKey(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/settings/api-keys`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ label: label.trim() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      const data = await res.json();
      setNewKey(data.api_key);
      setLabel("");
      await fetchKeys();
    } catch (err: any) {
      setError(err.message || "Could not create an API key.");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: number) => {
    setRevokingId(keyId);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/settings/api-keys/${keyId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!res.ok) throw new Error(`Server status: ${res.status}`);
      await fetchKeys();
    } catch (err: any) {
      setError(err.message || "Could not revoke this key.");
    } finally {
      setRevokingId(null);
    }
  };

  const handleCopy = async () => {
    if (!newKey) return;
    try {
      await navigator.clipboard.writeText(newKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API can be unavailable (older browser, insecure
      // context) -- the raw key stays selectable/visible either way,
      // so a failed copy is a minor inconvenience, not a dead end.
    }
  };

  const mcpUrl = `${backendUrl}/mcp/`;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-teal-500/10 border border-teal-500/20 rounded-lg">
          <Plug className="w-5 h-5 text-teal-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">MCP Tool Server</h2>
          <p className="text-xs text-slate-400">
            Connect Claude Desktop or another MCP-aware tool to this tenant's read-only analytics.
          </p>
        </div>
      </div>

      <div className="p-6">
        {!canManage ? (
          <p className="text-sm text-slate-500 italic">Only an owner or admin can manage MCP API keys.</p>
        ) : (
          <div className="space-y-5">
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-slate-400 space-y-1">
              <div>
                Server URL:{" "}
                <code className="text-slate-200 bg-slate-900 px-1.5 py-0.5 rounded">{mcpUrl}</code>
              </div>
              <div>
                Auth: <code className="text-slate-200 bg-slate-900 px-1.5 py-0.5 rounded">Authorization: Bearer &lt;key&gt;</code>
              </div>
              <div className="text-slate-500">
                Read-only: seven tools (BI summary, forecast, ledger rows, KPI summary, MRR, assumptions, known gaps). No tool here can modify data.
              </div>
            </div>

            {newKey && (
              <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-3 space-y-2">
                <p className="text-xs text-emerald-300 font-semibold">
                  Copy this key now -- it will not be shown again.
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs text-slate-100 bg-slate-950 border border-slate-800 rounded px-2 py-1.5 overflow-x-auto whitespace-nowrap">
                    {newKey}
                  </code>
                  <button
                    onClick={handleCopy}
                    className="shrink-0 flex items-center gap-1 bg-slate-800 hover:bg-slate-700 text-slate-200 px-2.5 py-1.5 rounded text-xs transition-colors"
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    {copied ? "Copied" : "Copy"}
                  </button>
                </div>
              </div>
            )}

            <div className="flex gap-2">
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={'Label (e.g. "Claude Desktop")'}
                className="flex-1 bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-teal-500 transition-colors"
              />
              <button
                onClick={handleCreate}
                disabled={creating}
                className="bg-teal-600 hover:bg-teal-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors whitespace-nowrap"
              >
                {creating ? "Creating..." : "New API Key"}
              </button>
            </div>

            {error && (
              <p className="flex items-center gap-1.5 text-xs text-rose-400">
                <AlertCircle className="w-3.5 h-3.5" />
                {error}
              </p>
            )}

            {loading ? (
              <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading keys...
              </div>
            ) : keys.length === 0 ? (
              <p className="text-xs text-slate-500 italic">No API keys yet -- create one above to connect an MCP client.</p>
            ) : (
              <div className="space-y-2">
                {keys.map((k) => (
                  <div
                    key={k.key_id}
                    className="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-lg px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-sm text-slate-200">
                        <code className="text-xs text-slate-400">{k.key_prefix}...</code>
                        {k.label && <span className="truncate">{k.label}</span>}
                        {!k.active && (
                          <span className="flex items-center gap-1 text-[10px] text-rose-400 bg-rose-500/10 border border-rose-500/20 rounded px-1.5 py-0.5">
                            <ShieldOff className="w-3 h-3" /> revoked
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500">
                        Created {new Date(k.created_at).toLocaleDateString()}
                        {k.last_used_at ? ` · last used ${new Date(k.last_used_at).toLocaleDateString()}` : " · never used"}
                      </div>
                    </div>
                    {k.active && (
                      <button
                        onClick={() => handleRevoke(k.key_id)}
                        disabled={revokingId === k.key_id}
                        className="shrink-0 flex items-center gap-1 text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50 transition-colors ml-3"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        Revoke
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
