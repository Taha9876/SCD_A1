import { useCallback, useEffect, useState } from 'react'

import { apiBaseUrl, getReady } from './api/client'
import type { ReadyState } from './api/types'
import { IconBrand, IconChart, IconList, IconMoon, IconSend, IconSun } from './components/Icon'
import { Link } from './components/Link'
import { ComplaintDetail } from './pages/ComplaintDetail'
import { Dashboard } from './pages/Dashboard'
import { NotFound } from './pages/NotFound'
import { StatsView } from './pages/StatsView'
import { Submit } from './pages/Submit'
import { useRoute, type Route } from './router'
import { useTheme } from './theme'

/**
 * Navigation. Three entries because §2.1 names three views and says
 * "Nothing else". The complaint detail page is reached from the dashboard,
 * so it is not a top-level entry -- it lights up "Dashboard" instead.
 */
const NAV: { to: string; label: string; Icon: typeof IconSend; owns: Route['name'][] }[] = [
  { to: '/', label: 'Report', Icon: IconSend, owns: ['submit'] },
  { to: '/dashboard', label: 'Dashboard', Icon: IconList, owns: ['dashboard', 'complaint'] },
  { to: '/stats', label: 'Statistics', Icon: IconChart, owns: ['stats'] },
]

/** How often the sidebar re-checks /ready. Slow enough not to be noise. */
const HEALTH_INTERVAL_MS = 30_000

const TITLES: Record<Route['name'], string> = {
  submit: 'Report a problem',
  dashboard: 'Dashboard',
  complaint: 'Complaint',
  stats: 'Statistics',
  'not-found': 'Not found',
}

export function App() {
  const route = useRoute()
  const [ready, setReady] = useState<ReadyState | null>(null)
  const { theme, toggle } = useTheme()

  const checkHealth = useCallback(async () => {
    setReady(await getReady())
  }, [])

  useEffect(() => {
    void checkHealth()
    const id = window.setInterval(() => void checkHealth(), HEALTH_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [checkHealth])

  useEffect(() => {
    document.title = `${TITLES[route.name]} · CivicPulse`
  }, [route.name])

  const failed = ready
    ? Object.entries(ready.dependencies)
        .filter(([, state]) => state !== 'ok')
        .map(([name]) => name)
    : []

  const healthClass = ready ? (ready.ok ? 'health health-ok' : 'health health-down') : 'health'
  const healthText = !ready
    ? 'Checking…'
    : ready.ok
      ? 'All systems ready'
      : `Degraded: ${failed.join(', ') || ready.status}`

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <aside className="sidebar">
        <Link to="/" className="brand" aria-label="CivicPulse home">
          <IconBrand className="brand-mark" />
          <span>
            <span className="brand-name">CivicPulse</span>
            <span className="brand-sub">Complaint intake &amp; triage</span>
          </span>
        </Link>

        <nav className="nav" aria-label="Main">
          {NAV.map(({ to, label, Icon, owns }) => {
            const active = owns.includes(route.name)
            return (
              <Link
                key={to}
                to={to}
                className={active ? 'nav-item nav-active' : 'nav-item'}
                aria-current={active ? 'page' : undefined}
              >
                <Icon />
                <span>{label}</span>
              </Link>
            )
          })}
        </nav>

        <div className="sidebar-foot">
          {/* Driven by /ready, so it reports Postgres and Redis, not merely
              that the page loaded. aria-live so a screen reader hears it when
              the system degrades. */}
          <span className={healthClass} role="status" aria-live="polite" title={healthText}>
            <span className="health-dot" />
            <span className="health-text">{healthText}</span>
          </span>

          <button
            type="button"
            className="icon-button"
            onClick={toggle}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            title="Toggle theme"
          >
            {theme === 'dark' ? <IconSun /> : <IconMoon />}
          </button>
        </div>
      </aside>

      <div className="content">
        <main id="main" tabIndex={-1}>
          {route.name === 'submit' && <Submit />}
          {route.name === 'dashboard' && <Dashboard />}
          {route.name === 'complaint' && <ComplaintDetail id={route.id} />}
          {route.name === 'stats' && <StatsView />}
          {route.name === 'not-found' && <NotFound path={route.path} />}
        </main>

        <footer className="site-foot">
          <span>CivicPulse &mdash; municipal complaint intake, triage and operations.</span>
          {/* The runtime-resolved backend: how you verify the same image is
              talking to a different API in each environment. */}
          <span>
            API: <code>{apiBaseUrl() || 'same origin (proxied by nginx)'}</code>
          </span>
        </footer>
      </div>
    </div>
  )
}
