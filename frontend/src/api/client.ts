export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface HealthResponse {
  status: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`);
  if (!res.ok) {
    throw new Error(`Health check failed with status ${res.status}`);
  }
  return res.json();
}
