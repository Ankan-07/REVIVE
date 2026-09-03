import { apiFetch, jsonPost } from './client';

export interface EscalationRead {
  id: string;
  case_id: string;
  status: string;
  reason: string;
  priority: string;
  notes?: string;
  owner_id?: string;
  recommended_action?: string;
  created_at: string;
  resolved_at?: string;
  // Case details (amount, customer, etc.) are fetched separately per escalation in the queue UI.
}

export function getPendingEscalations(): Promise<EscalationRead[]> {
  return apiFetch('/escalations', undefined, 'Failed to fetch escalations');
}

export function assignEscalation(id: string, owner_id: string): Promise<EscalationRead> {
  return apiFetch(`/escalations/${id}/assign`, jsonPost({ owner_id }), 'Failed to assign escalation');
}

export function resolveEscalation(
  id: string,
  resolution_status: string,
  notes: string,
): Promise<EscalationRead> {
  return apiFetch(
    `/escalations/${id}/resolve`,
    jsonPost({ resolution_status, notes }),
    'Failed to resolve escalation',
  );
}
