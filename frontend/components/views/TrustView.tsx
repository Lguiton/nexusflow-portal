"use client";

import React from "react";
import KnownGapsPanel from "../KnownGapsPanel";
import AssumptionLedger from "../AssumptionLedger";
import BYOKSettingsCard from "../BYOKSettingsCard";
import KnowledgeBaseCard from "../KnowledgeBaseCard";
import FinOpsBudgetCard from "../FinOpsBudgetCard";
import AuditLineageCard from "../AuditLineageCard";

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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <BYOKSettingsCard />
        <KnowledgeBaseCard />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <FinOpsBudgetCard />
        <AuditLineageCard />
      </div>
    </div>
  );
}
