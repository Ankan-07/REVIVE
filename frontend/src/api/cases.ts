import { apiFetch } from './client';

export interface RevenueRiskCaseRead {
  id: string;
  payment_id?: string | null;
  customer_id: string;
  case_type: string;
  amount_at_risk: number;
  priority: string;
  risk_score: number;
  status: string;
  net_recovered_amount: number;
  diagnosis_json?: any;
  details?: any;
  current_action?: string;
  attempt_count: number;
  created_at: string;
  updated_at: string;
}

export interface TimelineEntry {
  event_type: string;
  actor: string;
  payload: any;
  created_at: string;
}

export interface RunAgentResponse {
  case_id: string;
  status: string;
  diagnosis?: any;
  chosen_action?: string;
  expected_net?: number;
  recovered: boolean;
  outcome_type?: string;
  net_recovered: number;
  timeline: TimelineEntry[];
}

export interface JobDetail {
  id: string;
  job_type: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  case_id?: string | null;
  payload_json?: any;
  result_json?: any;
  error_message?: string | null;
  traceback?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export function getCase(caseId: string): Promise<RevenueRiskCaseRead> {
  return apiFetch(`/cases/${caseId}`, undefined, 'Failed to fetch case');
}

export function listCases(skip: number = 0, limit: number = 100): Promise<RevenueRiskCaseRead[]> {
  return apiFetch(`/cases?skip=${skip}&limit=${limit}`, undefined, 'Failed to list cases');
}

export function getCaseAudit(caseId: string): Promise<TimelineEntry[]> {
  return apiFetch(`/cases/${caseId}/audit`, undefined, 'Failed to fetch case audit');
}

export function getJob(jobId: string): Promise<JobDetail> {
  return apiFetch(`/jobs/${jobId}`, undefined, 'Failed to fetch job status');
}

export async function runAgent(caseId: string): Promise<RunAgentResponse | JobDetail> {
  const res = await apiFetch<any>(`/cases/${caseId}/run-agent`, { method: 'POST' }, 'Failed to run agent');
  if (res && res.job_id) {
    // Poll the background worker job status until terminal state (COMPLETED / FAILED)
    const maxPolls = 60; // Up to 90 seconds (60 * 1.5s)
    for (let i = 0; i < maxPolls; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const job = await getJob(res.job_id);
      if (job.status === 'COMPLETED' || job.status === 'FAILED') {
        if (job.status === 'FAILED') {
          throw new Error(job.error_message || 'Background agent run failed');
        }
        return job;
      }
    }
    throw new Error('Agent execution timed out in background worker');
  }
  return res as RunAgentResponse;
}
