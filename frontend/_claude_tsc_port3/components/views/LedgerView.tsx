"use client";

import React from "react";
import ETLDropzone from "../ETLDropzone";
import LedgerRowExplorer from "../LedgerRowExplorer";
import CategorySuggestionsWidget from "../CategorySuggestionsWidget";

interface LedgerViewProps {
  refreshTrigger: number;
  onUploadSuccess: () => void;
  onApplied: () => void;
}

export default function LedgerView({ refreshTrigger, onUploadSuccess, onApplied }: LedgerViewProps) {
  return (
    <div className="space-y-6">
      <ETLDropzone onUploadSuccess={onUploadSuccess} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LedgerRowExplorer refreshTrigger={refreshTrigger} />
        <CategorySuggestionsWidget refreshTrigger={refreshTrigger} onApplied={onApplied} />
      </div>
    </div>
  );
}
