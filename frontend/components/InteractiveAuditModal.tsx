"use client";

import React, { useState } from "react";
import { ShieldAlert, CheckCircle2, Loader2, X, Play, AlertTriangle } from "lucide-react";
import { useClientId } from "./ClientContext";

interface FlaggedItem {
  tx_id: string;
  amount: number;
  category: string;
  reason: string;
}

interface AuditReport {
  total_transactions_audited: number;
  flagged_count: number;
  expense_breakdown_by_category: Record<string, number>;
  flagged_items: FlaggedItem[];
  audit_status: string;
}

interface InteractiveAuditModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function InteractiveAuditModal({ isOpen, onClose }: InteractiveAuditModalProps) {
  const [auditing, setAuditing] = useState(false);
  const [auditComplete, setAuditComplete] = useState(false);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  let currentClientId = "default_client";
  let authToken: string | null = null;
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) currentClientId = clientCtx.clientId;
    authToken = clientCtx?.authToken ?? null;
  } catch (e) {}

  if (!isOpen) return null;

  const runAudit = async () => {
    setAuditing(true);
    setAuditComplete(false);
    setErrorMsg(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const res = await fetch(`${backendUrl}/api/v1/finance/comptroller-audit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-client-id": currentClientId,
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
      });
      if (!res.ok) throw new Error(`Server status: ${res.status}`);
      const data: AuditReport = await res.json();
      setReport(data);
    } catch (err) {
      setErrorMsg("Could not reach the ledger audit service. Try again in a moment.");
      setReport(null);
    } finally {
      setAuditing(false);
      setAuditComplete(true);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden text-slate-100 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-sm">Comptroller Ledger Audit</h3>
              <p className="text-[10px] text-slate-400 font-mono">Agent #09 Operational Environment Shield</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg bg-slate-800/50 hover:bg-slate-800 text-slate-400 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          <p className="text-xs text-slate-300">
            Pull this tenant's real ledger, total expenses by category, and flag any transaction whose amount is a statistical outlier within its category (z-score based).
          </p>

          {!auditComplete && !auditing && (
            <button
              onClick={runAudit}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs shadow-lg shadow-indigo-600/20 transition-all"
            >
              <Play className="w-4 h-4 fill-current" />
              <span>Run Expense Audit Now</span>
            </button>
          )}

          {auditing && (
            <div className="py-12 flex flex-col items-center justify-center gap-3 text-slate-400 font-mono text-xs">
              <Loader2 className="w-6 h-6 text-indigo-400 animate-spin" />
              <span>Scrubbing ledger and scoring anomalies...</span>
            </div>
          )}

          {auditComplete && errorMsg && (
            <div className="py-8 flex flex-col items-center justify-center gap-3 text-rose-400 text-xs">
              <AlertTriangle className="w-6 h-6" />
              <span>{errorMsg}</span>
              <button
                onClick={runAudit}
                className="mt-1 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium text-xs transition-all"
              >
                Retry
              </button>
            </div>
          )}

          {auditComplete && report && (
            <div className="space-y-3">
              <div className="bg-slate-950 border border-slate-800 p-3.5 rounded-xl space-y-1 font-mono text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-200">Audit Summary</span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] border ${
                      report.flagged_count === 0
                        ? "bg-emerald-950 text-emerald-300 border-emerald-800"
                        : "bg-amber-950 text-amber-300 border-amber-800"
                    }`}
                  >
                    {report.audit_status}
                  </span>
                </div>
                <p className="text-slate-400">
                  {report.total_transactions_audited} transactions audited &middot; {report.flagged_count} flagged
                </p>
              </div>

              {Object.keys(report.expense_breakdown_by_category).length > 0 && (
                <div className="bg-slate-950 border border-slate-800 p-3.5 rounded-xl space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Category Totals</p>
                  {Object.entries(report.expense_breakdown_by_category).map(([cat, total]) => (
                    <div key={cat} className="flex justify-between text-xs font-mono">
                      <span className="text-slate-400">{cat}</span>
                      <span className="text-white">${Number(total).toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              )}

              {report.flagged_items.length > 0 && (
                <div className="bg-amber-950/30 border border-amber-800/60 rounded-xl p-3.5 space-y-2">
                  <p className="text-[10px] font-bold text-amber-400 uppercase flex items-center gap-2">
                    <ShieldAlert className="w-3.5 h-3.5" /> Flagged for Review
                  </p>
                  {report.flagged_items.map((item, i) => (
                    <div key={i} className="bg-slate-950 border border-slate-800 p-2.5 rounded-lg text-xs">
                      <div className="flex justify-between items-center">
                        <span className="text-slate-300">{item.category}</span>
                        <span className="font-bold text-amber-400 font-mono">${item.amount.toLocaleString()}</span>
                      </div>
                      <p className="text-slate-500 text-[11px] mt-0.5">{item.reason}</p>
                    </div>
                  ))}
                </div>
              )}

              {report.total_transactions_audited === 0 && (
                <div className="flex items-center gap-2 text-slate-500 text-xs py-2">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>No ledger data yet — upload a CSV ledger first to run a real audit.</span>
                </div>
              )}

              <button
                onClick={runAudit}
                className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium text-xs transition-all mt-2"
              >
                Re-Run Audit
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-slate-950 border-t border-slate-800 flex justify-end">
          <button onClick={onClose} className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 transition-colors">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
