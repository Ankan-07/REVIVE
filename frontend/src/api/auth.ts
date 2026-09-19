import { apiFetch, jsonPost, setAuthToken } from './client';

export interface SessionResponse {
  authenticated: boolean;
  name: string;
  scopes: string[];
  expires_in_seconds: number;
  token?: string;
}

export interface UserProfileResponse {
  key_id: string;
  name: string;
  scopes: string[];
  is_session: boolean;
}

/** Exchange raw API key for a session token and httpOnly cookie (Phase A2.5). */
export async function loginWithApiKey(apiKey: string): Promise<SessionResponse> {
  const res = await apiFetch<SessionResponse>('/auth/session', jsonPost({ api_key: apiKey }), 'Session login');
  if (res.token) {
    setAuthToken(res.token);
  } else {
    setAuthToken(apiKey);
  }
  return res;
}

/** Fetch profile of currently authenticated operator. */
export async function fetchCurrentUser(): Promise<UserProfileResponse> {
  return apiFetch<UserProfileResponse>('/auth/me', undefined, 'Current user profile');
}

/** Logout and clear session cookie and stored token. */
export async function logoutSession(): Promise<{ status: string }> {
  try {
    return await apiFetch<{ status: string }>('/auth/logout', { method: 'POST' }, 'Session logout');
  } finally {
    setAuthToken(null);
  }
}
