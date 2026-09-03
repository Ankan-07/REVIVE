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

export function getCase(caseId: string): Promise<RevenueRiskCaseRead> {
  return apiFetch(`/cases/${caseId}`, undefined, 'Failed to fetch case');
}

export function listCases(skip: number = 0, limit: number = 100): Promise<RevenueRiskCaseRead[]> {
  return apiFetch(`/cases?skip=${skip}&limit=${limit}`, undefined, 'Failed to list cases');
}

export function getCaseAudit(caseId: string): Promise<TimelineEntry[]> {
  return apiFetch(`/cases/${caseId}/audit`, undefined, 'Failed to fetch case audit');
}

export function runAgent(caseId: string): Promise<RunAgentResponse> {
  return apiFetch(`/cases/${caseId}/run-agent`, { method: 'POST' }, 'Failed to run agent');
}
