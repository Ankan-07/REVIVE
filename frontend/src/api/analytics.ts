import { apiFetch } from './client';

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

export interface RecoveryTotalsResponse {
  total_cases: number;
  total_amount_at_risk: number;
  total_gross_recovered: number;
  total_intervention_costs: number;
  total_discounts: number;
  total_net_recovered: number;
  recovery_rate: number;
  average_recovery_time_hours: number | null;
}

export interface InterventionStat {
  intervention_type: string;
  count: number;
  success_count: number;
  total_cost: number;
}

export interface InterventionStatsResponse {
  stats: InterventionStat[];
}

function withQuery(path: string, params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.append(key, value);
  }
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

export function fetchBaselineComparison(seed?: number): Promise<BaselineComparisonResponse> {
  const query = seed !== undefined ? `?seed=${seed}` : '';
  return apiFetch(`/analytics/baseline${query}`, undefined, 'Failed to fetch baseline comparison');
}

export function fetchRecoveryTotals(
  startDate?: string,
  endDate?: string,
  caseType?: string,
  origin?: string,
): Promise<RecoveryTotalsResponse> {
  const url = withQuery('/analytics/recovery', {
    start_date: startDate,
    end_date: endDate,
    case_type: caseType,
    origin: origin,
  });
  return apiFetch(url, undefined, 'Failed to fetch recovery totals');
}

export function fetchInterventionStats(
  startDate?: string,
  endDate?: string,
  caseType?: string,
  origin?: string,
): Promise<InterventionStatsResponse> {
  const url = withQuery('/analytics/interventions', {
    start_date: startDate,
    end_date: endDate,
    case_type: caseType,
    origin: origin,
  });
  return apiFetch(url, undefined, 'Failed to fetch intervention stats');
}
