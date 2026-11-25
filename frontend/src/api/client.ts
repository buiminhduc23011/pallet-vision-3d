import type { JobTicket } from './types';

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (init.method === 'POST' && !(init.body instanceof FormData))
    headers.set('Idempotency-Key', crypto.randomUUID());
  const response = await fetch(path.startsWith('/api/') ? path : `/api/v1${path}`, { ...init, headers });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      data?.error?.code ?? 'REQUEST_FAILED',
      data?.error?.message ?? `Server returned ${response.status}`,
      response.status,
    );
  }
  return data as T;
}

export async function awaitJob<T>(ticket: JobTicket, signal?: AbortSignal): Promise<T> {
  // A slow CPU model may legitimately take minutes; cancellation stops UI polling, not the pinned job.
  for (;;) {
    if (signal?.aborted) throw new DOMException('Operation cancelled', 'AbortError');
    const job = await api<{ status: string; result: T; error: { code: string; message: string } | null }>(
      ticket.status_url,
      { signal },
    );
    if (job.status === 'succeeded') return job.result;
    if (job.status === 'failed')
      throw new ApiError(job.error?.code ?? 'JOB_FAILED', job.error?.message ?? 'Processing failed', 422);
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
}

export function post<T>(path: string, body: unknown) {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body) });
}
