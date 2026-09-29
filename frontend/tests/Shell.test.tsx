import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '../src/App'
import { ErrorBoundary } from '../src/components/ErrorBoundary'
import { jsonResponse } from './setup'

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 10, pages: 0 }
const READY = { status: 'ready', dependencies: { database: 'ok', cache: 'ok' } }
// Contract-shaped payloads (the same fields the OpenAPI check enforces), so a
// view reached by navigation renders exactly as it would against the server.
const STATS = {
  total: 3,
  by_category: { water: 2, roads: 1 },
  by_priority: { high: 1, normal: 2 },
  by_status: { open: 3 },
  generated_at: '2026-09-28T06:30:00Z',
}
const PROVIDERS = {
  active_provider: 'rules',
  configured_provider: 'rules',
  triage_cache: { lookups: 0, hits: 0, hit_rate: 0 },
  recent: [],
}

function stubApi(ready: unknown = READY, readyOk = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/ready')) {
        return Promise.resolve(jsonResponse(ready, { status: readyOk ? 200 : 503 }))
      }
      if (url.includes('/api/complaints')) return Promise.resolve(jsonResponse(EMPTY_PAGE))
      if (url.includes('/api/stats')) return Promise.resolve(jsonResponse(STATS))
      if (url.includes('/api/meta/providers')) return Promise.resolve(jsonResponse(PROVIDERS))
      return Promise.resolve(jsonResponse({}))
    }),
  )
}

beforeEach(() => {
  // Routing reads window.location, so every test starts at the root.
  window.history.pushState({}, '', '/')
  document.documentElement.removeAttribute('data-theme')
  try {
    localStorage.clear()
  } catch {
    /* ignore */
  }
})

afterEach(() => {
  document.documentElement.removeAttribute('data-theme')
})

describe('App shell', () => {
  it('exposes a skip link as the first focusable element', async () => {
    stubApi()
    render(<App />)

    const skip = screen.getByRole('link', { name: /skip to content/i })
    expect(skip).toHaveAttribute('href', '#main')
    // A keyboard user must reach the content without tabbing the whole nav.
    await userEvent.tab()
    expect(skip).toHaveFocus()
  })

  it('reports dependency health from /ready, not merely that the page loaded', async () => {
    stubApi()
    render(<App />)

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/all systems ready/i),
    )
  })

  it('names the failed dependency when /ready reports 503', async () => {
    stubApi({ status: 'not ready: database', dependencies: { database: 'unavailable', cache: 'ok' } }, false)
    render(<App />)

    // "Degraded" alone is not actionable; the header says which one.
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/degraded: database/i))
  })

  it('survives /ready being unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    render(<App />)

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/degraded/i))
    // The rest of the app still renders.
    expect(screen.getByRole('heading', { name: /report a problem/i })).toBeInTheDocument()
  })

  it('navigates by real URL and marks the current page for assistive tech', async () => {
    const user = userEvent.setup()
    stubApi()
    render(<App />)

    const nav = screen.getByRole('navigation', { name: /main/i })
    // Links, not buttons: navigation should open in a new tab, be copyable,
    // and be announced as navigation.
    const report = within(nav).getByRole('link', { name: /report/i })
    expect(report).toHaveAttribute('href', '/')
    expect(report).toHaveAttribute('aria-current', 'page')

    await user.click(within(nav).getByRole('link', { name: /dashboard/i }))

    expect(await screen.findByRole('heading', { name: /operations dashboard/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/dashboard')
    expect(within(nav).getByRole('link', { name: /dashboard/i })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(document.title).toMatch(/dashboard/i)
  })

  it('opens the right page on a deep link, so refresh keeps your place', async () => {
    window.history.pushState({}, '', '/stats')
    stubApi()
    render(<App />)

    expect(await screen.findByRole('heading', { name: /statistics/i })).toBeInTheDocument()
  })

  it('shows a not-found page for an unknown path rather than a blank screen', async () => {
    window.history.pushState({}, '', '/definitely-not-a-page')
    stubApi()
    render(<App />)

    expect(await screen.findByText(/there is no page here/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/ready/i))
  })

  it('returns to the previous view on browser back', async () => {
    const user = userEvent.setup()
    stubApi()
    render(<App />)

    await user.click(
      within(screen.getByRole('navigation', { name: /main/i })).getByRole('link', {
        name: /dashboard/i,
      }),
    )
    await screen.findByRole('heading', { name: /operations dashboard/i })

    window.history.back()

    expect(await screen.findByRole('heading', { name: /report a problem/i })).toBeInTheDocument()
  })

  it('toggles the theme by stamping data-theme on the root', async () => {
    const user = userEvent.setup()
    stubApi()
    render(<App />)

    // Nothing stamped means "follow the OS", which is the right default.
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)

    await user.click(screen.getByRole('button', { name: /switch to dark theme/i }))
    await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'dark'))

    await user.click(screen.getByRole('button', { name: /switch to light theme/i }))
    await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'light'))
  })

  it('renders correctly when localStorage is unavailable', async () => {
    // A private window, or site data blocked. The accessor throws; the UI must
    // still render rather than white-screening.
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    stubApi()

    render(<App />)

    expect(screen.getByRole('heading', { name: /report a problem/i })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/ready/i))
    spy.mockRestore()
  })

  it('shows the runtime-resolved API target in the footer', async () => {
    stubApi()
    render(<App />)

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/ready/i))
    expect(screen.getByText(/same origin \(proxied by nginx\)/i)).toBeInTheDocument()
  })
})

describe('ErrorBoundary', () => {
  it('catches a render error instead of blanking the page', () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})

    function Boom(): JSX.Element {
      throw new Error('kaboom')
    }

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(/something went wrong/i)
    expect(screen.getByText('kaboom')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument()

    quiet.mockRestore()
  })
})
