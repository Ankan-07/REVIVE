import React, { useEffect, useState } from 'react';
import { fetchHealth, API_BASE_URL } from './api/client';
import { Activity, CheckCircle2, XCircle, RefreshCw, ShieldCheck, Zap } from 'lucide-react';

export function App() {
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const checkHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchHealth();
      setStatus(data.status);
    } catch (err: any) {
      setError(err.message || 'Unable to connect to backend server');
      setStatus(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center p-6">
      {/* Header Badge */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold uppercase tracking-wider mb-6">
        <Zap className="w-3.5 h-3.5" />
        Phase 0 & 1 Operational
      </div>

      {/* Main Container */}
      <div className="w-full max-w-md bg-slate-900/80 backdrop-blur border border-slate-800 rounded-2xl p-6 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-100 tracking-tight">Revenue Rescue Engine</h1>
              <p className="text-xs text-slate-400">System Health Dashboard</p>
            </div>
          </div>
          <button
            onClick={checkHealth}
            disabled={loading}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition disabled:opacity-50"
            title="Refresh Health Status"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* Status Display Card */}
        <div className="bg-slate-950/60 border border-slate-800/60 rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Activity className="w-5 h-5 text-slate-500" />
            <div>
              <div className="text-xs font-medium text-slate-400">Backend API</div>
              <div className="text-xs text-slate-500 font-mono">{API_BASE_URL}/health</div>
            </div>
          </div>

          <div>
            {loading ? (
              <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                Checking...
              </span>
            ) : status === 'ok' ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <CheckCircle2 className="w-3.5 h-3.5" />
                ONLINE
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                <XCircle className="w-3.5 h-3.5" />
                OFFLINE
              </span>
            )}
          </div>
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs font-mono">
            {error}
          </div>
        )}

        <div className="mt-6 text-center text-xs text-slate-500">
          Backend: FastAPI + SQLAlchemy • Frontend: React + Vite + Tailwind v4
        </div>
      </div>
    </div>
  );
}

export default App;
