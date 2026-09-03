import React from 'react';
import { TimelineEntry } from '../api/cases';
import { CheckCircle2, Clock, XCircle, Activity, AlertCircle, FileText } from 'lucide-react';
import { cn } from '../lib/utils';

interface TimelineProps {
  entries: TimelineEntry[];
}

export function Timeline({ entries }: TimelineProps) {
  if (!entries || entries.length === 0) {
    return <div className="text-slate-500 text-sm italic">No audit trail available.</div>;
  }

  const getEventIcon = (type: string) => {
    switch (type) {
      case 'CASE_CREATED': return <FileText className="w-4 h-4 text-indigo-400" />;
      case 'DIAGNOSIS_COMPLETED': return <Activity className="w-4 h-4 text-indigo-400" />;
      case 'EV_SCORED': return <Activity className="w-4 h-4 text-emerald-400" />;
      case 'POLICY_EVALUATED': return <ShieldIcon type={type} />;
      case 'TOOL_EXECUTED': return <Clock className="w-4 h-4 text-amber-400" />;
      case 'OUTCOME_VERIFIED': return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
      case 'CASE_CLOSED': return <CheckCircle2 className="w-4 h-4 text-slate-400" />;
      case 'ESCALATED': return <AlertCircle className="w-4 h-4 text-rose-400" />;
      default: return <div className="w-2 h-2 rounded-full bg-slate-500" />;
    }
  };

  const ShieldIcon = ({type}: {type: string}) => <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>;

  return (
    <div className="relative border-l border-slate-800 ml-3 space-y-6 pb-4">
      {entries.map((entry, idx) => (
        <div key={idx} className="relative pl-6">
          <div className="absolute -left-3.5 top-1 bg-slate-950 border border-slate-800 p-1.5 rounded-full flex items-center justify-center">
            {getEventIcon(entry.event_type)}
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-slate-200">{entry.event_type}</span>
              <span className="text-xs text-slate-500">{new Date(entry.created_at).toLocaleString()}</span>
            </div>
            <div className="text-xs text-slate-400">Actor: <span className="font-mono text-slate-300">{entry.actor}</span></div>
            {entry.payload && Object.keys(entry.payload).length > 0 && (
              <div className="mt-2 bg-slate-900 border border-slate-800 rounded-md p-3 overflow-x-auto">
                <pre className="text-[10px] text-slate-400 font-mono m-0">
                  {JSON.stringify(entry.payload, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
