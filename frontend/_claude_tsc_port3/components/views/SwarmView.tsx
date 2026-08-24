"use client";

import React from "react";
import CognitiveSearchBar from "../CognitiveSearchBar";
import SwarmLogStreamer from "../SwarmLogStreamer";
import { SwarmVisualizer } from "../SwarmVisualizer";
import AgentDirectory from "../AgentDirectory";

interface SearchResult {
  query: string;
  synthesized_insight: string;
  agent_breakdown: Array<{
    agent_name: string;
    domain: string;
    output_summary: string;
    raw_artifacts?: unknown;
  }>;
  confidence_score: number;
  status: string;
}

interface SwarmViewProps {
  searchResult: SearchResult | null;
  onQueryResult: (data: SearchResult) => void;
}

export default function SwarmView({ searchResult, onQueryResult }: SwarmViewProps) {
  return (
    <div className="space-y-6">
      <CognitiveSearchBar onQueryResult={onQueryResult} />
      <SwarmLogStreamer sessionId="active_dashboard_session" />
      {searchResult && (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
          <SwarmVisualizer data={searchResult} />
        </div>
      )}
      <AgentDirectory />
    </div>
  );
}
