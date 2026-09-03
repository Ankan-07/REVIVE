import { API_BASE_URL } from './client';

export interface BaselineMetrics {
  gross_recovered: number;
  net_recovered: number;
  recovery_rate: number;
  escalation_rate: number;
}

export interface BaselineComparisonResponse {
  simulation_run_id: string;
  seed: number;
  baseline: BaselineMetrics;
  revive: BaselineMetrics;
  delta_net: number;
  delta_escalation_rate: number;
}

export async function fetchBaselineComparison(seed?: number): Promise<BaselineComparisonResponse> {
  let url = `${API_BASE_URL}/analytics/baseline`;
  if (seed !== undefined) {
    url += `?seed=${seed}`;
  }
  
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch baseline comparison: ${res.statusText}`);
  }
  return res.json();
}

export interface RecoveryTotalsResponse {
  total_cases: number;
  total_amount_at_risk: number;
  total_recovered_amount: number;
  total_intervention_cost: number;
  total_discount_amount: number;
  net_recovered: number;
  recovery_rate: number;
  average_recovery_time_hours?: number;
}

export interface InterventionStats {
  action: string;
  count: number;
  success_count: number;
  total_cost: number;
  total_recovered: number;
}

export interface InterventionStatsResponse {
  stats: InterventionStats[];
}

export async function fetchRecoveryTotals(startDate?: string, endDate?: string, caseType?: string): Promise<RecoveryTotalsResponse> {
  const params = new URLSearchParams();
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  if (caseType) params.append('case_type', caseType);
  const qs = params.toString();
  const url = `${API_BASE_URL}/analytics/recovery${qs ? `?${qs}` : ''}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch recovery totals: ${res.statusText}`);
  return res.json();
}

export async function fetchInterventionStats(startDate?: string, endDate?: string, caseType?: string): Promise<InterventionStatsResponse> {
  const params = new URLSearchParams();
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  if (caseType) params.append('case_type', caseType);
  const qs = params.toString();
  const url = `${API_BASE_URL}/analytics/interventions${qs ? `?${qs}` : ''}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch intervention stats: ${res.statusText}`);
  return res.json();
}
