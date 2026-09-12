import React, { useEffect, useState } from 'react';
import { fetchHealth, API_BASE_URL } from './api/client';
import { fetchCurrentUser, loginWithApiKey, logoutSession, UserProfileResponse } from './api/auth';
import { Activity, CheckCircle2, XCircle, RefreshCw, ShieldCheck, Key, LogOut, UserCheck, AlertCircle } from 'lucide-react';
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

const DEV_API_KEY = "rve_f310e2f4_rhxJTY51fGUDifUwb3WVEPPFMy4l3NCcx6rDYdyhkcE";

function Layout() {
  const [user, setUser] = useState<UserProfileResponse | null>(null);
  const [showAuthModal, setShowAuthModal] = useState<boolean>(false);
  const [apiKeyInput, setApiKeyInput] = useState<string>('');
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState<boolean>(false);

  useEffect(() => {
    fetchCurrentUser()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  const handleLogin = async (key: string) => {
    setAuthLoading(true);
    setAuthError(null);
    try {
      await loginWithApiKey(key.trim());
      setShowAuthModal(false);
      window.location.reload();
    } catch (err: any) {
      setAuthError(err.message || 'Authentication failed. Please verify your API key.');
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await logoutSession();
      setUser(null);
      window.location.reload();
    } catch (err) {
      console.error(err);
    }
  };

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
        
        <div className="flex items-center gap-4">
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

          {/* Auth Status & Login Trigger */}
          {user ? (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs">
              <UserCheck className="w-4 h-4 text-emerald-400" />
              <span className="font-semibold">{user.name}</span>
              <button
                onClick={handleLogout}
                title="Log out"
                className="ml-2 text-slate-400 hover:text-rose-400 transition"
              >
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowAuthModal(true)}
              className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow transition"
            >
              <Key className="w-3.5 h-3.5" />
              Operator Login
            </button>
          )}
        </div>
      </nav>

      {/* Auth Modal */}
      {showAuthModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-white font-bold text-base">
                <Key className="w-5 h-5 text-indigo-400" />
                Operator Authentication
              </div>
              <button
                onClick={() => setShowAuthModal(false)}
                className="text-slate-400 hover:text-slate-200 text-sm"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-400">
              Enter your REVIVE operator API key to connect your secure browser session.
            </p>

            {authError && (
              <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{authError}</span>
              </div>
            )}

            <div className="space-y-2">
              <label className="text-xs font-medium text-slate-300">API Key</label>
              <input
                type="password"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                placeholder="rve_..."
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex gap-2 pt-2">
              <button
                disabled={authLoading}
                onClick={() => handleLogin(DEV_API_KEY)}
                className="flex-1 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition"
              >
                Use Dev Key
              </button>
              <button
                disabled={authLoading || !apiKeyInput.trim()}
                onClick={() => handleLogin(apiKeyInput)}
                className="flex-1 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow transition disabled:opacity-50"
              >
                {authLoading ? 'Connecting...' : 'Connect Session'}
              </button>
            </div>
          </div>
        </div>
      )}

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

