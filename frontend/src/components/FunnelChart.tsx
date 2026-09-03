import React from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { InterventionStat } from '../api/analytics';

interface FunnelChartProps {
  data: InterventionStat[];
}

export function FunnelChart({ data }: FunnelChartProps) {
  if (!data || data.length === 0) {
    return <div className="h-full flex items-center justify-center text-slate-500 text-sm">No intervention data available</div>;
  }

  // Format data for the chart
  const chartData = data.map(stat => ({
    name: stat.intervention_type,
    count: stat.count,
    success: stat.success_count,
    rate: stat.count > 0 ? (stat.success_count / stat.count) * 100 : 0
  })).sort((a, b) => b.count - a.count);

  return (
    <div className="w-full h-full min-h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
        >
          <XAxis type="number" hide />
          <YAxis 
            dataKey="name" 
            type="category" 
            axisLine={false} 
            tickLine={false}
            tick={{ fill: '#94a3b8', fontSize: 12 }}
            width={120}
          />
          <Tooltip 
            cursor={{ fill: '#1e293b', opacity: 0.4 }}
            content={({ active, payload }) => {
              if (active && payload && payload.length) {
                const data = payload[0].payload;
                return (
                  <div className="bg-slate-900 border border-slate-800 p-3 rounded-lg shadow-xl text-sm">
                    <p className="font-semibold text-slate-200 mb-2">{data.name}</p>
                    <p className="text-slate-400">Total Attemps: <span className="text-slate-200 font-mono">{data.count}</span></p>
                    <p className="text-slate-400">Successes: <span className="text-emerald-400 font-mono">{data.success}</span></p>
                    <p className="text-slate-400">Success Rate: <span className="text-indigo-400 font-mono">{data.rate.toFixed(1)}%</span></p>
                  </div>
                );
              }
              return null;
            }}
          />
          <Bar dataKey="count" fill="#334155" radius={[0, 4, 4, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill="#334155" />
            ))}
          </Bar>
          <Bar dataKey="success" fill="#4f46e5" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
