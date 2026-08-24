"use client";

import React from "react";
import AdvancedAnalyticsDashboard from "../AdvancedAnalyticsDashboard";
import VirtualCFOWidget from "../VirtualCFOWidget";
import ForecastCard from "../ForecastCard";
import DataVisualizationWidget from "../DataVisualizationWidget";
import DataEngineerWidget from "../DataEngineerWidget";

interface AnalyticsViewProps {
  refreshTrigger: number;
}

export default function AnalyticsView({ refreshTrigger }: AnalyticsViewProps) {
  return (
    <div className="space-y-6">
      <AdvancedAnalyticsDashboard refreshTrigger={refreshTrigger} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <VirtualCFOWidget refreshTrigger={refreshTrigger} />
        <ForecastCard refreshTrigger={refreshTrigger} />
      </div>
      <DataVisualizationWidget refreshTrigger={refreshTrigger} />
      <DataEngineerWidget refreshTrigger={refreshTrigger} />
    </div>
  );
}
