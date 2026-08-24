'use client';
import { useEffect, useState } from 'react';

export default function MRRTrendChart() {
  const [trendData, setTrendData] = useState<any[]>([]);
  const [chartType, setChartType] = useState<string>('bar');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://localhost:8000/api/v1/analytics/mrr-trend')
      .then((res) => res.json())
      .then((data) => {
        setTrendData(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-slate-400 p-4">Loading Analytics Visualization...</div>;

  const maxMrr = Math.max(...trendData.map(d => d.mrr), 60000);
  const totalMrrSum = trendData.reduce((acc, curr) => acc + curr.mrr, 0);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h3 className="text-md font-semibold text-cyan-400">Advanced Business Intelligence Visualizer</h3>
          <p className="text-xs text-slate-400">Dynamic telemetry projections across active financial pipelines</p>
        </div>

        {/* Chart Type Dropdown Selector */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 font-mono">View:</span>
          <select
            value={chartType}
            onChange={(e) => setChartType(e.target.value)}
            className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-cyan-500 font-mono"
          >
            <option value="bar">Monthly Bar Chart</option>
            <option value="pie">Revenue Proportion Pie</option>
            <option value="line">Growth Trend Line</option>
            <option value="area">Gradient Area Chart</option>
            <option value="scatter">Dispersion Scatter Plot</option>
            <option value="histogram">Cohort Histogram</option>
            <option value="targets">Cohort Target Progress</option>
          </select>
        </div>
      </div>

      {/* Visualization Container */}
      <div className="h-56 bg-slate-950 rounded-lg border border-slate-800 p-4 flex flex-col justify-end">
        
        {/* 1. Bar Chart View */}
        {chartType === 'bar' && (
          <div className="h-full flex flex-col justify-between pt-2">
            <div className="text-xs text-slate-400 font-mono mb-1">Monthly Recurring Revenue Distribution ($)</div>
            <div className="h-40 flex items-end gap-3 pb-2 px-2 border-b border-slate-800">
              {trendData.map((item, index) => {
                const heightPercent = (item.mrr / maxMrr) * 100;
                return (
                  <div key={index} className="flex-1 flex flex-col items-center gap-2 h-full justify-end group relative">
                    <div className="absolute -top-8 bg-slate-800 text-cyan-300 text-[10px] font-mono py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap border border-slate-700 pointer-events-none z-20">
                      {item.month}: ${item.mrr.toLocaleString()}
                    </div>
                    <div 
                      style={{ height: `${heightPercent}%` }} 
                      className="w-full bg-cyan-500/30 hover:bg-cyan-400 border-t-2 border-cyan-400 rounded-t transition-all"
                    />
                  </div>
                );
              })}
            </div>
            <div className="flex justify-between px-2 text-[10px] text-slate-400 font-mono pt-1">
              {trendData.map((d, i) => <span key={i}>{d.month}</span>)}
            </div>
          </div>
        )}

        {/* 2. Revenue Proportion Pie/Donut View */}
        {chartType === 'pie' && (
          <div className="h-full flex flex-col justify-center space-y-3 px-4">
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-400 font-mono">Cohort Share Proportions (Total: ${totalMrrSum.toLocaleString()})</span>
            </div>
            <div className="w-full h-8 bg-slate-900 rounded-lg overflow-hidden flex border border-slate-700 p-1 gap-1">
              {trendData.map((item, i) => {
                const sharePercent = Math.round((item.mrr / totalMrrSum) * 100);
                const colors = [
                  'bg-cyan-500', 'bg-teal-500', 'bg-emerald-500', 
                  'bg-amber-500', 'bg-orange-500', 'bg-rose-500', 'bg-indigo-500'
                ];
                return (
                  <div 
                    key={i} 
                    style={{ width: `${sharePercent}%` }} 
                    className={`${colors[i % colors.length]} h-full rounded hover:opacity-80 transition-opacity flex items-center justify-center text-[10px] font-bold text-slate-950`}
                    title={`${item.month}: $${item.mrr.toLocaleString()} (${sharePercent}%)`}
                  >
                    {sharePercent}%
                  </div>
                );
              })}
            </div>
            <div className="grid grid-cols-4 gap-2 pt-2 text-[10px] text-slate-400 font-mono">
              {trendData.map((d, i) => (
                <div key={i} className="flex items-center gap-1 truncate">
                  <span className="w-2 h-2 rounded-full bg-cyan-400 inline-block shrink-0"/>
                  <span className="truncate">{d.month}: ${d.mrr.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 3. Growth Line View */}
        {chartType === 'line' && (
          <div className="h-full flex flex-col justify-between pt-4">
            <div className="relative h-36 border-l border-b border-slate-800 flex items-end px-2">
              <svg className="absolute inset-0 w-full h-full overflow-visible p-2">
                <polyline
                  fill="none"
                  stroke="#22d3ee"
                  strokeWidth="2.5"
                  points={trendData.map((item, i) => {
                    const x = (i / (trendData.length - 1)) * 380;
                    const y = 140 - (item.mrr / maxMrr) * 120;
                    return `${x},${y}`;
                  }).join(' ')}
                />
              </svg>
              {trendData.map((item, index) => (
                <div key={index} className="flex-1 flex flex-col items-center relative group">
                  <div className="w-2 h-2 rounded-full bg-cyan-400 ring-4 ring-cyan-950 z-10 mb-[-4px]" />
                  <div className="absolute -top-8 bg-slate-800 text-cyan-300 text-[10px] font-mono py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap border border-slate-700 pointer-events-none">
                    {item.month}: ${item.mrr.toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex justify-between px-2 text-[10px] text-slate-400 font-mono">
              {trendData.map((d, i) => <span key={i}>{d.month}</span>)}
            </div>
          </div>
        )}

        {/* 4. Gradient Area Chart View */}
        {chartType === 'area' && (
          <div className="h-full flex flex-col justify-between pt-4">
            <div className="relative h-36 border-l border-b border-slate-800 flex items-end px-2">
              <svg className="absolute inset-0 w-full h-full overflow-visible p-2">
                <defs>
                  <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.0" />
                  </linearGradient>
                </defs>
                <polygon
                  fill="url(#areaGradient)"
                  points={`0,140 ${trendData.map((item, i) => {
                    const x = (i / (trendData.length - 1)) * 380;
                    const y = 140 - (item.mrr / maxMrr) * 120;
                    return `${x},${y}`;
                  }).join(' ')} 380,140`}
                />
                <polyline
                  fill="none"
                  stroke="#22d3ee"
                  strokeWidth="2"
                  points={trendData.map((item, i) => {
                    const x = (i / (trendData.length - 1)) * 380;
                    const y = 140 - (item.mrr / maxMrr) * 120;
                    return `${x},${y}`;
                  }).join(' ')}
                />
              </svg>
            </div>
            <div className="flex justify-between px-2 text-[10px] text-slate-400 font-mono">
              {trendData.map((d, i) => <span key={i}>{d.month}</span>)}
            </div>
          </div>
        )}

        {/* 5. Dispersion Scatter Plot View */}
        {chartType === 'scatter' && (
          <div className="h-full flex flex-col justify-between pt-4 relative">
            <div className="relative h-36 border-l border-b border-slate-800 flex items-center px-2">
              {trendData.map((item, index) => {
                const topPercent = 100 - (item.mrr / maxMrr) * 85;
                return (
                  <div key={index} className="flex-1 flex justify-center relative group">
                    <div 
                      style={{ top: `${topPercent}%` }}
                      className="absolute w-3 h-3 rounded-full bg-emerald-400 border border-slate-950 shadow-lg shadow-emerald-500/50 cursor-pointer hover:scale-125 transition-transform"
                    />
                    <div className="absolute -top-6 bg-slate-800 text-emerald-300 text-[10px] font-mono py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap border border-slate-700 pointer-events-none z-20">
                      {item.month}: ${item.mrr.toLocaleString()}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex justify-between px-2 text-[10px] text-slate-400 font-mono">
              {trendData.map((d, i) => <span key={i}>{d.month}</span>)}
            </div>
          </div>
        )}

        {/* 6. Cohort Histogram View */}
        {chartType === 'histogram' && (
          <div className="h-full flex items-end gap-2 pt-6 pb-2 px-2">
            {trendData.map((item, index) => {
              const freqHeight = Math.min(100, (item.mrr / maxMrr) * 110 + (index * 5));
              return (
                <div key={index} className="flex-1 flex flex-col items-center gap-2 h-full justify-end group relative">
                  <div className="absolute -top-8 bg-slate-800 text-amber-300 text-[10px] font-mono py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap border border-slate-700 pointer-events-none">
                    {item.month} Density: {item.mrr} units
                  </div>
                  <div 
                    style={{ height: `${freqHeight}%` }} 
                    className="w-full bg-amber-500/30 hover:bg-amber-400 border border-amber-500 rounded transition-all"
                  />
                  <span className="text-[10px] text-slate-400 font-mono">{item.month}</span>
                </div>
              );
            })}
          </div>
        )}

        {/* 7. Cohort Target Progress View */}
        {chartType === 'targets' && (
          <div className="h-full flex flex-col justify-center space-y-2.5 px-2">
            <div className="text-xs text-slate-400 font-mono mb-1">Q3 MRR Target Completion Velocity</div>
            {trendData.slice(-3).map((item, index) => {
              const target = 60000;
              const percent = Math.min(100, Math.round((item.mrr / target) * 100));
              return (
                <div key={index} className="space-y-1">
                  <div className="flex justify-between text-[10px] font-mono text-slate-300">
                    <span>{item.month} Actual (${item.mrr.toLocaleString()})</span>
                    <span className="text-cyan-400">{percent}% of $60k Goal</span>
                  </div>
                  <div className="w-full h-2 bg-slate-900 rounded-full overflow-hidden border border-slate-800">
                    <div 
                      style={{ width: `${percent}%` }} 
                      className="h-full bg-gradient-to-r from-cyan-500 to-emerald-400 rounded-full transition-all"
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}

      </div>
    </div>
  );
}