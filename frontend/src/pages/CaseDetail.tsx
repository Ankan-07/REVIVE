import React from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCase, getCaseAudit, runAgent } from '../api/cases';
import { razorpayCheckoutEnabled } from '../api/checkout';
import { RazorpayCheckout } from '../components/RazorpayCheckout';
import { Timeline } from '../components/Timeline';
import { ArrowLeft, Play, ShieldAlert, CheckCircle2, AlertCircle, CreditCard } from 'lucide-react';
import { cn } from '../lib/utils';

export function CaseDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: caseData, isLoading: loadingCase, isError: isCaseError } = useQuery({
    queryKey: ['case', id],
    queryFn: () => getCase(id!),
    enabled: !!id
  });

  const { data: auditData, isLoading: loadingAudit, isError: isAuditError } = useQuery({
    queryKey: ['caseAudit', id],
    queryFn: () => getCaseAudit(id!),
    enabled: !!id,
    refetchInterval: caseData?.status === 'WAITING_FOR_OUTCOME' ? 3000 : false
  });

  const { mutate: handleRunAgent, isPending: isRunning, isError: isRunError, error: runError, reset: resetRunError } = useMutation({
    mutationFn: () => runAgent(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', id] });
      queryClient.invalidateQueries({ queryKey: ['caseAudit', id] });
    }
  });

  if (loadingCase) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 bg-slate-800 rounded-lg"></div>
          <div>
            <div className="h-6 w-32 bg-slate-800 rounded mb-2"></div>
            <div className="h-4 w-48 bg-slate-800 rounded"></div>
          </div>
          <div className="ml-auto w-40 h-10 bg-slate-800 rounded-lg"></div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 h-48"></div>
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 h-32"></div>
          </div>
          <div className="lg:col-span-1">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 h-[500px]"></div>
          </div>
        </div>
      </div>
    );
  }

  if (isCaseError || !caseData) {
    return (
      <div className="p-12 text-center flex flex-col items-center justify-center">
        <AlertCircle className="w-12 h-12 text-rose-500 mb-4" />
        <h2 className="text-xl font-bold text-slate-100 mb-2">Case Not Found</h2>
        <p className="text-slate-400 mb-6">We couldn't load the details for this case. It might not exist or the server is unreachable.</p>
        <Link to="/" className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition">
          Return to Dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {isRunError && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-4 rounded-xl flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <AlertCircle className="w-5 h-5" />
            Failed to run agent: {runError instanceof Error ? runError.message : 'Unknown error'}
          </div>
          <button onClick={() => resetRunError()} className="text-rose-400 hover:text-rose-300 font-medium text-sm">Dismiss</button>
        </div>
      )}

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

          {/* Real Payment Collection (Razorpay Standard Checkout, test mode) */}
          {razorpayCheckoutEnabled &&
            caseData.case_type === 'FAILED_PAYMENT' &&
            caseData.payment_id &&
            !['RECOVERED', 'CLOSED_NO_RECOVERY', 'EXPIRED'].includes(caseData.status) && (
              <div className="bg-slate-900/80 backdrop-blur border border-indigo-500/20 rounded-xl p-6 shadow-xl">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-4">
                  <div>
                    <h3 className="text-lg font-bold text-slate-100 flex items-center gap-2">
                      <CreditCard className="w-5 h-5 text-indigo-400" /> Collect Payment
                    </h3>
                    <p className="text-xs text-slate-500 mt-1">
                      Real Razorpay Standard Checkout · test mode · payment {caseData.payment_id}
                    </p>
                  </div>
                </div>
                <RazorpayCheckout
                  paymentId={caseData.payment_id}
                  amountInr={caseData.amount_at_risk}
                  onVerified={() => {
                    queryClient.invalidateQueries({ queryKey: ['case', id] });
                    queryClient.invalidateQueries({ queryKey: ['caseAudit', id] });
                  }}
                />
              </div>
            )}

          {/* Checkout Cart Contents */}
          {caseData.case_type === 'ABANDONED_CHECKOUT' && caseData.details && (
            <div className="bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6 shadow-xl">
              <h3 className="text-lg font-bold text-slate-100 mb-4 border-b border-slate-800 pb-4">Cart Contents</h3>
              <div className="space-y-3">
                {caseData.details.items?.map((item: any, i: number) => (
                  <div key={i} className="flex justify-between items-center text-sm">
                    <span className="text-slate-300">{item.product_name} (x{item.quantity})</span>
                    <span className="text-slate-200 font-medium">₹{item.price}</span>
                  </div>
                ))}
                <div className="pt-3 mt-3 border-t border-slate-800 flex justify-between items-center text-sm font-bold">
                  <span className="text-slate-400">Total Cart Value</span>
                  <span className="text-rose-400">₹{caseData.details.cart_value}</span>
                </div>
              </div>
            </div>
          )}

          {/* Invoice & Promise Details */}
          {caseData.case_type === 'OVERDUE_INVOICE' && caseData.details && (
            <div className="bg-slate-900/80 backdrop-blur border border-slate-800 rounded-xl p-6 shadow-xl">
              <h3 className="text-lg font-bold text-slate-100 mb-4 border-b border-slate-800 pb-4">Invoice Details</h3>
              <div className="grid grid-cols-2 gap-6 text-sm">
                <div>
                  <p className="text-xs font-medium text-slate-500 mb-1">Due Date</p>
                  <p className="text-slate-200">{new Date(caseData.details.due_date).toLocaleDateString()}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-slate-500 mb-1">Invoice Amount</p>
                  <p className="font-bold text-slate-200">₹{caseData.details.amount}</p>
                </div>
                {caseData.details.promised_date && (
                  <>
                    <div>
                      <p className="text-xs font-medium text-slate-500 mb-1">Promised Date</p>
                      <p className="text-indigo-300 font-medium">{new Date(caseData.details.promised_date).toLocaleDateString()}</p>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-slate-500 mb-1">Promise Status</p>
                      <span className={cn(
                        "px-2 py-0.5 rounded text-xs font-bold border",
                        caseData.details.promise_status === 'BROKEN' ? "bg-rose-500/10 text-rose-400 border-rose-500/20" :
                        caseData.details.promise_status === 'KEPT' ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                        "bg-amber-500/10 text-amber-400 border-amber-500/20"
                      )}>
                        {caseData.details.promise_status}
                      </span>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

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
            {isAuditError ? (
               <div className="text-sm text-rose-400 flex items-center gap-2">
                 <AlertCircle className="w-4 h-4" /> Failed to load timeline
               </div>
            ) : loadingAudit ? (
              <div className="space-y-4 animate-pulse">
                {[1, 2, 3].map(i => (
                  <div key={i} className="flex gap-4">
                    <div className="w-2 h-2 rounded-full bg-slate-800 mt-1.5"></div>
                    <div className="flex-1">
                      <div className="h-4 w-24 bg-slate-800 rounded mb-2"></div>
                      <div className="h-3 w-16 bg-slate-800 rounded"></div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Timeline entries={auditData || []} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
