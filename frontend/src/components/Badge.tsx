import type { Category, Priority, Status, TriagedBy } from '../api/types'
import { STATUS_LABELS } from '../api/types'
import {
  IconAlert,
  IconBolt,
  IconCheck,
  IconClock,
  IconClose,
  IconDots,
  IconDroplet,
  IconInfo,
  IconLamp,
  IconMinus,
  IconRoad,
  IconTrash,
} from './Icon'

/**
 * Every badge pairs a hue with an icon and a word.
 *
 * That is not decoration. Roughly 1 in 12 men cannot reliably separate the red
 * and green we use for priority, and this UI also has to survive a greyscale
 * print and Windows high-contrast mode. If colour were the only channel,
 * "high" and "low" would be the same badge to those readers.
 */

const PRIORITY_ICON = {
  high: IconAlert,
  normal: IconInfo,
  low: IconMinus,
} as const

/** Plain language for a citizen, who does not know what our enum means. */
export const PRIORITY_MEANING: Record<Priority, string> = {
  high: 'Treated as urgent — danger to people or property.',
  normal: 'A real service failure with no immediate danger.',
  low: 'Logged for routine scheduling.',
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  const Icon = PRIORITY_ICON[priority]
  return (
    <span className={`badge badge-${priority}`} data-testid="priority-badge">
      <Icon />
      {priority}
    </span>
  )
}

/**
 * Category identity: one hue and one icon per category, used everywhere a
 * category appears, so "water" is the same blue drop on a card, a receipt, a
 * chart label and a detail page.
 *
 * Deliberately a different visual grammar from priority. Priority is a FILLED
 * severity pill; category is a NEUTRAL chip whose icon carries the hue. Filled
 * category chips would collide with priority -- an amber "electricity" chip
 * next to an amber "normal" pill reads as one signal twice. The label text
 * stays in ink, never in the hue, so a light hue never becomes unreadable text.
 */
export const CATEGORY_ICON = {
  water: IconDroplet,
  electricity: IconBolt,
  sanitation: IconTrash,
  roads: IconRoad,
  streetlights: IconLamp,
  other: IconDots,
} as const

export function CategoryBadge({ category }: { category: Category }) {
  const Icon = CATEGORY_ICON[category]
  return (
    <span className={`badge badge-category cat-${category}`} data-testid="category-badge">
      <Icon className="cat-ink" />
      {category}
    </span>
  )
}

/** A tinted square with the category's icon: the visual anchor of a card. */
export function CategoryTile({ category, size = 'md' }: { category: Category; size?: 'md' | 'lg' }) {
  const Icon = CATEGORY_ICON[category]
  return (
    <span className={`cat-tile cat-tile-${size} cat-${category}`} aria-hidden="true">
      <Icon />
    </span>
  )
}

const STATUS_ICON = {
  open: IconInfo,
  in_progress: IconClock,
  resolved: IconCheck,
  rejected: IconClose,
} as const

export function StatusBadge({ status }: { status: Status }) {
  const Icon = STATUS_ICON[status]
  return (
    <span className="badge badge-status" data-testid="status-badge">
      <Icon />
      {STATUS_LABELS[status]}
    </span>
  )
}

/**
 * Which reader actually decided this complaint.
 *
 * An amber `rules:fallback` chip on the dashboard is an operator noticing the
 * AI provider is degraded before anyone thinks to look at a metric. That is
 * why it sits on the card rather than in a debug view.
 */
export function ProviderBadge({
  provider,
  latencyMs,
}: {
  provider: TriagedBy
  latencyMs?: number
}) {
  const degraded = provider === 'rules:fallback'
  return (
    <span
      className={`badge badge-provider${degraded ? ' badge-degraded' : ''}`}
      data-testid="provider-badge"
      title={
        degraded
          ? 'The AI provider failed; keyword rules decided this one.'
          : `Triaged by ${provider}`
      }
    >
      {degraded && <IconBolt />}
      {provider}
      {latencyMs !== undefined && <span className="badge-latency">{latencyMs} ms</span>}
    </span>
  )
}
