import type { AnchorHTMLAttributes, ReactNode } from 'react'

import { onLinkClick } from '../router'

/**
 * An in-app link. It renders a real <a href>, so it can be opened in a new
 * tab, copied, and read by a screen reader as a link -- then intercepts plain
 * clicks to navigate without a page reload.
 */
export function Link({
  to,
  children,
  ...rest
}: { to: string; children: ReactNode } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>) {
  return (
    <a href={to} onClick={(e) => onLinkClick(e, to)} {...rest}>
      {children}
    </a>
  )
}
