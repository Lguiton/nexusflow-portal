'use client';

import React, { useState } from 'react';
import { BarChart2 } from 'lucide-react';
import { 
  BarChart, Bar, LineChart, Line, ScatterChart, Scatter, 
  PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, 
  Legend, ResponsiveContainer, ZAxis, AreaChart, Area
} from 'recharts';

const TIME_SERIES_DATA = [
  { label: 'Jan', revenue: 45000, cost: 12000, margin: 33000, tier1: 25000, tier2: 20000 },
  { label: 'Feb', revenue: 52000, cost: 14000, margin: 38000, tier1: 28000, tier2: 24000 },
  { label: 'Mar', revenue: 49000, cost: 13500, margin: 35500, tier1: 26000, tier2: 23000 },
  { label: 'Apr', revenue: 63000, cost: 16000, margin: 47000, tier1: 35000, tier2: 28000 },
  { label: 'May', revenue: 71000, cost: 18000, margin: 53000, tier1: 40000, tier2: 31000 },
  { label: 'Jun', revenue: 85000, cost: 21000, margin: 64000, tier1: 48000, tier2: 37000 },
];

const PARETO_DATA = [
  { category: 'Software Subs', frequency: 120, cumulative: 45 },
  { category: 'Cloud Infrastructure', frequency: 85, cumulative: 77 },
  { category: 'Marketing & Ads', frequency: 45, cumulative: 89 },
  { category: 'Legal & Compliance', frequency: 20, cumulative: 96 },
  { category: 'Office Supplies', frequency: 10, cumulative: 100 },
];

const DONUT_DATA = [
  { name: 'Enterprise', value: 45000 },
  { name: 'Pro Tier', value: 25000 },
  { name: 'Starter', value: 10000 },
  { name: 'Add-ons', value: 5000 },
];
const DONUT_COLORS = ['#34d399', '#3b82f6', '#a855f7', '#f43f5e'];

const SCATTER_DATA = [
  { x: 10, y: 30, z: 200, client: 'CLI-001' },
  { x: 25, y: 50, z: 400, client: 'CLI-002' },
  { x: 30, y: 80, z: 600, client: 'CLI-003' },
  { x: 50, y: 90, z: 900, client: 'CLI-004' },
  { x: 70, y: 120, z: 1200, client: 'CLI-005' },
];

const FREQ_TABLE_DATA = [
  { bin: '$0 - $10,000', frequency: 4, relativePct: '25.0%', cumulative: '25.0%' },
  { bin: '$10,001 - $25,000', frequency: 6, relativePct: '37.5%', cumulative: '62.5%' },
  { bin: '$25,001 - $50,000', frequency: 3, relativePct: '18.8%', cumulative: '81.3%' },
  { bin: '$50,001+', frequency: 3, relativePct: '18.7%', cumulative: '100.0%' },
];

