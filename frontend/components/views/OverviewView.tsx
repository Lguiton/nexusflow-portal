"use client";

import React, { useState } from "react";
import { ShieldCheck } from "lucide-react";
import SystemHealthStrip from "../SystemHealthStrip";
import type { HealthData } from "../SystemHealthStrip";
import OnboardingChecklist from "../OnboardingChecklist";
import KpiGrid from "../KpiGrid";
import KnownGapsPanel from "../KnownGapsPanel";
import ETLDropzone from "../ETLDropzone";
import InteractiveAuditModal from "../InteractiveAuditModal";

interface OverviewViewProps {
  health: HealthData | null;
  healthLoading: boolean;
  refreshTrigger: number;
  onUploadSuccess: () => void;
}

export default function OverviewView({ health, healthLoading, refreshTrigger, onUploadSuccess }: OverviewViewProps) {
  const [auditOpen, setAuditOpen] = useState(false);

  return (
    <div className="space-y-6">
      <SystemHealthStrip health={health} loading={healthLoading} />
      <OnboardingChecklist refreshTrigger={refreshTrigger} />
      <KpiGrid refreshTrigger={refreshTrigger} />
      <KnownGapsPanel refreshTrigger={refreshTrigger} />

      <div className="flex justify-end">
        <button
          onClick={() => setAuditOpen(true)}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs font-medium text-slate-300 hover:text-indigo-300 hover:border-indigo-500/40 transition-all"
        >
          <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
          Run Ledger Audit
        </button>
      </div>
      <InteractiveAuditModal isOpen={auditOpen} onClose={() => setAuditOpen(false)} />

      <ETLDropzone onUploadSuccess={onUploadSuccess} />
    </div>
  );
}
