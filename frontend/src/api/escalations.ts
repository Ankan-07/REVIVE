import { API_BASE_URL } from './client';

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
  // We can fetch case details (amount, customer, etc.) if they were joined, 
  // but let's assume we just have what the schema provides. We might need case_id to fetch case info.
}

export async function getPendingEscalations(): Promise<EscalationRead[]> {
  const res = await fetch(`${API_BASE_URL}/escalations`);
  if (!res.ok) {
    throw new Error(`Failed to fetch escalations: ${res.status}`);
  }
  return res.json();
}

export async function assignEscalation(id: string, owner_id: string): Promise<EscalationRead> {
  const res = await fetch(`${API_BASE_URL}/escalations/${id}/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner_id }),
  });
  if (!res.ok) {
    throw new Error(`Failed to assign escalation: ${res.status}`);
  }
  return res.json();
}

export async function resolveEscalation(id: string, resolution_status: string, notes: string): Promise<EscalationRead> {
  const res = await fetch(`${API_BASE_URL}/escalations/${id}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resolution_status, notes }),
  });
  if (!res.ok) {
    throw new Error(`Failed to resolve escalation: ${res.status}`);
  }
  return res.json();
}
