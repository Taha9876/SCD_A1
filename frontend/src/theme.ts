import { useCallback, useEffect, useState } from 'react'

/**
 * Theme preference: 'system' follows the OS, 'light'/'dark' override it.
 *
 * An explicit choice stamps data-theme on <html>; 'system' stamps nothing and
 * lets the prefers-color-scheme media query decide. The CSS defines dark twice
 * for exactly that reason -- see styles.css.
 *
 * Every localStorage access is wrapped: in a private window, with site data
 * blocked, or inside a screenshot harness, the accessor can throw or return
 * nothing. The UI must render correctly either way, so this is a convenience,
 * never state the app depends on.
 */

export type Theme = 'system' | 'light' | 'dark'

const KEY = 'civicpulse.theme'

function read(): Theme {
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    /* blocked or unavailable -- fall through to the default */
  }
  return 'system'
}

function apply(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
}

export function useTheme(): { theme: Theme; setTheme: (t: Theme) => void; toggle: () => void } {
  const [theme, setThemeState] = useState<Theme>(read)

  useEffect(() => {
    apply(theme)
  }, [theme])

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* the choice still applies for this session */
    }
  }, [])

  const toggle = useCallback(() => {
    setThemeState((current) => {
      // From 'system', flip to whichever is the opposite of what is showing,
      // so one click always visibly changes something.
      const showingDark =
        current === 'dark' ||
        (current === 'system' &&
          typeof window.matchMedia === 'function' &&
          window.matchMedia('(prefers-color-scheme: dark)').matches)
      const next: Theme = showingDark ? 'light' : 'dark'
      try {
        localStorage.setItem(KEY, next)
      } catch {
        /* ignore */
      }
      return next
    })
  }, [])

  return { theme, setTheme, toggle }
}
