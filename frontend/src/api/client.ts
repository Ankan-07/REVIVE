export const API_BASE_URL = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '/api' : 'http://localhost:8000');

export interface HealthResponse {
  status: string;
}

const TOKEN_STORAGE_KEY = 'revive_auth_token';

export function getAuthToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null): void {
  try {
    if (token) {
      sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // sessionStorage unavailable
  }
}

/** Shared JSON fetch against the API base URL, with a human-readable error on non-2xx. */
export async function apiFetch<T>(path: string, init?: RequestInit, label?: string): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getAuthToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const options: RequestInit = {
    credentials: 'include',
    ...init,
    headers,
  };
  const res = await fetch(`${API_BASE_URL}${path}`, options);
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
