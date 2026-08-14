'use client';

import React, { useState } from 'react';
import { BarChart3, TrendingUp, AreaChart as AreaIcon, PieChart as PieIcon } from 'lucide-react';
import { 
  LineChart, Line, BarChart, Bar, AreaChart, Area, PieChart, Pie, Cell, Legend,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer 
} from 'recharts';

// Time-series data for Line, Bar, and Area charts
const MOCK_MRR_DATA = [
  { month: 'Jan', mrr: 45000 },
  { month: 'Feb', mrr: 52000 },
  { month: 'Mar', mrr: 49000 },
  { month: 'Apr', mrr: 63000 },
  { month: 'May', mrr: 71000 },
  { month: 'Jun', mrr: 85000 },
];

// Categorical data for the Pie chart
const MOCK_PIE_DATA = [
  { name: 'Enterprise', value: 45000 },
  { name: 'Pro Tier', value: 25000 },
  { name: 'Starter', value: 10000 },
  { name: 'Add-ons', value: 5000 },
];
const PIE_COLORS = ['#34d399', '#3b82f6', '#a855f7', '#f43f5e'];

export default function MRRChartWidget() {
  const [chartType, setChartType] = useState<'area' | 'bar' | 'line' | 'pie'>('area');

  return (
    <div className="w-full bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-md text-slate-100 mt-6">
      <div className="flex items-center justify-between mb-6 border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-lg font-bold flex items-center gap-2 text-white">
            <TrendingUp className="text-emerald-400 w-5 h-5" />
            Recurring Revenue (MRR)
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            {chartType === 'pie' ? "Current Month Revenue Breakdown" : "6-Month Trailing Revenue Trajectory"}
          </p>
        </div>
        
        {/* Advanced Chart Options Toggle */}
        <div className="flex bg-slate-950 rounded-lg p-1 border border-slate-800">
          <button
            onClick={() => setChartType('area')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5 ${
              chartType === 'area' ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <AreaIcon className="w-3.5 h-3.5" /> Area
          </button>
          <button
            onClick={() => setChartType('bar')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5 ${
              chartType === 'bar' ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" /> Bar
          </button>
          <button
            onClick={() => setChartType('line')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5 ${
              chartType === 'line' ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <TrendingUp className="w-3.5 h-3.5" /> Line
          </button>
          <button
            onClick={() => setChartType('pie')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5 border-l border-slate-800 ml-1 pl-4 ${
              chartType === 'pie' ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <PieIcon className="w-3.5 h-3.5" /> Breakdown
          </button>
        </div>
      </div>

      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chartType === 'area' ? (
            <AreaChart data={MOCK_MRR_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="month" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `$${value / 1000}k`} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }}
                itemStyle={{ color: '#34d399', fontWeight: 'bold' }}
                formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'MRR']}
              />
              <Area type="monotone" dataKey="mrr" stroke="#34d399" fill="#34d399" fillOpacity={0.2} strokeWidth={3} />
            </AreaChart>

          ) : chartType === 'bar' ? (
            <BarChart data={MOCK_MRR_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="month" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `$${value / 1000}k`} />
              <Tooltip 
                cursor={{fill: '#1e293b', opacity: 0.4}}
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }}
                itemStyle={{ color: '#3b82f6', fontWeight: 'bold' }}
                formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'MRR']}
              />
              <Bar dataKey="mrr" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>

          ) : chartType === 'pie' ? (
            <PieChart>
              <Pie
                data={MOCK_PIE_DATA}
                cx="50%" cy="50%"
                innerRadius={60} outerRadius={100}
                paddingAngle={5}
                dataKey="value" stroke="none"
              >
                {MOCK_PIE_DATA.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip 
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }}
                itemStyle={{ color: '#f8fafc', fontWeight: 'bold' }}
                formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'Revenue']}
              />
              <Legend verticalAlign="bottom" height={36} iconType="circle" wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }}/>
            </PieChart>

          ) : (
            <LineChart data={MOCK_MRR_DATA}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="month" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `$${value / 1000}k`} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }}
                itemStyle={{ color: '#a855f7', fontWeight: 'bold' }}
                formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'MRR']}
              />
              <Line type="monotone" dataKey="mrr" stroke="#a855f7" strokeWidth={3} dot={{ r: 4, fill: '#0f172a', stroke: '#a855f7', strokeWidth: 2 }} />
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}