import '@testing-library/jest-dom/vitest'

import { afterEach, beforeEach, vi } from 'vitest'

// jsdom does not implement scrolling; the router calls it on navigation.
window.scrollTo = () => {}

beforeEach(() => {
  // Same-origin by default, which is how the container actually runs: nginx
  // proxies /api, so the client needs no absolute URL.
  window.__CIVICPULSE_CONFIG__ = { apiBaseUrl: '' }
})

afterEach(() => {
  vi.restoreAllMocks()
})

/** Build a fetch stub that returns this body, with optional headers. */
export function jsonResponse(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  })
}
