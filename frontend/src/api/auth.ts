import { apiFetch, jsonPost } from './client';

export interface SessionResponse {
  authenticated: boolean;
  name: string;
  scopes: string[];
  expires_in_seconds: number;
}

export interface UserProfileResponse {
  key_id: string;
  name: string;
  scopes: string[];
  is_session: boolean;
}

/** Exchange raw API key for an httpOnly session cookie (Phase A2.5). */
export async function loginWithApiKey(apiKey: string): Promise<SessionResponse> {
  return apiFetch<SessionResponse>('/auth/session', jsonPost({ api_key: apiKey }), 'Session login');
}

/** Fetch profile of currently authenticated operator. */
export async function fetchCurrentUser(): Promise<UserProfileResponse> {
  return apiFetch<UserProfileResponse>('/auth/me', undefined, 'Current user profile');
}

/** Logout and clear session cookie. */
export async function logoutSession(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>('/auth/logout', { method: 'POST' }, 'Session logout');
}
