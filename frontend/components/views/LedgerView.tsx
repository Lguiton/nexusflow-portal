"use client";

import React, { useState } from "react";
import ETLDropzone from "../ETLDropzone";
import LedgerRowExplorer from "../LedgerRowExplorer";
import CategorySuggestionsWidget from "../CategorySuggestionsWidget";
import ExportActionBar from "../ExportActionBar";
import TelemetryScoutCard from "../TelemetryScoutCard";
import IngestionHistoryCard from "../IngestionHistoryCard";
import { useClientId } from "../ClientContext";

interface LedgerViewProps {
  refreshTrigger: number;
  onUploadSuccess: () => void;
  onApplied: () => void;
}

function toCsv(rows: any[]): string {
  if (rows.length === 0) return "date,category,amount,description,is_recurring,row_id\n";
  const header = ["date", "category", "amount", "description", "is_recurring", "row_id"];
  const escape = (v: any) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  // eslint-disable-next-line security/detect-object-injection -- h comes from the fixed local `header` array of known CSV column names, never external input
  const lines = rows.map((r) => header.map((h) => escape(r[h])).join(","));
  return [header.join(","), ...lines].join("\n");
}

export default function LedgerView({ refreshTrigger, onUploadSuccess, onApplied }: LedgerViewProps) {
  const [exporting, setExporting] = useState(false);
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;

  // Real export -- pulls this tenant's ledger rows via the same DIFF-01
  // drill-down endpoint LedgerRowExplorer uses (capped at 1000 rows, that
  // endpoint's own hard limit; a tenant with more than that will get a
  // truncated export today, not a silently wrong one -- worth a real
  // "export everything" backend job if that cap is ever hit in practice)
  // and converts it to CSV client-side, no fabricated data.
  const handleExportCsv = async () => {
    setExporting(true);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const res = await fetch(`${backendUrl}/api/v1/finance/ledger-rows`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ limit: 1000 }),
      });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const data = await res.json();
      const csv = toCsv(data.rows ?? []);
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ledger-export-${new Date().toISOString().split("T")[0]}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("CSV export failed:", err);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <ExportActionBar onExportCsv={handleExportCsv} csvLoading={exporting} />
      <ETLDropzone onUploadSuccess={onUploadSuccess} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LedgerRowExplorer refreshTrigger={refreshTrigger} />
        <CategorySuggestionsWidget refreshTrigger={refreshTrigger} onApplied={onApplied} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <IngestionHistoryCard refreshTrigger={refreshTrigger} onDataChanged={onUploadSuccess} />
        <TelemetryScoutCard />
      </div>
    </div>
  );
}
