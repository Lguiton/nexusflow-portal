'use client';

import React, { useState } from 'react';
import { Receipt, ShieldAlert, CheckCircle, ArrowRight } from 'lucide-react';

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

const MOCK_TRANSACTIONS = [
  { id: "tx_001", amount: 150.0, category: "Software Subscriptions" },
  { id: "tx_002", amount: 3200.0, category: "Marketing" },
  { id: "tx_003", amount: 45.0, category: "Office Supplies" },
  { id: "tx_004", amount: 850.0, category: "Travel" },
  { id: "tx_005", amount: 120.0, category: "Uncategorized" }
];

export default function ComptrollerWidget() {
  const [loading, setLoading] = useState<boolean>(false);
  const [report, setReport] = useState<AuditReport | null>(null);

  const runLedgerAudit = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://127.0.0.1:8000/api/v1/finance/comptroller-audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // THIS LINE WAS MISSING! We have to actually send the data to the AI.
        body: JSON.stringify({ transactions: MOCK_TRANSACTIONS }), 
      });

      if (res.ok) {
        const data = await res.json();
        setReport(data.audit_report);
      }
    } catch (err) {
      console.error("Comptroller Audit error:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-md text-slate-100 mt-6">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-lg font-bold flex items-center gap-2">
            <Receipt className="text-rose-400 w-5 h-5" />
            Comptroller Ledger Audit (Agent #12)
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Automated expense categorization and anomaly detection.
          </p>
        </div>
        <button
          onClick={runLedgerAudit}
          disabled={loading}
          className="px-4 py-2 bg-rose-600 hover:bg-rose-500 disabled:opacity-50 rounded-lg text-xs font-semibold text-white transition-colors flex items-center gap-2 cursor-pointer"
        >
          {loading ? "Auditing Ledger..." : "Run Expense Audit"}
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>

      {report ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-950 p-4 rounded-lg border border-slate-800">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs text-slate-500 uppercase font-semibold">Audit Summary</p>
                {report.flagged_count === 0 ? (
                  <CheckCircle className="w-4 h-4 text-emerald-500" />
                ) : (
                  <ShieldAlert className="w-4 h-4 text-amber-500" />
                )}
              </div>
              <p className="text-sm font-medium text-slate-300">
                Processed: <span className="text-white font-bold">{report.total_transactions_audited} txns</span>
              </p>
              <p className="text-sm font-medium text-slate-300">
                Anomalies Flagged: <span className={report.flagged_count > 0 ? "text-amber-400 font-bold" : "text-emerald-400 font-bold"}>
                  {report.flagged_count}
                </span>
              </p>
            </div>

            <div className="bg-slate-950 p-4 rounded-lg border border-slate-800">
              <p className="text-xs text-slate-500 uppercase font-semibold mb-2">Category Totals</p>
              <div className="space-y-1">
                {Object.entries(report.expense_breakdown_by_category).map(([cat, total]) => (
                  <div key={cat} className="flex justify-between text-xs font-mono">
                    <span className="text-slate-400">{cat}</span>
                    <span className="text-white">${total.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {report.flagged_items.length > 0 && (
            <div className="bg-amber-950/30 border border-amber-800/60 rounded-lg p-4">
              <p className="text-xs font-bold text-amber-400 uppercase mb-2 flex items-center gap-2">
                <ShieldAlert className="w-4 h-4" /> Require Executive Review
              </p>
              <ul className="space-y-2">
                {report.flagged_items.map((item, idx) => (
                  <li key={idx} className="text-sm bg-slate-950 p-2 rounded border border-slate-800 flex justify-between items-center">
                    <div>
                      <span className="font-mono text-xs text-slate-500 mr-2">{item.tx_id}</span>
                      <span className="text-slate-300">{item.reason}</span>
                    </div>
                    <span className="font-bold text-amber-400 font-mono">${item.amount}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="py-8 text-center border-2 border-dashed border-slate-800 rounded-lg">
          <p className="text-sm text-slate-500">Ready to audit incoming ledger batch.</p>
        </div>
      )}
    </div>
  );
}