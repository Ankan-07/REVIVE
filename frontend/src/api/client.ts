export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface HealthResponse {
  status: string;
}

/** Shared JSON fetch against the API base URL, with a human-readable error on non-2xx. */
export async function apiFetch<T>(path: string, init?: RequestInit, label?: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  if (!res.ok) {
    throw new Error(`${label || `Request to ${path}`} failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** RequestInit for POSTing a JSON body (used by every mutating endpoint). */
export function jsonPost(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

export async function fetchHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health', undefined, 'Health check');
}
