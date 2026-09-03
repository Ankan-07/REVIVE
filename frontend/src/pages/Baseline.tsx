import React, { useEffect, useState } from 'react';
import { fetchBaselineComparison, BaselineComparisonResponse } from '../api/analytics';
import { RefreshCw, TrendingUp, AlertTriangle, IndianRupee, Activity } from 'lucide-react';

export function Baseline() {
  const [data, setData] = useState<BaselineComparisonResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchBaselineComparison();
      setData(response);
    } catch (err: any) {
      setError(err.message || 'Failed to load benchmark data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-slate-400">
        <RefreshCw className="w-8 h-8 animate-spin mb-4 text-indigo-500" />
        <p>Loading benchmark data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-300">
        <h3 className="font-bold flex items-center gap-2 mb-2">
          <AlertTriangle className="w-5 h-5" /> Error Loading Benchmark
        </h3>
        <p>{error}</p>
        <button 
          onClick={loadData}
          className="mt-4 px-4 py-2 bg-rose-500/20 hover:bg-rose-500/30 rounded-lg text-rose-200 transition"
        >
          Try Again
        </button>
      </div>
    );
  }

  if (!data || data.simulation_run_id === 'none') {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-slate-400">
        <Activity className="w-8 h-8 mb-4 text-slate-500" />
        <p>No simulation runs found. Run a simulation first to see the benchmark.</p>
      </div>
    );
  }

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(amount);
  };

  const formatPercent = (rate: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'percent',
      maximumFractionDigits: 1,
    }).format(rate);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">
            Strategy Benchmark
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Comparing REVIVE AI against naive baseline (Seed: {data.seed})
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition disabled:opacity-50"
        >
          <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Baseline Column */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          <div className="bg-slate-800/50 p-4 border-b border-slate-800 text-center">
            <h3 className="font-bold text-slate-300">Naive Baseline</h3>
            <p className="text-xs text-slate-500 mt-1">1 Retry + 1 Reminder</p>
          </div>
          <div className="p-6 space-y-6">
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold mb-1">Gross Recovered</div>
              <div className="text-2xl font-mono text-slate-300">{formatCurrency(data.baseline.gross_recovered)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold mb-1">Net Recovered</div>
              <div className="text-2xl font-mono text-slate-300">{formatCurrency(data.baseline.net_recovered)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold mb-1">Recovery Rate</div>
              <div className="text-2xl font-mono text-slate-300">{formatPercent(data.baseline.recovery_rate)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold mb-1">Escalation Rate</div>
              <div className="text-2xl font-mono text-slate-300">{formatPercent(data.baseline.escalation_rate)}</div>
            </div>
          </div>
        </div>

        {/* REVIVE Column */}
        <div className="bg-indigo-950/20 border border-indigo-500/30 rounded-2xl overflow-hidden shadow-2xl relative">
          <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-indigo-500 to-cyan-500"></div>
          <div className="bg-indigo-900/20 p-4 border-b border-indigo-500/20 text-center">
            <h3 className="font-bold text-indigo-300">REVIVE Agent</h3>
            <p className="text-xs text-indigo-400/70 mt-1">Contextual LangGraph Loop</p>
          </div>
          <div className="p-6 space-y-6">
            <div>
              <div className="text-xs text-indigo-400/60 uppercase tracking-wider font-semibold mb-1">Gross Recovered</div>
              <div className="text-2xl font-mono text-indigo-100">{formatCurrency(data.revive.gross_recovered)}</div>
            </div>
            <div>
              <div className="text-xs text-indigo-400/60 uppercase tracking-wider font-semibold mb-1">Net Recovered</div>
              <div className="text-2xl font-mono text-indigo-100 font-bold">{formatCurrency(data.revive.net_recovered)}</div>
            </div>
            <div>
              <div className="text-xs text-indigo-400/60 uppercase tracking-wider font-semibold mb-1">Recovery Rate</div>
              <div className="text-2xl font-mono text-indigo-100">{formatPercent(data.revive.recovery_rate)}</div>
            </div>
            <div>
              <div className="text-xs text-indigo-400/60 uppercase tracking-wider font-semibold mb-1">Escalation Rate</div>
              <div className="text-2xl font-mono text-indigo-100">{formatPercent(data.revive.escalation_rate)}</div>
            </div>
          </div>
        </div>

        {/* Delta Column */}
        <div className="bg-emerald-950/20 border border-emerald-500/30 rounded-2xl overflow-hidden shadow-2xl relative flex flex-col justify-center">
          <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-emerald-500 to-teal-500"></div>
          <div className="p-8 text-center space-y-8">
            <div>
              <div className="inline-flex items-center justify-center p-3 bg-emerald-500/20 rounded-full text-emerald-400 mb-4">
                <TrendingUp className="w-8 h-8" />
              </div>
              <div className="text-xs text-emerald-400/70 uppercase tracking-wider font-semibold mb-2">Net Revenue Lift</div>
              <div className={`text-4xl font-mono font-bold ${data.delta_net >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {data.delta_net >= 0 ? '+' : ''}{formatCurrency(data.delta_net)}
              </div>
            </div>
            
            <div className="pt-6 border-t border-emerald-500/20">
              <div className="text-xs text-emerald-400/70 uppercase tracking-wider font-semibold mb-2">Escalation Delta</div>
              <div className={`text-2xl font-mono ${data.delta_escalation_rate <= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {data.delta_escalation_rate > 0 ? '+' : ''}{formatPercent(data.delta_escalation_rate)}
              </div>
              <p className="text-xs text-emerald-400/50 mt-2">
                {data.delta_escalation_rate <= 0 ? 'Less human operator time required' : 'More human operator time required'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
