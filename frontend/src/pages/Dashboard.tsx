import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { fetchRecoveryTotals, fetchInterventionStats } from '../api/analytics';
import { listCases } from '../api/cases';
import { MetricCard } from '../components/MetricCard';
import { FunnelChart } from '../components/FunnelChart';
import { Activity, DollarSign, ShieldAlert, TrendingUp } from 'lucide-react';
import { cn } from '../lib/utils';

export function Dashboard() {
  const { data: totals, isLoading: loadingTotals } = useQuery({
    queryKey: ['recoveryTotals'],
    queryFn: () => fetchRecoveryTotals()
  });

  const { data: interventions, isLoading: loadingInterventions } = useQuery({
    queryKey: ['interventionStats'],
    queryFn: () => fetchInterventionStats()
  });

  const { data: cases, isLoading: loadingCases } = useQuery({
    queryKey: ['cases', { skip: 0, limit: 10 }],
    queryFn: () => listCases(0, 10)
  });

  return (
    <div className="space-y-6">
      {/* Top Level Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard 
          title="Total Risk Detected" 
          value={loadingTotals ? '...' : `₹${totals?.total_amount_at_risk?.toLocaleString() || 0}`} 
          icon={<ShieldAlert className="w-5 h-5" />}
          subtitle={`${totals?.total_cases || 0} active cases`}
        />
        <MetricCard 
          title="Net Recovered" 
          value={loadingTotals ? '...' : `₹${totals?.net_recovered?.toLocaleString() || 0}`}
          icon={<DollarSign className="w-5 h-5" />}
          trend="up"
          trendValue={loadingTotals ? '' : `${totals?.recovery_rate?.toFixed(1) || 0}%`}
          subtitle="recovery rate"
        />
        <MetricCard 
          title="Intervention Cost" 
          value={loadingTotals ? '...' : `₹${totals?.total_intervention_cost?.toLocaleString() || 0}`}
          icon={<Activity className="w-5 h-5" />}
          subtitle="Agent operational cost"
        />
        <MetricCard 
          title="Avg. Recovery Time" 
          value={loadingTotals ? '...' : `${totals?.average_recovery_time_hours?.toFixed(1) || 0}h`}
          icon={<TrendingUp className="w-5 h-5" />}
          subtitle="From detection to resolved"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Intervention Performance */}
        <div className="lg:col-span-1 bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6">
          <h3 className="text-lg font-bold text-slate-100 mb-6">Intervention Funnel</h3>
          <div className="h-[300px]">
            {loadingInterventions ? (
              <div className="h-full flex items-center justify-center text-slate-500 text-sm animate-pulse">Loading charts...</div>
            ) : (
              <FunnelChart data={interventions?.stats || []} />
            )}
          </div>
        </div>

        {/* Active Cases Table */}
        <div className="lg:col-span-2 bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl flex flex-col overflow-hidden">
          <div className="p-6 border-b border-slate-800">
            <h3 className="text-lg font-bold text-slate-100">Recent Revenue Risk Cases</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-400">
              <thead className="text-xs uppercase bg-slate-950/50 text-slate-500">
                <tr>
                  <th className="px-6 py-3 font-medium">Case ID</th>
                  <th className="px-6 py-3 font-medium">Type</th>
                  <th className="px-6 py-3 font-medium text-right">Amount at Risk</th>
                  <th className="px-6 py-3 font-medium text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {loadingCases ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center animate-pulse">Loading cases...</td>
                  </tr>
                ) : cases?.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center italic">No cases found.</td>
                  </tr>
                ) : (
                  cases?.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-800/20 transition-colors">
                      <td className="px-6 py-4 font-mono text-indigo-400">
                        <Link to={`/cases/${c.id}`} className="hover:underline">{c.id}</Link>
                      </td>
                      <td className="px-6 py-4">{c.case_type}</td>
                      <td className="px-6 py-4 text-right font-medium text-slate-200">₹{c.amount_at_risk.toLocaleString()}</td>
                      <td className="px-6 py-4 flex justify-center">
                        <span className={cn(
                          "px-2.5 py-1 rounded-md text-xs font-semibold border",
                          c.status === 'RECOVERED' ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : 
                          c.status === 'DETECTED' ? "bg-amber-500/10 text-amber-400 border-amber-500/20" : 
                          c.status === 'ESCALATED' ? "bg-rose-500/10 text-rose-400 border-rose-500/20" : 
                          "bg-slate-500/10 text-slate-400 border-slate-500/20"
                        )}>
                          {c.status}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
