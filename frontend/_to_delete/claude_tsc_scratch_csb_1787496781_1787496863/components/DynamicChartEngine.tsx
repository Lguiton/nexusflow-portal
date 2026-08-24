'use client';

import React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell,
  LineChart, Line
} from 'recharts';

// Elite Tailwind colors for our charts
const COLORS = ['#22d3ee', '#818cf8', '#34d399', '#f472b6', '#fbbf24'];

interface ChartProps {
  // Added 'line' and 'histogram'. 'line' previously had NO renderer at
  // all here -- bi_visualization_architect.py's real chart-recommendation
  // logic can return chart_type="line" for a monthly revenue trend, and
  // any caller passing that through this component silently fell into the
  // BAR renderer below instead of a real line chart. 'histogram' needed
  // no new rendering logic (a histogram of pre-computed bins is just a bar
  // chart over range labels), only the type addition, since it already
  // falls through to the same generic bar renderer.
  chartType: 'bar' | 'pie' | 'stacked_bar' | 'pareto' | 'line' | 'histogram';
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

  // --- LINE CHART RENDERER (e.g. real monthly revenue trend) ---
  if (chartType === 'line') {
    return (
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
          <XAxis dataKey={config.xAxisKey} stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
          <YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
          <Tooltip
            contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9', borderRadius: '8px' }}
            itemStyle={{ color: '#818cf8', fontWeight: 500 }}
          />
          <Legend iconType="circle" wrapperStyle={{ paddingTop: '10px', color: '#94a3b8', fontSize: '12px' }} />
          {config.dataKeys.map((key, idx) => (
            <Line
              key={key}
              type="monotone"
              name={key}
              dataKey={key}
              stroke={COLORS[idx % COLORS.length]}
              strokeWidth={3}
              dot={{ r: 4, fill: '#0f172a', strokeWidth: 2, stroke: COLORS[idx % COLORS.length] }}
              activeDot={{ r: 6, fill: COLORS[idx % COLORS.length] }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // --- BAR / STACKED BAR / PARETO / HISTOGRAM RENDERER ---
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