export default function AdvancedAnalyticsDashboard() {
  const [activeChart, setActiveChart] = useState<string>('time-series');

  return (
    <div className="w-full bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-md text-slate-100 my-6">
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 mb-6 border-b border-slate-800 pb-4">
        <div>
          <h3 className="text-lg font-bold flex items-center gap-2 text-white">
            <BarChart2 className="text-cyan-400 w-5 h-5" />
            Advanced Statistical & BI Analytics Suite
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Multi-dimensional data exploration, distributions, and predictive plots.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-slate-950 p-1.5 rounded-xl border border-slate-800 overflow-x-auto max-w-full">
          <select 
            value={activeChart} 
            onChange={(e) => setActiveChart(e.target.value)}
            className="bg-slate-900 text-slate-200 text-xs font-semibold py-1.5 px-3 rounded-lg border border-slate-700 focus:outline-none focus:border-cyan-500 cursor-pointer"
          >
            <option value="time-series">Line Chart / Time-Series</option>
            <option value="vertical-bar">Vertical Bar (Column)</option>
            <option value="horizontal-bar">Horizontal Bar</option>
            <option value="grouped-bar">Grouped / Clustered Bar</option>
            <option value="stacked-bar">Stacked Bar Chart</option>
            <option value="pareto">Pareto Chart</option>
            <option value="donut">Donut Chart</option>
            <option value="scatter">Scatter Plot</option>
            <option value="kde-density">Density Plot / KDE Summary</option>
            <option value="box-plot">Box Plot & Violin Metrics</option>
            <option value="freq-table">Frequency Distribution Table</option>
          </select>
        </div>
      </div>

      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {activeChart === 'time-series' ? (
            <LineChart data={TIME_SERIES_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v/1000}k`} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Legend />
              <Line type="monotone" dataKey="revenue" stroke="#34d399" strokeWidth={3} dot={{ r: 4 }} />
              <Line type="monotone" dataKey="cost" stroke="#f43f5e" strokeWidth={2} strokeDasharray="4 4" />
            </LineChart>
          ) : activeChart === 'vertical-bar' ? (
            <BarChart data={TIME_SERIES_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v) => `$${v/1000}k`} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Bar dataKey="revenue" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          ) : activeChart === 'horizontal-bar' ? (
            <BarChart data={TIME_SERIES_DATA} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
              <XAxis type="number" stroke="#64748b" fontSize={12} tickFormatter={(v) => `$${v/1000}k`} />
              <YAxis dataKey="label" type="category" stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Bar dataKey="revenue" fill="#a855f7" radius={[0, 4, 4, 0]} />
            </BarChart>
          ) : activeChart === 'grouped-bar' ? (
            <BarChart data={TIME_SERIES_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Legend />
              <Bar dataKey="tier1" fill="#34d399" name="Tier 1 MRR" />
              <Bar dataKey="tier2" fill="#3b82f6" name="Tier 2 MRR" />
            </BarChart>
          ) : activeChart === 'stacked-bar' ? (
            <BarChart data={TIME_SERIES_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Legend />
              <Bar dataKey="tier1" stackId="a" fill="#34d399" name="Tier 1" />
              <Bar dataKey="tier2" stackId="a" fill="#a855f7" name="Tier 2" />
            </BarChart>
          ) : activeChart === 'pareto' ? (
            <BarChart data={PARETO_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="category" stroke="#64748b" fontSize={10} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Bar dataKey="frequency" fill="#06b6d4" name="Frequency" radius={[4, 4, 0, 0]} />
            </BarChart>
          ) : activeChart === 'donut' ? (
            <PieChart>
              <Pie data={DONUT_DATA} cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={4} dataKey="value">
                {DONUT_DATA.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={DONUT_COLORS[index % DONUT_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Legend />
            </PieChart>
          ) : activeChart === 'scatter' ? (
            <ScatterChart>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="x" name="Volume" stroke="#64748b" />
              <YAxis dataKey="y" name="Value ($)" stroke="#64748b" />
              <ZAxis dataKey="z" range={[60, 400]} />
              <Tooltip cursor={{ strokeDasharray: '3 3' }} contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Scatter name="Clients" data={SCATTER_DATA} fill="#34d399" />
            </ScatterChart>
          ) : activeChart === 'kde-density' ? (
            <AreaChart data={TIME_SERIES_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }} />
              <Area type="monotone" dataKey="margin" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.3} name="Probability Density (KDE)" />
            </AreaChart>
          ) : activeChart === 'box-plot' ? (
            <div className="h-full flex flex-col justify-center items-center text-center p-4 bg-slate-950 rounded-lg border border-slate-800">
              <h4 className="text-sm font-bold text-cyan-400 mb-2">Statistical Distribution: Box Plot & Violin Metrics</h4>
              <div className="grid grid-cols-4 gap-4 w-full max-w-2xl mt-4">
                <div className="bg-slate-900 p-3 rounded border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase">Minimum</span>
                  <p className="text-sm font-bold text-slate-200">$45,000</p>
                </div>
                <div className="bg-slate-900 p-3 rounded border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase">Q1 / Median</span>
                  <p className="text-sm font-bold text-cyan-400">$50,500 / $60,000</p>
                </div>
                <div className="bg-slate-900 p-3 rounded border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase">Q3 / Max</span>
                  <p className="text-sm font-bold text-emerald-400">$77,500 / $85,000</p>
                </div>
                <div className="bg-slate-900 p-3 rounded border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase">IQR Variance</span>
                  <p className="text-sm font-bold text-purple-400">±14.2%</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="h-full overflow-y-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950 text-slate-400 uppercase border-b border-slate-800">
                  <tr>
                    <th className="p-2.5">Revenue Bin</th>
                    <th className="p-2.5">Frequency (Count)</th>
                    <th className="p-2.5">Relative %</th>
                    <th className="p-2.5">Cumulative %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 text-slate-300">
                  {FREQ_TABLE_DATA.map((row, idx) => (
                    <tr key={idx} className="hover:bg-slate-950/50">
                      <td className="p-2.5 font-bold text-cyan-300">{row.bin}</td>
                      <td className="p-2.5">{row.frequency}</td>
                      <td className="p-2.5">{row.relativePct}</td>
                      <td className="p-2.5 text-emerald-400">{row.cumulative}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}