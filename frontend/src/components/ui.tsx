import type { ReactNode } from 'react'

import { IconAlert, IconInbox, IconInfo } from './Icon'

/** Small shared pieces. Kept together because none is big enough to own a file. */

export function Alert({
  tone = 'error',
  children,
}: {
  tone?: 'error' | 'warn' | 'info'
  children: ReactNode
}) {
  const Icon = tone === 'info' ? IconInfo : IconAlert
  return (
    <div className={`alert alert-${tone}`} role="alert">
      <Icon />
      <div>{children}</div>
    </div>
  )
}

export function FieldError({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <p className="field-error" id={id} role="alert">
      <IconAlert />
      {children}
    </p>
  )
}

/**
 * Skeleton rows rather than the word "Loading".
 *
 * A skeleton holds the layout still, so the page does not jump when the data
 * lands, and it communicates roughly how much is coming.
 */
export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <ul className="complaint-list" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <li key={i} className="skeleton-card">
          <div className="sk-row">
            <span className="sk" style={{ width: '4rem' }} />
            <span className="sk" style={{ width: '3.2rem' }} />
            <span className="sk" style={{ width: '3.6rem' }} />
          </div>
          <div className="sk" style={{ width: '62%', height: '0.95rem', marginBottom: '0.55rem' }} />
          <div className="sk" style={{ width: '88%', marginBottom: '0.55rem' }} />
          <div className="sk" style={{ width: '34%' }} />
        </li>
      ))}
    </ul>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <IconInbox />
      <h3>{title}</h3>
      <p>{body}</p>
      {action}
    </div>
  )
}

/** Stat tile: label (sentence case, no colon), value, optional footnote. */
export function Tile({
  label,
  value,
  foot,
  icon,
  hero = false,
  tone,
  testId,
}: {
  label: string
  value: ReactNode
  foot?: ReactNode
  icon?: ReactNode
  hero?: boolean
  tone?: 'critical'
  testId?: string
}) {
  const classes = ['tile', hero ? 'tile-hero' : '', tone ? `tile-${tone}` : '']
    .filter(Boolean)
    .join(' ')
  return (
    <div className={classes}>
      <div className="tile-label">
        {icon}
        {label}
      </div>
      <div className="tile-value" data-testid={testId}>
        {value}
      </div>
      {foot && <div className="tile-foot">{foot}</div>}
    </div>
  )
}
