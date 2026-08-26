"use client";

import React from "react";
import AdvancedAnalyticsDashboard from "../AdvancedAnalyticsDashboard";
import VirtualCFOWidget from "../VirtualCFOWidget";
import ForecastCard from "../ForecastCard";
import DataVisualizationWidget from "../DataVisualizationWidget";
import TransactionScatterPanel from "../TransactionScatterPanel";
import DataEngineerWidget from "../DataEngineerWidget";

interface AnalyticsViewProps {
  refreshTrigger: number;
  onNavigateToLedger?: () => void;
}

export default function AnalyticsView({ refreshTrigger, onNavigateToLedger }: AnalyticsViewProps) {
  return (
    <div className="space-y-6">
      <AdvancedAnalyticsDashboard refreshTrigger={refreshTrigger} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <VirtualCFOWidget refreshTrigger={refreshTrigger} onNavigateToLedger={onNavigateToLedger} />
        <ForecastCard refreshTrigger={refreshTrigger} />
      </div>
      <DataVisualizationWidget refreshTrigger={refreshTrigger} />
      <TransactionScatterPanel refreshTrigger={refreshTrigger} />
      <DataEngineerWidget refreshTrigger={refreshTrigger} />
    </div>
  );
}
