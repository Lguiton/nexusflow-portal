'use client';

import React from 'react';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';

// Elite Tailwind colors for our charts
const COLORS = ['#22d3ee', '#818cf8', '#34d399', '#f472b6', '#fbbf24'];

interface ChartProps {
  chartType: 'bar' | 'pie' | 'stacked_bar' | 'pareto';
  data: any[];
  config: {
    xAxisKey: string;
    dataKeys: string[];
  };
}

export default function DynamicChartEngine({ chartType, data, config }: ChartProps) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-sm p-4 text-center font-mono">No data available for visualization.</div>;
  }

  // --- PIE CHART RENDERER ---
  if (chartType === 'pie') {
    return (
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={80}
            paddingAngle={5}
            dataKey={config.dataKeys[0]}
            nameKey={config.xAxisKey}
          >
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip 
            contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f8fafc', borderRadius: '8px' }}
            itemStyle={{ color: '#22d3ee' }}
          />
          <Legend wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  // --- BAR / STACKED BAR RENDERER ---
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis dataKey={config.xAxisKey} stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
        <YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
        <Tooltip 
          cursor={{ fill: '#1e293b' }}
          contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f8fafc', borderRadius: '8px' }}
        />
        <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
        {config.dataKeys.map((key, idx) => (
          <Bar 
            key={key} 
            dataKey={key} 
            stackId={chartType === 'stacked_bar' ? "a" : undefined}
            fill={COLORS[idx % COLORS.length]} 
            radius={chartType === 'stacked_bar' ? [0, 0, 0, 0] : [4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
