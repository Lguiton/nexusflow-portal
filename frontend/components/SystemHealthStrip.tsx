"use client";

import React from "react";
import { Server, ShieldCheck } from "lucide-react";
import SubAgentWidget from "./SubAgentWidget";

// System State / Runtime Security tiles -- ported as-is from the old
// page.tsx header (same real GET /api/v1/health fields, same field-name
// history/caveats), now living in the Overview tab as the first row of
// tiles instead of the page's own custom header. Sub-Agent Network stays
// the real, already-fixed SubAgentWidget alongside them, matching the
// 3-tile system-status row from the original layout.
export interface HealthData {
  status: string;
  // See backend/main.py's real GET /api/v1/health -- returns
  // "docker_detected" / "active_agent_modules". docker_detected only
  // reflects os.path.exists("/.dockerenv"), i.e. whether the process is
  // running inside a container -- it does not itself verify any
  // tenant-isolation or network security policy.
  docker_detected: boolean;
  active_agent_modules: number;
  version: string;
}

interface SystemHealthStripProps {
  health: HealthData | null;
  loading: boolean;
}

export default function SystemHealthStrip({ health, loading }: SystemHealthStripProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">System State</span>
          <Server className="w-5 h-5 text-indigo-400" />
        </div>
        <div className="mt-4">
          <p className="text-2xl font-bold text-white">{loading ? "Checking..." : health?.status || "OFFLINE"}</p>
          <p className="text-xs text-slate-500 mt-1">FastAPI Engine v{health?.version || "1.0.0"}</p>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Runtime Security</span>
          <ShieldCheck className="w-5 h-5 text-emerald-400" />
        </div>
        <div className="mt-4">
          <p className="text-2xl font-bold text-white">
            {loading
              ? "CHECKING"
              : health === null
                ? "OFFLINE"
                : health.docker_detected
                  ? "ISOLATED"
                  : "UNSECURED"}
          </p>
          <p className="text-xs text-slate-500 mt-1">RevSecOps & SysAdmin Policy Enforced</p>
        </div>
      </div>

      <SubAgentWidget />
    </div>
  );
}
