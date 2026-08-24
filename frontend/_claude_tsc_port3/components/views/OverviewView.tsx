"use client";

import React from "react";
import SystemHealthStrip from "../SystemHealthStrip";
import type { HealthData } from "../SystemHealthStrip";
import OnboardingChecklist from "../OnboardingChecklist";
import KpiGrid from "../KpiGrid";
import KnownGapsPanel from "../KnownGapsPanel";
import ETLDropzone from "../ETLDropzone";

interface OverviewViewProps {
  health: HealthData | null;
  healthLoading: boolean;
  refreshTrigger: number;
  onUploadSuccess: () => void;
}

export default function OverviewView({ health, healthLoading, refreshTrigger, onUploadSuccess }: OverviewViewProps) {
  return (
    <div className="space-y-6">
      <SystemHealthStrip health={health} loading={healthLoading} />
      <OnboardingChecklist refreshTrigger={refreshTrigger} />
      <KpiGrid refreshTrigger={refreshTrigger} />
      <KnownGapsPanel refreshTrigger={refreshTrigger} />
      <ETLDropzone onUploadSuccess={onUploadSuccess} />
    </div>
  );
}
