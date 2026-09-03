import React from 'react';
import { cn } from '../lib/utils';

interface MetricCardProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: 'up' | 'down' | 'neutral';
  trendValue?: string;
}

export function MetricCard({ title, value, subtitle, icon, trend, trendValue, className, ...props }: MetricCardProps) {
  return (
    <div 
      className={cn(
        "bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6 flex flex-col gap-4",
        className
      )} 
      {...props}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-400">{title}</h3>
        {icon && <div className="text-slate-500">{icon}</div>}
      </div>
      <div>
        <div className="text-2xl font-bold text-slate-100">{value}</div>
        {(subtitle || trendValue) && (
          <div className="flex items-center gap-2 mt-1">
            {trendValue && (
              <span className={cn(
                "text-xs font-semibold",
                trend === 'up' ? "text-emerald-400" : trend === 'down' ? "text-rose-400" : "text-slate-400"
              )}>
                {trendValue}
              </span>
            )}
            {subtitle && <span className="text-xs text-slate-500">{subtitle}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
