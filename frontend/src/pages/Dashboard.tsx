import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { fetchRecoveryTotals, fetchInterventionStats } from '../api/analytics';
import { listCases } from '../api/cases';
import { MetricCard } from '../components/MetricCard';
import { FunnelChart } from '../components/FunnelChart';
import { Activity, DollarSign, ShieldAlert, TrendingUp, AlertCircle } from 'lucide-react';
import { cn } from '../lib/utils';

export function Dashboard() {
  const [origin, setOrigin] = React.useState<'live' | 'lab'>('live');

  const { data: totals, isLoading: loadingTotals, isError: isTotalsError, error: totalsError } = useQuery({
    queryKey: ['recoveryTotals', origin],
    queryFn: () => fetchRecoveryTotals(undefined, undefined, undefined, origin)
  });

  const { data: interventions, isLoading: loadingInterventions, isError: isInterventionsError } = useQuery({
    queryKey: ['interventionStats', origin],
    queryFn: () => fetchInterventionStats(undefined, undefined, undefined, origin)
  });

  const { data: cases, isLoading: loadingCases, isError: isCasesError } = useQuery({
    queryKey: ['cases', { skip: 0, limit: 10, origin }],
    queryFn: () => listCases(0, 10, origin)
  });

  return (
    <div className="space-y-6">
      {/* Dashboard Header & Environment Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">Recovery Operations Dashboard</h1>
          <p className="text-xs text-slate-400 mt-0.5">Real-time metrics, automated interventions, and case resolution ledger.</p>
        </div>
        <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 p-1 rounded-xl text-xs font-semibold self-start sm:self-auto">
          <button
            onClick={() => setOrigin('live')}
            className={cn(
              'px-3 py-1 rounded-lg transition cursor-pointer',
              origin === 'live' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'text-slate-400 hover:text-slate-200'
            )}
          >
            ● Live Cases
          </button>
          <button
            onClick={() => setOrigin('lab')}
            className={cn(
              'px-3 py-1 rounded-lg transition cursor-pointer',
              origin === 'lab' ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'text-slate-400 hover:text-slate-200'
            )}
          >
            Simulation Lab
          </button>
        </div>
      </div>

      {/* Top Level Metrics */}
      {isTotalsError ? (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-4 rounded-xl text-sm flex items-center gap-2">
          <AlertCircle className="w-5 h-5" />
          Failed to load recovery totals: {totalsError instanceof Error ? totalsError.message : 'Unknown error'}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <MetricCard 
            title="Total Risk Detected" 
            value={loadingTotals ? <div className="h-8 w-24 bg-slate-800 rounded animate-pulse"></div> : `₹${totals?.total_amount_at_risk?.toLocaleString() || 0}`} 
            icon={<ShieldAlert className="w-5 h-5" />}
            subtitle={loadingTotals ? <div className="h-4 w-20 bg-slate-800 rounded mt-1 animate-pulse"></div> : `${totals?.total_cases || 0} closed cases`}
          />
          <MetricCard 
            title="Net Recovered" 
            value={loadingTotals ? <div className="h-8 w-24 bg-slate-800 rounded animate-pulse"></div> : `₹${totals?.total_net_recovered?.toLocaleString() || 0}`}
            icon={<DollarSign className="w-5 h-5" />}
            trend={loadingTotals ? undefined : "up"}
            trendValue={loadingTotals ? '' : `${((totals?.recovery_rate ?? 0) * 100).toFixed(1)}%`}
            subtitle={loadingTotals ? <div className="h-4 w-20 bg-slate-800 rounded mt-1 animate-pulse"></div> : "recovery rate"}
          />
          <MetricCard 
            title="Intervention Cost" 
            value={loadingTotals ? <div className="h-8 w-24 bg-slate-800 rounded animate-pulse"></div> : `₹${totals?.total_intervention_costs?.toLocaleString() || 0}`}
            icon={<Activity className="w-5 h-5" />}
            subtitle={loadingTotals ? <div className="h-4 w-20 bg-slate-800 rounded mt-1 animate-pulse"></div> : "Agent operational cost"}
          />
          <MetricCard 
            title="Avg. Recovery Time" 
            value={loadingTotals ? <div className="h-8 w-24 bg-slate-800 rounded animate-pulse"></div> : `${(totals?.average_recovery_time_hours ?? 0).toFixed(1)}h`}
            icon={<TrendingUp className="w-5 h-5" />}
            subtitle={loadingTotals ? <div className="h-4 w-20 bg-slate-800 rounded mt-1 animate-pulse"></div> : "From detection to resolved"}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Cases by Type Summary */}
        <div className="lg:col-span-1 bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6">
          <h3 className="text-lg font-bold text-slate-100 mb-6">Cases by Type</h3>
          {isCasesError ? (
            <div className="text-rose-400 text-sm flex items-center gap-2">
              <AlertCircle className="w-4 h-4" /> Failed to load case types
            </div>
          ) : (
            <div className="space-y-4">
              {['FAILED_PAYMENT', 'ABANDONED_CHECKOUT', 'OVERDUE_INVOICE'].map(type => {
                const count = cases?.filter(c => c.case_type === type).length || 0;
                return (
                  <div key={type} className="flex justify-between items-center bg-slate-950/50 p-3 rounded-lg border border-slate-800/50">
                    <span className="text-sm font-medium text-slate-300">{type.replace('_', ' ')}</span>
                    {loadingCases ? (
                      <div className="h-5 w-8 bg-slate-800 rounded animate-pulse"></div>
                    ) : (
                      <span className="text-sm font-bold text-indigo-400">{count}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Intervention Performance */}
        <div className="lg:col-span-1 bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6">
          <h3 className="text-lg font-bold text-slate-100 mb-6">Intervention Funnel</h3>
          <div className="h-[300px]">
            {isInterventionsError ? (
               <div className="h-full flex items-center justify-center text-rose-400 text-sm gap-2">
                 <AlertCircle className="w-4 h-4" /> Failed to load charts
               </div>
            ) : loadingInterventions ? (
              <div className="h-full flex items-center justify-center text-slate-500 text-sm animate-pulse">Loading charts...</div>
            ) : (
              <FunnelChart data={interventions?.stats || []} />
            )}
          </div>
        </div>

        {/* Active Cases Table */}
        <div className="lg:col-span-3 bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl flex flex-col overflow-hidden">
          <div className="p-6 border-b border-slate-800">
            <h3 className="text-lg font-bold text-slate-100">Recent Revenue Risk Cases</h3>
          </div>
          <div className="overflow-x-auto">
            {isCasesError ? (
               <div className="p-8 text-center text-rose-400 flex flex-col items-center justify-center gap-2">
                 <AlertCircle className="w-6 h-6" />
                 <span>Failed to load cases. Please try again.</span>
               </div>
            ) : (
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
                    Array.from({ length: 5 }).map((_, i) => (
                      <tr key={i} className="animate-pulse">
                        <td className="px-6 py-4"><div className="h-4 w-24 bg-slate-800 rounded"></div></td>
                        <td className="px-6 py-4"><div className="h-4 w-32 bg-slate-800 rounded"></div></td>
                        <td className="px-6 py-4 flex justify-end"><div className="h-4 w-16 bg-slate-800 rounded"></div></td>
                        <td className="px-6 py-4"><div className="h-6 w-20 bg-slate-800 rounded mx-auto"></div></td>
                      </tr>
                    ))
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
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
