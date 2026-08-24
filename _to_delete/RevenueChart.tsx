"use client";

import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { BarChart3 } from "lucide-react";

const data = [
  { month: 'Jan', revenue: 45000, cost: 12000 },
  { month: 'Feb', revenue: 52000, cost: 11000 },
  { month: 'Mar', revenue: 48000, cost: 10500 },
  { month: 'Apr', revenue: 61000, cost: 13000 },
  { month: 'May', revenue: 69000, cost: 14000 },
  { month: 'Jun', revenue: 82000, cost: 15000 },
];

export default function RevenueChart() {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-2xl">
      <div className="mb-6 flex justify-between items-center border-b border-slate-800 pb-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-indigo-400" />
          <div>
            <h3 className="text-slate-100 font-semibold text-sm">Advanced Statistical & BI Analytics Suite</h3>
            <p className="text-slate-400 text-xs mt-0.5">Multi-dimensional data exploration and predictive plots.</p>
          </div>
        </div>
        <select className="bg-slate-950 border border-slate-700 text-slate-300 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-500 font-medium">
          <option>Line Chart / Time-Series</option>
          <option>Bar Chart / Segmented</option>
        </select>
      </div>
      <div className="h-[300px] w-full text-xs">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey="month" stroke="#64748b" tickLine={false} axisLine={false} tickMargin={10} />
            <YAxis stroke="#64748b" tickLine={false} axisLine={false} tickFormatter={(value) => `$${value/1000}k`} />
            <Tooltip
              contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9', borderRadius: '8px' }}
              itemStyle={{ color: '#818cf8', fontWeight: 500 }}
            />
            <Legend iconType="circle" wrapperStyle={{ paddingTop: '20px', color: '#94a3b8' }} />
            <Line type="monotone" name="Revenue" dataKey="revenue" stroke="#34d399" strokeWidth={3} dot={{ r: 4, fill: '#0f172a', strokeWidth: 2, stroke: '#34d399' }} activeDot={{ r: 6, fill: '#34d399' }} />
            <Line type="monotone" name="Cost" dataKey="cost" stroke="#f43f5e" strokeWidth={3} dot={{ r: 4, fill: '#0f172a', strokeWidth: 2, stroke: '#f43f5e' }} activeDot={{ r: 6, fill: '#f43f5e' }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
