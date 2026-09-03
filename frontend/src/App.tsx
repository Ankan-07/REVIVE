import React, { useEffect, useState } from 'react';
import { fetchHealth, API_BASE_URL } from './api/client';
import { Activity, CheckCircle2, XCircle, RefreshCw, ShieldCheck } from 'lucide-react';
import { EscalationQueue } from './pages/EscalationQueue';
import { Baseline } from './pages/Baseline';
import { Dashboard } from './pages/Dashboard';
import { CaseDetail } from './pages/CaseDetail';
import { Routes, Route, NavLink, Outlet } from 'react-router-dom';

function HealthPage() {
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
    <div className="max-w-md mx-auto mt-12 bg-slate-900/80 backdrop-blur border border-slate-800 rounded-2xl p-6 shadow-2xl">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4 mb-6">
        <h2 className="text-lg font-bold">System Health Dashboard</h2>
        <button
          onClick={checkHealth}
          disabled={loading}
          className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition disabled:opacity-50"
          title="Refresh Health Status"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

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
    </div>
  );
}

function Layout() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Navigation */}
      <nav className="border-b border-slate-800 bg-slate-900/50 backdrop-blur px-6 py-4 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <span className="text-lg font-bold tracking-tight text-white">Revenue Rescue Engine</span>
        </div>
        
        <div className="flex gap-2 p-1 bg-slate-900 rounded-lg border border-slate-800">
          <NavLink
            to="/"
            className={({ isActive }) => `px-4 py-1.5 rounded-md text-sm font-medium transition ${
              isActive ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Dashboard
          </NavLink>
          <NavLink
            to="/benchmark"
            className={({ isActive }) => `px-4 py-1.5 rounded-md text-sm font-medium transition ${
              isActive ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Benchmark
          </NavLink>
          <NavLink
            to="/escalations"
            className={({ isActive }) => `px-4 py-1.5 rounded-md text-sm font-medium transition ${
              isActive ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Escalations
          </NavLink>
          <NavLink
            to="/health"
            className={({ isActive }) => `px-4 py-1.5 rounded-md text-sm font-medium transition ${
              isActive ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Health
          </NavLink>
        </div>
      </nav>

      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="cases/:id" element={<CaseDetail />} />
        <Route path="benchmark" element={<Baseline />} />
        <Route path="escalations" element={<EscalationQueue />} />
        <Route path="health" element={<HealthPage />} />
      </Route>
    </Routes>
  );
}

export default App;

