"use client";

import React, { useEffect, useState } from "react";
import { KeyRound, Loader2, CheckCircle2, Trash2, AlertCircle, Eye, EyeOff } from "lucide-react";
import { useClientId } from "./ClientContext";

// BYOK-01: lets an owner/admin supply their own OpenAI API key instead of
// sharing the platform's. The key itself is only ever POSTed once and
// never returned by the backend afterward -- this component only ever
// knows whether a key is configured (byok_configured), never its value.
export default function BYOKSettingsCard() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;
  const role: string | undefined = clientCtx?.user?.role;

  const [configured, setConfigured] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(true);
  const [keyInput, setKeyInput] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  const canManage = role === "owner" || role === "admin";

  useEffect(() => {
    if (!authReady) return;
    (async () => {
      setChecking(true);
      try {
        const res = await fetch(`${backendUrl}/api/v1/settings/byok`, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        });
        if (res.ok) {
          const data = await res.json();
          setConfigured(!!data.byok_configured);
        }
      } catch (err) {
        console.error("BYOK status check failed:", err);
      } finally {
        setChecking(false);
      }
    })();
  }, [authReady, authToken, backendUrl]);

  const handleSave = async () => {
    if (!keyInput.trim()) return;
    setSaving(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/settings/byok`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ openai_api_key: keyInput.trim() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      setConfigured(true);
      setKeyInput("");
      setSuccessMsg("Your API key is saved and encrypted.");
    } catch (err: any) {
      setError(err.message || "Could not save your API key.");
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async () => {
    setSaving(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/settings/byok`, {
        method: "DELETE",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) throw new Error(`Server status: ${res.status}`);
      setConfigured(false);
      setSuccessMsg("Your API key was removed -- agents will use the platform key again.");
    } catch (err: any) {
      setError(err.message || "Could not remove your API key.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-lg">
          <KeyRound className="w-5 h-5 text-indigo-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Bring Your Own Key</h2>
          <p className="text-xs text-slate-400">Route agent calls through your own OpenAI API key instead of the platform's.</p>
        </div>
      </div>

      <div className="p-6">
        {!canManage ? (
          <p className="text-sm text-slate-500 italic">Only an owner or admin can manage this tenant's API key.</p>
        ) : checking ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
            <Loader2 className="w-4 h-4 animate-spin" />
            Checking status...
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm">
              {configured ? (
                <>
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span className="text-slate-300">A key is configured for this tenant.</span>
                </>
              ) : (
                <>
                  <AlertCircle className="w-4 h-4 text-slate-500" />
                  <span className="text-slate-500">No key configured -- using the platform's shared key.</span>
                </>
              )}
            </div>

            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={showKey ? "text" : "password"}
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  placeholder="sk-..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg py-2 pl-3 pr-10 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((s) => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  aria-label={showKey ? "Hide key" : "Show key"}
                >
                  {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <button
                onClick={handleSave}
                disabled={saving || !keyInput.trim()}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors"
              >
                {saving ? "Saving..." : configured ? "Replace Key" : "Save Key"}
              </button>
            </div>

            {configured && (
              <button
                onClick={handleRemove}
                disabled={saving}
                className="flex items-center gap-1.5 text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Remove key
              </button>
            )}

            {error && <p className="text-xs text-rose-400">{error}</p>}
            {successMsg && <p className="text-xs text-emerald-400">{successMsg}</p>}

            <p className="text-[11px] text-slate-600 leading-relaxed">
              Your key is encrypted at rest and never displayed again after saving. Agent calls fall back to the platform's key automatically if yours is removed or fails.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
