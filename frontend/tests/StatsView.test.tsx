import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { apiBaseUrl } from '../src/api/client'
import { StatsView } from '../src/pages/StatsView'
import { jsonResponse } from './setup'

const STATS = {
  total: 36,
  by_category: {
    water: 9,
    electricity: 7,
    sanitation: 8,
    roads: 6,
    streetlights: 5,
    other: 1,
  },
  by_priority: { high: 11, normal: 19, low: 6 },
  by_status: { open: 30, in_progress: 4, resolved: 1, rejected: 1 },
  generated_at: '2026-09-20T06:30:00Z',
}

const PROVIDERS = {
  active_provider: 'llm:groq',
  configured_provider: 'llm',
  triage_cache: { lookups: 40, hits: 12, hit_rate: 0.3 },
  recent: [
    {
      provider: 'llm:groq',
      latency_ms: 812,
      fallback: false,
      cache_hit: false,
      category: 'water',
      priority: 'high',
      error_class: null,
    },
    {
      provider: 'rules:fallback',
      latency_ms: 10004,
      fallback: true,
      cache_hit: false,
      category: 'roads',
      priority: 'normal',
      error_class: 'TriageTimeout',
    },
  ],
}

function stubFetch(cacheHeader: 'HIT' | 'MISS') {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/stats')) {
        return Promise.resolve(jsonResponse(STATS, { headers: { 'X-Cache': cacheHeader } }))
      }
      return Promise.resolve(jsonResponse(PROVIDERS))
    }),
  )
}

describe('Stats view', () => {
  it('renders aggregate counts by category and priority', async () => {
    stubFetch('MISS')

    render(<StatsView />)

    expect(await screen.findByTestId('total-complaints')).toHaveTextContent('36')
    expect(screen.getByText('water')).toBeInTheDocument()
    // high = 11 now appears in the tile, the bar segment and the legend, so
    // assert on the tile rather than on the bare string.
    expect(screen.getByText('High priority').closest('.tile')).toHaveTextContent('11')
  })

  it('renders MISS from the X-Cache header', async () => {
    stubFetch('MISS')

    render(<StatsView />)

    expect(await screen.findByTestId('cache-badge')).toHaveTextContent('MISS')
    expect(screen.getByText(/computed fresh/i)).toBeInTheDocument()
  })

  it('renders HIT from the X-Cache header', async () => {
    stubFetch('HIT')

    render(<StatsView />)

    // Showing our own cache behaviour is what makes the caching claim
    // demonstrable in the demo rather than merely asserted in the README.
    expect(await screen.findByTestId('cache-badge')).toHaveTextContent('HIT')
    expect(screen.getByText(/came from Redis/i)).toBeInTheDocument()
  })

  it('reports the measured triage cache hit rate and flags fallbacks', async () => {
    stubFetch('HIT')

    render(<StatsView />)

    expect(await screen.findByText(/12\/40 hits/)).toBeInTheDocument()
    expect(screen.getByText(/30\.0% hit rate/)).toBeInTheDocument()
    // A fallback row is visible with the error class that caused it: an
    // operator notices a degraded provider here before anyone reads a metric.
    expect(screen.getByText(/yes \(TriageTimeout\)/)).toBeInTheDocument()
  })

  it('still shows statistics when the providers panel fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        if (String(input).includes('/api/stats')) {
          return Promise.resolve(jsonResponse(STATS, { headers: { 'X-Cache': 'MISS' } }))
        }
        return Promise.resolve(jsonResponse({ error: 'boom', detail: 'no' }, { status: 500 }))
      }),
    )

    render(<StatsView />)

    expect(await screen.findByTestId('total-complaints')).toHaveTextContent('36')
    expect(screen.queryByText(/triage provider/i)).not.toBeInTheDocument()
  })
})

describe('runtime configuration', () => {
  it('defaults to the same origin so nginx can proxy /api', () => {
    window.__CIVICPULSE_CONFIG__ = {}
    expect(apiBaseUrl()).toBe('')
  })

  it('reads the base URL from the runtime config, not from the build', () => {
    // This is the property that keeps one image deployable everywhere: the
    // value arrives from /config.js at container start, never from a Vite
    // import.meta.env baked into the bundle.
    window.__CIVICPULSE_CONFIG__ = { apiBaseUrl: 'https://api.civicpulse.example/' }
    expect(apiBaseUrl()).toBe('https://api.civicpulse.example')
  })
})
