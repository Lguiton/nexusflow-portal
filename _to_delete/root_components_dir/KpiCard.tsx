import React from 'react';
import { LucideIcon } from 'lucide-react';

interface KpiCardProps {
  title: string;
  value: string | number;
  icon: LucideIcon;
  trend?: string;
  status?: 'normal' | 'warning' | 'critical';
  footerText?: string;
}

export default function KpiCard({ title, value, icon: Icon, trend, status = 'normal', footerText }: KpiCardProps) {
  const statusColors = {
    normal: 'text-emerald-400 bg-emerald-950/50 border-emerald-800/50',
    warning: 'text-amber-400 bg-amber-950/50 border-amber-800/50',
    critical: 'text-red-400 bg-red-950/50 border-red-800/50'
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col gap-3 transition-all hover:border-slate-700">
      <div className="flex items-center justify-between text-slate-400">
        <span className="text-sm font-medium">{title}</span>
        <Icon className="w-5 h-5 text-indigo-400" />
      </div>
      
      <div className="text-3xl font-bold text-slate-100">{value}</div>
      
      {(trend || footerText) && (
        <div className="flex items-center justify-between mt-1">
          {trend && (
            <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded border ${statusColors[status]}`}>
              {trend}
            </span>
          )}
          {footerText && <span className="text-xs text-slate-500">{footerText}</span>}
        </div>
      )}
    </div>
  );
}
