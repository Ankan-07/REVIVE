import React, { useEffect, useState } from 'react';
import { ShieldAlert, User, DollarSign, Activity, ChevronRight, Check, X, Clock, PlayCircle } from 'lucide-react';
import { getPendingEscalations, assignEscalation, resolveEscalation, EscalationRead } from '../api/escalations';
import { getCase, RevenueRiskCaseRead } from '../api/cases';

interface EnrichedEscalation extends EscalationRead {
  caseDetails?: RevenueRiskCaseRead;
}

export function EscalationQueue() {
  const [escalations, setEscalations] = useState<EnrichedEscalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchQueue = async () => {
    setLoading(true);
    try {
      const escData = await getPendingEscalations();
      
      // Filter out resolved
      const pending = escData.filter(e => e.status === 'OPEN' || e.status === 'IN_PROGRESS');

      // Fetch case details for each
      const enriched = await Promise.all(pending.map(async (esc) => {
        try {
          const caseDetails = await getCase(esc.case_id);
          return { ...esc, caseDetails };
        } catch (e) {
          return esc; // fallback if case fetch fails
        }
      }));

      setEscalations(enriched);
    } catch (err: any) {
      setError(err.message || 'Failed to load queue');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, []);

  const handleAssign = async (id: string) => {
    setActionLoading(id);
    try {
      await assignEscalation(id, 'CurrentOperator'); // mocked user
      await fetchQueue();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(null);
    }
  };

  const handleResolve = async (id: string, status: 'APPROVED' | 'REJECTED') => {
    setActionLoading(id);
    try {
      await resolveEscalation(id, status, `Operator marked as ${status}`);
      await fetchQueue();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && escalations.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Clock className="animate-spin w-5 h-5 mr-2" /> Loading Queue...
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-rose-500" />
            Escalation Queue
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Cases requiring manual operator review before proceeding.
          </p>
        </div>
        <button 
          onClick={fetchQueue}
          className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-medium transition flex items-center gap-2"
        >
          <Clock className="w-4 h-4" /> Refresh
        </button>
      </div>

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-4 rounded-xl text-sm">
          {error}
        </div>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-2xl">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-950/50 text-slate-400 text-xs uppercase tracking-wider">
              <th className="p-4 font-medium">Case & Priority</th>
              <th className="p-4 font-medium">Customer</th>
              <th className="p-4 font-medium">Amount</th>
              <th className="p-4 font-medium">Reason</th>
              <th className="p-4 font-medium">Recommended Action</th>
              <th className="p-4 font-medium text-right">Operator Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {escalations.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-8 text-center text-slate-500 text-sm">
                  No pending escalations found in the queue.
                </td>
              </tr>
            ) : escalations.map((esc) => (
              <tr key={esc.id} className="hover:bg-slate-800/30 transition group">
                <td className="p-4">
                  <div className="flex flex-col">
                    <span className="font-mono text-slate-200 text-sm">{esc.case_id}</span>
                    <span className={`text-xs font-semibold uppercase mt-1 ${
                      esc.priority === 'HIGH' ? 'text-rose-400' : 'text-amber-400'
                    }`}>
                      {esc.priority}
                    </span>
                  </div>
                </td>
                <td className="p-4">
                  <div className="flex items-center gap-2 text-slate-300">
                    <User className="w-4 h-4 text-slate-500" />
                    <span className="text-sm font-medium">{esc.caseDetails?.customer_id || 'Unknown'}</span>
                  </div>
                </td>
                <td className="p-4">
                  <div className="flex items-center gap-1 text-slate-200 font-medium">
                    <DollarSign className="w-4 h-4 text-emerald-500" />
                    {esc.caseDetails?.amount_at_risk?.toLocaleString() || '---'}
                  </div>
                </td>
                <td className="p-4">
                  <div className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20 whitespace-nowrap">
                    {esc.reason.replace(/_/g, ' ')}
                  </div>
                </td>
                <td className="p-4">
                  <div className="flex items-center gap-2">
                    <PlayCircle className="w-4 h-4 text-indigo-400" />
                    <span className="text-sm text-indigo-300 font-medium">
                      {esc.recommended_action?.replace(/_/g, ' ') || 'None'}
                    </span>
                  </div>
                </td>
                <td className="p-4 text-right">
                  {esc.status === 'OPEN' && !esc.owner_id ? (
                    <button
                      onClick={() => handleAssign(esc.id)}
                      disabled={actionLoading === esc.id}
                      className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold rounded-lg shadow-lg shadow-indigo-900/20 transition"
                    >
                      {actionLoading === esc.id ? 'Assigning...' : 'Assign to Me'}
                    </button>
                  ) : (
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => handleResolve(esc.id, 'APPROVED')}
                        disabled={actionLoading === esc.id}
                        className="p-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 text-emerald-400 border border-emerald-500/20 rounded-lg transition"
                        title="Approve & Resume"
                      >
                        <Check className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleResolve(esc.id, 'REJECTED')}
                        disabled={actionLoading === esc.id}
                        className="p-1.5 bg-rose-500/10 hover:bg-rose-500/20 disabled:opacity-50 text-rose-400 border border-rose-500/20 rounded-lg transition"
                        title="Reject"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
