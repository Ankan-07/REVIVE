import React from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCase, getCaseAudit, runAgent } from '../api/cases';
import { Timeline } from '../components/Timeline';
import { ArrowLeft, Play, ShieldAlert, CheckCircle2 } from 'lucide-react';
import { cn } from '../lib/utils';

export function CaseDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: caseData, isLoading: loadingCase } = useQuery({
    queryKey: ['case', id],
    queryFn: () => getCase(id!),
    enabled: !!id
  });

  const { data: auditData, isLoading: loadingAudit } = useQuery({
    queryKey: ['caseAudit', id],
    queryFn: () => getCaseAudit(id!),
    enabled: !!id,
    refetchInterval: caseData?.status === 'WAITING_FOR_OUTCOME' ? 3000 : false
  });

  const { mutate: handleRunAgent, isPending: isRunning } = useMutation({
    mutationFn: () => runAgent(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', id] });
      queryClient.invalidateQueries({ queryKey: ['caseAudit', id] });
    }
  });

  if (loadingCase) {
    return <div className="p-6 text-center text-slate-500 animate-pulse">Loading case...</div>;
  }

  if (!caseData) {
    return <div className="p-6 text-center text-rose-400">Case not found.</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/" className="p-2 bg-slate-900 border border-slate-800 rounded-lg text-slate-400 hover:text-white transition">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-3">
            Case {caseData.id}
            <span className={cn(
              "px-2.5 py-1 rounded-md text-xs font-semibold border",
              caseData.status === 'RECOVERED' ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : 
              caseData.status === 'DETECTED' ? "bg-amber-500/10 text-amber-400 border-amber-500/20" : 
              caseData.status === 'ESCALATED' ? "bg-rose-500/10 text-rose-400 border-rose-500/20" : 
              "bg-slate-500/10 text-slate-400 border-slate-500/20"
            )}>
              {caseData.status}
            </span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">Created at {new Date(caseData.created_at).toLocaleString()}</p>
        </div>
        <div className="ml-auto">
          <button
            onClick={() => handleRunAgent()}
            disabled={isRunning || caseData.status === 'RECOVERED' || caseData.status === 'CLOSED_NO_RECOVERY'}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:hover:bg-indigo-600 text-white text-sm font-semibold rounded-lg transition shadow-lg"
          >
            {isRunning ? (
              <span className="flex items-center gap-2 animate-pulse"><Play className="w-4 h-4" /> Running Agent...</span>
            ) : (
              <><Play className="w-4 h-4 fill-current" /> Run Revenue Rescue</>
            )}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* Summary Panel */}
          <div className="bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6 shadow-xl">
            <h3 className="text-lg font-bold text-slate-100 mb-4 border-b border-slate-800 pb-4">Case Summary</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">Customer ID</p>
                <p className="font-mono text-sm text-slate-200">{caseData.customer_id}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">Type</p>
                <p className="text-sm text-slate-200">{caseData.case_type}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">Amount at Risk</p>
                <p className="text-sm font-bold text-rose-400">₹{caseData.amount_at_risk.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">Net Recovered</p>
                <p className="text-sm font-bold text-emerald-400">₹{caseData.net_recovered_amount?.toLocaleString() || 0}</p>
              </div>
            </div>
          </div>

          {/* AI Diagnosis */}
          {caseData.diagnosis_json && (
            <div className="bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6 shadow-xl">
              <h3 className="text-lg font-bold text-slate-100 mb-4 border-b border-slate-800 pb-4 flex items-center gap-2">
                <ShieldAlert className="w-5 h-5 text-indigo-400" /> AI Diagnosis
              </h3>
              <div className="bg-slate-950 border border-slate-800 rounded-md p-4 overflow-x-auto">
                <pre className="text-xs text-slate-300 font-mono m-0">
                  {JSON.stringify(caseData.diagnosis_json, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Recommended Action / Policy */}
          {caseData.current_action && (
            <div className="bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6 shadow-xl">
              <h3 className="text-lg font-bold text-slate-100 mb-4 border-b border-slate-800 pb-4 flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-400" /> Current Action
              </h3>
              <div className="p-4 bg-indigo-500/10 border border-indigo-500/20 rounded-md">
                <p className="font-mono text-sm text-indigo-300">{caseData.current_action}</p>
                <p className="text-xs text-slate-400 mt-2">Attempt Count: {caseData.attempt_count}</p>
              </div>
            </div>
          )}
        </div>

        <div className="lg:col-span-1">
          {/* Audit Trail */}
          <div className="bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6 shadow-xl h-full">
            <h3 className="text-lg font-bold text-slate-100 mb-6 border-b border-slate-800 pb-4">Audit Timeline</h3>
            {loadingAudit ? (
              <div className="text-sm text-slate-500 animate-pulse">Loading timeline...</div>
            ) : (
              <Timeline entries={auditData || []} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
