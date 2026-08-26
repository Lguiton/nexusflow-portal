"use client";

import React, { useEffect, useState } from "react";
import { Gauge, Loader2, AlertCircle, ShieldAlert, Trash2 } from "lucide-react";
import { useClientId } from "./ClientContext";

// FINOPS-01: real billing-overrun protection, not just monitoring. Reads
// db_manager.check_budget_gate's real numbers (this tenant's actual
// ai_usage-derived spend this calendar month vs. an optional cap) and lets
// an owner/admin set or clear that cap. No cap set -> unrestricted, same
// as every tenant's default -- this card never implies a cap exists until
// one has actually been saved.
interface BudgetStatus {
  allowed: boolean;
  cap_usd: number | null;
  usage_usd: number;
  usage_tokens: number;
  call_count: number;
  priced_call_count: number;
  pct_used: number | null;
}

export default function FinOpsBudgetCard() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;
  const role: string | undefined = clientCtx?.user?.role;

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  const canManage = role === "owner" || role === "admin";

  const [status, setStatus] = useState<BudgetStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [capInput, setCapInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = authToken ? { Authorization: `Bearer ${authToken}` } : {};

  const fetchStatus = async () => {
    if (!authReady) return;
    setLoading(true);
    try {
      const res = await fetch(`${backendUrl}/api/v1/settings/budget`, { headers: authHeaders });
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (err) {
      console.error("Budget status check failed:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, authToken, backendUrl]);

  const handleSaveCap = async () => {
    const parsed = parseFloat(capInput);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setError("Enter a cap greater than $0.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/settings/budget`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ monthly_cap_usd: parsed }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      const data = await res.json();
      setStatus(data);
      setCapInput("");
    } catch (err: any) {
      setError(err.message || "Could not save your budget cap.");
    } finally {
      setSaving(false);
    }
  };

  const handleClearCap = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/settings/budget`, { method: "DELETE", headers: authHeaders });
      if (!res.ok) throw new Error(`Server status: ${res.status}`);
      const data = await res.json();
      setStatus(data);
    } catch (err: any) {
      setError(err.message || "Could not remove your budget cap.");
    } finally {
      setSaving(false);
    }
  };

  const pct = status?.pct_used ?? 0;
  const barColor = pct >= 100 ? "bg-rose-500" : pct >= 80 ? "bg-amber-500" : "bg-emerald-500";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <Gauge className="w-5 h-5 text-amber-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">AI Usage Budget</h2>
          <p className="text-xs text-slate-400">Real monthly spend, computed from every actual LLM call this tenant has made.</p>
        </div>
      </div>

      <div className="p-6 space-y-4">
        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading usage...
          </div>
        ) : !status ? (
          <p className="text-xs text-rose-400">Could not load budget status.</p>
        ) : (
          <>
            <div>
              <div className="flex items-baseline justify-between mb-1.5">
                <span className="text-2xl font-bold text-white">${status.usage_usd.toFixed(2)}</span>
                <span className="text-xs text-slate-500">
                  {status.cap_usd !== null ? `of $${status.cap_usd.toFixed(2)} this month` : "no cap set -- unrestricted"}
                </span>
              </div>
              {status.cap_usd !== null && (
                <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${barColor} transition-all`}
                    style={{ width: `${Math.min(100, pct)}%` }}
                  />
                </div>
              )}
              <p className="text-[11px] text-slate-600 mt-2">
                {status.call_count} AI call{status.call_count === 1 ? "" : "s"} this month
                {status.priced_call_count < status.call_count && (
                  <> ({status.call_count - status.priced_call_count} against a model without a known price -- token count only, not included above)</>
                )}
                , {status.usage_tokens.toLocaleString()} total tokens.
              </p>
            </div>

            {!status.allowed && (
              <div className="flex items-start gap-2 bg-rose-500/10 border border-rose-500/30 rounded-lg p-3 text-xs text-rose-300">
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                <span>Cap reached -- new AI-calling requests are being blocked until this raises, resets next month, or the cap is removed.</span>
              </div>
            )}

            {!canManage ? (
              <p className="text-xs text-slate-500 italic">Only an owner or admin can change this tenant's budget cap.</p>
            ) : (
              <div className="border-t border-slate-800 pt-4 space-y-2">
                <div className="flex gap-2">
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={capInput}
                    onChange={(e) => setCapInput(e.target.value)}
                    placeholder="Monthly cap in USD, e.g. 50"
                    className="flex-1 bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-amber-500 transition-colors"
                  />
                  <button
                    onClick={handleSaveCap}
                    disabled={saving || !capInput.trim()}
                    className="bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors"
                  >
                    {saving ? "Saving..." : status.cap_usd !== null ? "Update Cap" : "Set Cap"}
                  </button>
                </div>
                {status.cap_usd !== null && (
                  <button
                    onClick={handleClearCap}
                    disabled={saving}
                    className="flex items-center gap-1.5 text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50 transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    Remove cap (go unrestricted)
                  </button>
                )}
                {error && (
                  <p className="text-xs text-rose-400 flex items-center gap-1.5">
                    <AlertCircle className="w-3.5 h-3.5" /> {error}
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
