"use client";

import React, { useState } from "react";
import { Download, FileSpreadsheet, Share2, Check, Loader2 } from "lucide-react";

interface ExportActionBarProps {
  onExportPdf?: () => void;
  onExportCsv?: () => void;
  csvLoading?: boolean;
}

export default function ExportActionBar({ onExportPdf, onExportCsv, csvLoading }: ExportActionBarProps) {
  const [copied, setCopied] = useState(false);

  const handleShareLink = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <div className="flex flex-wrap items-center gap-2 bg-slate-900 border border-slate-800 p-2 rounded-xl shadow-md">
      <button
        onClick={onExportPdf}
        disabled={!onExportPdf}
        title={!onExportPdf ? "Executive PDF export isn't built yet -- coming soon" : undefined}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs font-medium text-slate-200 hover:text-indigo-300 hover:border-indigo-500/40 transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-slate-200 disabled:hover:border-slate-800"
      >
        <Download className="w-3.5 h-3.5 text-indigo-400" />
        <span>Download Executive PDF{!onExportPdf ? " (Coming Soon)" : ""}</span>
      </button>

      <button
        onClick={onExportCsv}
        disabled={!onExportCsv || csvLoading}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs font-medium text-slate-200 hover:text-indigo-300 hover:border-indigo-500/40 transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {csvLoading ? (
          <Loader2 className="w-3.5 h-3.5 text-emerald-400 animate-spin" />
        ) : (
          <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400" />
        )}
        <span>{csvLoading ? "Exporting..." : "Export CSV Ledger"}</span>
      </button>

      <button
        onClick={handleShareLink}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs font-medium text-slate-200 hover:text-indigo-300 hover:border-indigo-500/40 transition-all shadow-sm ml-auto"
      >
        {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Share2 className="w-3.5 h-3.5 text-indigo-400" />}
        <span>{copied ? "Link Copied!" : "Secure Share Link"}</span>
      </button>
    </div>
  );
}
