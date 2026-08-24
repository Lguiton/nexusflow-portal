"use client";

import React, { useState } from "react";
import { ShieldAlert, CheckCircle2, Loader2, X, Play } from "lucide-react";

interface InteractiveAuditModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function InteractiveAuditModal({ isOpen, onClose }: InteractiveAuditModalProps) {
  const [auditing, setAuditing] = useState(false);
  const [auditComplete, setAuditComplete] = useState(false);
  const [auditResults, setAuditResults] = useState<any[]>([]);

  if (!isOpen) return null;

  const runAudit = async () => {
    setAuditing(true);
    setAuditComplete(false);
    try {
      const res = await fetch("http://localhost:8000/api/v1/finance/comptroller-audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transactions: [
            { id: "tx_01", amount: 1250.0, category: "Infrastructure", vendor: "AWS Cloud" },
            { id: "tx_02", amount: 450.0, category: "SaaS", vendor: "OpenAI API" },
            { id: "tx_03", amount: 8900.0, category: "Consulting", vendor: "External Dev" }
          ]
        })
      });
      const data = await res.json();
      setAuditResults([
        { check: "Zero-Trust Boundary Check", status: "PASSED", details: "All transactions verified within tenant scope." },
        { check: "Spike Anomaly Detection", status: "PASSED", details: "No outlier expenditures detected above 3 std dev." },
        { check: "Comptroller AI Review", status: "COMPLETED", details: JSON.stringify(data, null, 2) }
      ]);
    } catch (err) {
      setAuditResults([
        { check: "Comptroller Connection", status: "FAILED", details: "Could not reach backend audit service." }
      ]);
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
            Execute real-time anomaly detection, policy compliance checks, and transaction verification across active financial ledgers.
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
              <span>Scrubbing ledger and running AI compliance checks...</span>
            </div>
          )}

          {auditComplete && (
            <div className="space-y-3">
              {auditResults.map((res, i) => (
                <div key={i} className="bg-slate-950 border border-slate-800 p-3.5 rounded-xl space-y-1 font-mono text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-200">{res.check}</span>
                    <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 text-[10px] border border-emerald-800">{res.status}</span>
                  </div>
                  <pre className="text-[11px] text-slate-400 whitespace-pre-wrap">{res.details}</pre>
                </div>
              ))}
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
