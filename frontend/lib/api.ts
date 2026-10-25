export const base = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(base + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
    cache: 'no-store',
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: 'Backend request failed' }));
    throw new Error(error.message || 'Request failed');
  }
  return response.json();
}
