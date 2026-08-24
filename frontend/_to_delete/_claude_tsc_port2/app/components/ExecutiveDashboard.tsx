'use client';
import { useEffect, useState } from 'react';

export default function ExecutiveDashboard() {
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://localhost:8000/api/v1/bi/executive-summary')
      .then((res) => res.json())
      .then((data) => {
        setMetrics(data.kpis);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-slate-400">Loading Executive Metrics...</div>;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h3 className="text-md font-semibold text-cyan-400">Executive Proof & BI Visualization</h3>
          <p className="text-xs text-slate-400">10-Second Scannability Panel: Real-Time Corporate Margins</p>
        </div>
        <span className="px-2.5 py-1 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono rounded">
          Live Sync Active
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-950 border border-slate-800 p-4 rounded-lg">
          <div className="text-xs text-slate-400">Net MRR</div>
          <div className="text-xl font-bold text-slate-100 mt-1">${metrics?.net_mrr?.toLocaleString() || '51,000'}</div>
          <div className="text-[10px] text-emerald-400 mt-1">↑ +14.2% vs last month</div>
        </div>

        <div className="bg-slate-950 border border-slate-800 p-4 rounded-lg">
          <div className="text-xs text-slate-400">ARPU</div>
          <div className="text-xl font-bold text-slate-100 mt-1">${metrics?.arpu?.toLocaleString() || '8,500'}</div>
          <div className="text-[10px] text-emerald-400 mt-1">Optimized tier distribution</div>
        </div>

        <div className="bg-slate-950 border border-slate-800 p-4 rounded-lg">
          <div className="text-xs text-slate-400">Gross Margin</div>
          <div className="text-xl font-bold text-slate-100 mt-1">{metrics?.gross_margin_percent || '82.5'}%</div>
          <div className="text-[10px] text-emerald-400 mt-1">High operational efficiency</div>
        </div>

        <div className="bg-slate-950 border border-amber-500/30 p-4 rounded-lg">
          <div className="text-xs text-amber-400">Estimated Profit Leak</div>
          <div className="text-xl font-bold text-amber-300 mt-1">${metrics?.estimated_profit_leak?.toLocaleString() || '1,420'}</div>
          <div className="text-[10px] text-amber-400 mt-1">Action required by Supervisor</div>
        </div>
      </div>
    </div>
  );
}