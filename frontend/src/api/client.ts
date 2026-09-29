/**
 * Typed API client.
 *
 * Two things worth noting:
 *
 * 1. The base URL is read at RUNTIME from window.__CIVICPULSE_CONFIG__, which
 *    /config.js sets when the container starts. It is never read from
 *    import.meta.env, because Vite bakes those into the bundle at build time
 *    and an image with a baked-in backend URL is environment-specific --
 *    build-once-deploy-many is gone. The default is '' (same origin), so nginx
 *    proxies /api and the client needs no absolute URL at all.
 *
 * 2. Errors keep the server's body. A 409 must reach the UI with the server's
 *    own message, not a generic "error".
 */

import type {
  Complaint,
  ReadyState,
  ComplaintFilters,
  ComplaintPage,
  ErrorBody,
  ProvidersInfo,
  Stats,
  StatsResponse,
  Status,
} from './types'

declare global {
  interface Window {
    __CIVICPULSE_CONFIG__?: { apiBaseUrl?: string }
  }
}

export function apiBaseUrl(): string {
  const configured = window.__CIVICPULSE_CONFIG__?.apiBaseUrl
  // Trailing slash would produce //api on join, which some proxies 404.
  return (configured ?? '').replace(/\/$/, '')
}

/** An API error that still carries the server's body, so the UI can show it. */
export class ApiError extends Error {
  readonly status: number
  readonly body: ErrorBody

  constructor(status: number, body: ErrorBody) {
    super(body.detail || body.error || `Request failed with ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }

  /** Field-level messages keyed by field name, for inline form errors. */
  fieldErrors(): Record<string, string> {
    const result: Record<string, string> = {}
    for (const f of this.body.fields ?? []) result[f.field] = f.message
    return result
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<{ data: T; response: Response }> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    // A network failure is not an API error and must not be rendered as one.
    // The underlying TypeError says nothing a citizen can act on.
    throw new ApiError(0, {
      error: 'network_error',
      detail: 'Could not reach the server. Check your connection and try again.',
    })
  }

  if (!response.ok) {
    let body: ErrorBody
    try {
      body = (await response.json()) as ErrorBody
    } catch {
      body = { error: 'unexpected', detail: `Server returned ${response.status}.` }
    }
    throw new ApiError(response.status, body)
  }

  const data = (await response.json()) as T
  return { data, response }
}

export async function submitComplaint(payload: {
  text: string
  location: string
  reporter_contact?: string
}): Promise<Complaint> {
  const body: Record<string, unknown> = {
    text: payload.text,
    location: payload.location,
  }
  // Send the key only when there is a value: the server forbids extra fields
  // and treats an empty string differently from an absent one.
  if (payload.reporter_contact) body.reporter_contact = payload.reporter_contact

  const { data } = await request<Complaint>('/api/complaints', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return data
}

export async function listComplaints(filters: ComplaintFilters = {}): Promise<ComplaintPage> {
  const params = new URLSearchParams()
  if (filters.category) params.set('category', filters.category)
  if (filters.priority) params.set('priority', filters.priority)
  if (filters.status) params.set('status', filters.status)
  params.set('page', String(filters.page ?? 1))
  params.set('page_size', String(filters.page_size ?? 10))

  const { data } = await request<ComplaintPage>(`/api/complaints?${params.toString()}`)
  return data
}

export async function getComplaint(id: string): Promise<Complaint> {
  const { data } = await request<Complaint>(`/api/complaints/${id}`)
  return data
}

export async function updateStatus(id: string, status: Status): Promise<Complaint> {
  const { data } = await request<Complaint>(`/api/complaints/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
  return data
}

export async function getStats(): Promise<StatsResponse> {
  const { data, response } = await request<Stats>('/api/stats')
  // Showing our own cache behaviour in the UI is unusual, and it is exactly
  // the thing that makes the caching claim demonstrable rather than asserted.
  return { stats: data, cacheHit: response.headers.get('X-Cache') === 'HIT' }
}

export async function getProviders(): Promise<ProvidersInfo> {
  const { data } = await request<ProvidersInfo>('/api/meta/providers')
  return data
}

/**
 * Readiness, for the header indicator.
 *
 * Deliberately does NOT go through request(): a 503 from /ready is a real
 * answer carrying which dependency failed, not an error to throw away. The
 * header shows "degraded" and names it rather than going blank.
 */
export async function getReady(): Promise<ReadyState> {
  try {
    const response = await fetch(`${apiBaseUrl()}/ready`, {
      headers: { Accept: 'application/json' },
    })
    const body = (await response.json()) as { status: string; dependencies: Record<string, string> }
    return {
      ok: response.ok,
      status: body.status,
      dependencies: body.dependencies ?? {},
    }
  } catch {
    return { ok: false, status: 'unreachable', dependencies: {} }
  }
}
