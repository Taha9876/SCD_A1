import { useEffect, useState } from 'react'

/**
 * A deliberately tiny router: four routes do not justify a dependency.
 *
 * Every view has a real URL, so refresh keeps you where you were, the back
 * button works, and an operator can paste a link to a complaint into a chat.
 * nginx's `try_files ... /index.html` (and the k8s Ingress `/` rule) serve the
 * app for any of these paths; `/api/*` never reaches this code.
 *
 * Routes map one-to-one onto §2.1's views and §2.2's contract:
 *
 *   /                  Submit     POST  /api/complaints
 *   /dashboard         Dashboard  GET   /api/complaints, PATCH .../status
 *   /complaints/{id}   Detail     GET   /api/complaints/{id}
 *   /stats             Stats      GET   /api/stats, /api/meta/providers
 */

export type Route =
  | { name: 'submit' }
  | { name: 'dashboard' }
  | { name: 'complaint'; id: string }
  | { name: 'stats' }
  | { name: 'not-found'; path: string }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function parse(pathname: string): Route {
  const path = pathname.replace(/\/+$/, '') || '/'
  if (path === '/') return { name: 'submit' }
  if (path === '/dashboard') return { name: 'dashboard' }
  if (path === '/stats') return { name: 'stats' }
  const detail = path.match(/^\/complaints\/([^/]+)$/)
  if (detail && UUID.test(detail[1])) return { name: 'complaint', id: detail[1] }
  return { name: 'not-found', path }
}

export function href(route: Route): string {
  switch (route.name) {
    case 'submit':
      return '/'
    case 'dashboard':
      return '/dashboard'
    case 'stats':
      return '/stats'
    case 'complaint':
      return `/complaints/${route.id}`
    case 'not-found':
      return route.path
  }
}

const EVENT = 'civicpulse:navigate'

export function navigate(to: string): void {
  if (to === window.location.pathname) return
  window.history.pushState({}, '', to)
  window.dispatchEvent(new Event(EVENT))
  // A new page starts at the top, the way a real navigation would.
  window.scrollTo?.(0, 0)
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.pathname))
  useEffect(() => {
    const update = () => setRoute(parse(window.location.pathname))
    window.addEventListener('popstate', update)
    window.addEventListener(EVENT, update)
    return () => {
      window.removeEventListener('popstate', update)
      window.removeEventListener(EVENT, update)
    }
  }, [])
  return route
}

/**
 * Click handler for in-app links. Plain left-clicks navigate in place;
 * ctrl/cmd/shift/middle clicks fall through to the browser, so "open in new
 * tab" still works -- which a real <a href> gets for free and a button never
 * does.
 */
export function onLinkClick(event: React.MouseEvent<HTMLAnchorElement>, to: string): void {
  if (event.defaultPrevented || event.button !== 0) return
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  navigate(to)
}
