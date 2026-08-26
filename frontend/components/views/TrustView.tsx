"use client";

import React from "react";
import KnownGapsPanel from "../KnownGapsPanel";
import AssumptionLedger from "../AssumptionLedger";
import BYOKSettingsCard from "../BYOKSettingsCard";

interface TrustViewProps {
  refreshTrigger: number;
}

export default function TrustView({ refreshTrigger }: TrustViewProps) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <KnownGapsPanel refreshTrigger={refreshTrigger} />
        <AssumptionLedger />
      </div>
      <BYOKSettingsCard />
    </div>
  );
}
