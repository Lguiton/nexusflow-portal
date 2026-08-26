"use client";

import React from "react";
import {
  ComposedChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

// Real box plot (min / Q1 / median / Q3 / max) of transaction amounts per
// category -- backed by db_manager.get_category_amount_stats, computed via
// DuckDB's real PERCENTILE_CONT/MEDIAN aggregates against this tenant's
// actual ledger rows. Recharts has no built-in box plot primitive, so this
// draws one manually: a single invisible <Bar> per category supplies the
// full-height "background" rect Recharts computes for every bar (spanning
// the whole y-axis range at that bar's x position), and a custom `shape`
// renderer converts the real min/q1/median/q3/max values into pixel
// positions within that rect to draw the whiskers, box, and median line.
// This is exactly the technique Recharts' own Bar.js source anticipates --
// see the comment on hasCustomShape in computeBarRectangles ("the custom
// renderer may still draw something visible... e.g. horizontal lines in a
// BoxPlot").

interface BoxStat {
  category: string;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  entry_count: number;
}

interface BoxPlotChartProps {
  data: BoxStat[];
}

const BOX_STROKE = "#5fd3ff";
const BOX_FILL = "rgba(95, 211, 255, 0.16)";

const currency = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

export default function BoxPlotChart({ data }: BoxPlotChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="text-slate-500 text-sm p-4 text-center font-mono">
        No transaction-amount spread data available.
      </div>
    );
  }

  const rawMin = Math.min(...data.map((d) => d.min));
  const rawMax = Math.max(...data.map((d) => d.max));
  const span = rawMax - rawMin;
  // A little headroom above/below the real min/max so whisker caps aren't
  // drawn flush against the plot edge. Falls back to a small absolute pad
  // when every value is identical (span === 0), so the axis never
  // collapses to a single point.
  const pad = span > 0 ? span * 0.08 : Math.max(Math.abs(rawMax), 1) * 0.08;
  const domainMin = rawMin - pad;
  const domainMax = rawMax + pad;

  const renderBoxAndWhiskers = (props: any) => {
    const { x, width, background, payload } = props;
    if (!background || !payload) return <g />;
    const stat = payload as BoxStat;

    const yFor = (v: number) => {
      if (domainMax === domainMin) return background.y + background.height / 2;
      const ratio = (domainMax - v) / (domainMax - domainMin);
      return background.y + ratio * background.height;
    };

    const cx = x + width / 2;
    const boxWidth = Math.max(10, width * 0.5);
    const boxX = cx - boxWidth / 2;
    const capHalf = boxWidth / 4;

    const yMin = yFor(stat.min);
    const yQ1 = yFor(stat.q1);
    const yMedian = yFor(stat.median);
    const yQ3 = yFor(stat.q3);
    const yMax = yFor(stat.max);

    return (
      <g>
        <line x1={cx} y1={yMin} x2={cx} y2={yQ1} stroke={BOX_STROKE} strokeWidth={1.5} />
        <line x1={cx} y1={yQ3} x2={cx} y2={yMax} stroke={BOX_STROKE} strokeWidth={1.5} />
        <line x1={cx - capHalf} y1={yMin} x2={cx + capHalf} y2={yMin} stroke={BOX_STROKE} strokeWidth={1.5} />
        <line x1={cx - capHalf} y1={yMax} x2={cx + capHalf} y2={yMax} stroke={BOX_STROKE} strokeWidth={1.5} />
        <rect
          x={boxX}
          y={Math.min(yQ1, yQ3)}
          width={boxWidth}
          height={Math.max(1, Math.abs(yQ3 - yQ1))}
          fill={BOX_FILL}
          stroke={BOX_STROKE}
          strokeWidth={1.5}
          rx={2}
        />
        <line x1={boxX} y1={yMedian} x2={boxX + boxWidth} y2={yMedian} stroke={BOX_STROKE} strokeWidth={2} />
      </g>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis dataKey="category" stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
        <YAxis
          domain={[domainMin, domainMax]}
          stroke="#64748b"
          fontSize={11}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          cursor={{ fill: "#1e293b" }}
          content={({ active, payload }) => {
            if (!active || !payload || !payload.length) return null;
            const d = payload[0].payload as BoxStat;
            return (
              <div className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 shadow-xl">
                <p className="font-semibold mb-1">{d.category}</p>
                <p>Max: {currency(d.max)}</p>
                <p>Q3: {currency(d.q3)}</p>
                <p>Median: {currency(d.median)}</p>
                <p>Q1: {currency(d.q1)}</p>
                <p>Min: {currency(d.min)}</p>
                <p className="text-slate-500 mt-1">
                  {d.entry_count} transaction{d.entry_count === 1 ? "" : "s"}
                </p>
              </div>
            );
          }}
        />
        <Bar
          dataKey="max"
          fill="transparent"
          background={{ fill: "transparent" }}
          shape={renderBoxAndWhiskers}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
