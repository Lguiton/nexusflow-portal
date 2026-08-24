"use client";

import React, { useState } from "react";
import { Download, FileSpreadsheet, Share2, Check } from "lucide-react";

interface ExportActionBarProps {
  onExportPdf?: () => void;
  onExportCsv?: () => void;
}

export default function ExportActionBar({ onExportPdf, onExportCsv }: ExportActionBarProps) {
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
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs font-medium text-slate-200 hover:text-indigo-300 hover:border-indigo-500/40 transition-all shadow-sm"
      >
        <Download className="w-3.5 h-3.5 text-indigo-400" />
        <span>Download Executive PDF</span>
      </button>

      <button
        onClick={onExportCsv}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs font-medium text-slate-200 hover:text-indigo-300 hover:border-indigo-500/40 transition-all shadow-sm"
      >
        <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400" />
        <span>Export CSV Ledger</span>
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
