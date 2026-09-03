import { API_BASE_URL } from './client';

export interface RevenueRiskCaseRead {
  id: string;
  customer_id: string;
  case_type: string;
  amount_at_risk: number;
  priority: string;
  risk_score: number;
  status: string;
  net_recovered_amount: number;
  diagnosis_json?: any;
  current_action?: string;
  attempt_count: number;
  created_at: string;
  updated_at: string;
}

export async function getCase(caseId: string): Promise<RevenueRiskCaseRead> {
  const res = await fetch(`${API_BASE_URL}/cases/${caseId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch case: ${res.status}`);
  }
  return res.json();
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

export async function listCases(skip: number = 0, limit: number = 100): Promise<RevenueRiskCaseRead[]> {
  const res = await fetch(`${API_BASE_URL}/cases?skip=${skip}&limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to list cases: ${res.status}`);
  return res.json();
}

export async function getCaseAudit(caseId: string): Promise<TimelineEntry[]> {
  const res = await fetch(`${API_BASE_URL}/cases/${caseId}/audit`);
  if (!res.ok) throw new Error(`Failed to fetch case audit: ${res.status}`);
  return res.json();
}

export async function runAgent(caseId: string): Promise<RunAgentResponse> {
  const res = await fetch(`${API_BASE_URL}/cases/${caseId}/run-agent`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to run agent: ${res.status}`);
  return res.json();
}
