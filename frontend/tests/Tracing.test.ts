import { trace } from '@opentelemetry/api'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { startTracing } from '../src/tracing'
import { jsonResponse } from './setup'

function headerOf(init: RequestInit | undefined, name: string): string | null {
  return new Headers(init?.headers).get(name)
}

describe('browser tracing', () => {
  afterEach(() => {
    trace.disable()
  })

  it('attaches a W3C traceparent to same-origin API calls, so the backend continues the trace', async () => {
    const underlying = vi.fn().mockResolvedValue(jsonResponse({ total: 0 }))
    vi.stubGlobal('fetch', underlying)

    const provider = startTracing({ exporterUrl: '/otel/v1/traces' })
    try {
      await window.fetch('/api/stats')

      const [, init] = underlying.mock.calls[0] as [RequestInfo, RequestInit | undefined]
      const traceparent = headerOf(init, 'traceparent')
      // version-traceid-spanid-flags, sampled
      expect(traceparent).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/)
    } finally {
      await provider.shutdown()
      vi.unstubAllGlobals()
    }
  })

  it('does not propagate trace context to other origins it was not told about', async () => {
    const underlying = vi.fn().mockResolvedValue(jsonResponse({}))
    vi.stubGlobal('fetch', underlying)

    const provider = startTracing({ exporterUrl: '/otel/v1/traces' })
    try {
      await window.fetch('https://third-party.example/pixel')
      const [, init] = underlying.mock.calls[0] as [RequestInfo, RequestInit | undefined]
      expect(headerOf(init, 'traceparent')).toBeNull()
    } finally {
      await provider.shutdown()
      vi.unstubAllGlobals()
    }
  })
})
