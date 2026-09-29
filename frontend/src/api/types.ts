/**
 * Types mirroring the backend's OpenAPI schema.
 *
 * Checked against it in CI by `scripts/check_openapi_contract.py`, which
 * builds the app in-process and diffs these unions and interfaces against
 * the schema it serves at /openapi.json. When the backend adds a
 * category and the frontend does not, that job fails -- which is the point:
 * the contract is enforced, not hoped for.
 *
 * Note what is NOT here: the list of valid status transitions. The server
 * sends `allowed_transitions` on every complaint. The moment this file
 * contains a transition table there are two sources of truth and one will rot.
 */

export type Category =
  | 'water'
  | 'electricity'
  | 'sanitation'
  | 'roads'
  | 'streetlights'
  | 'other'

export type Priority = 'high' | 'normal' | 'low'

export type Status = 'open' | 'in_progress' | 'resolved' | 'rejected'

export type TriagedBy =
  | 'llm:groq'
  | 'llm:ollama'
  | 'rules'
  | 'rules:fallback'
  | 'simulated'

export interface Complaint {
  id: string
  text: string
  location: string
  reporter_contact: string | null
  category: Category
  priority: Priority
  status: Status
  ai_summary: string | null
  triaged_by: TriagedBy
  triage_latency_ms: number
  triage_confidence: number | null
  created_at: string
  updated_at: string
  /** Decided by the server. The client renders it; it never computes it. */
  allowed_transitions: Status[]
}

export interface ComplaintPage {
  items: Complaint[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface Stats {
  total: number
  by_category: Record<string, number>
  by_priority: Record<string, number>
  by_status: Record<string, number>
  generated_at: string
}

export interface StatsResponse {
  stats: Stats
  /** Read from the X-Cache response header. */
  cacheHit: boolean
}

export interface TriageRecord {
  provider: string
  latency_ms: number
  fallback: boolean
  cache_hit: boolean
  category: string
  priority: string
  error_class: string | null
}

export interface ProvidersInfo {
  active_provider: string
  configured_provider: string
  triage_cache: { lookups: number; hits: number; hit_rate: number }
  recent: TriageRecord[]
}

export interface FieldError {
  field: string
  message: string
  type: string
}

export interface ErrorBody {
  error: string
  detail: string
  fields?: FieldError[]
  current_status?: Status
  attempted_status?: Status
  allowed_transitions?: Status[]
}

export interface ComplaintFilters {
  category?: Category
  priority?: Priority
  status?: Status
  page?: number
  page_size?: number
}

export const CATEGORIES: Category[] = [
  'water',
  'electricity',
  'sanitation',
  'roads',
  'streetlights',
  'other',
]

export const PRIORITIES: Priority[] = ['high', 'normal', 'low']

export const STATUSES: Status[] = ['open', 'in_progress', 'resolved', 'rejected']

/** Presentation only. Not a business rule -- purely how a status is spelled. */
export const STATUS_LABELS: Record<Status, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved: 'Resolved',
  rejected: 'Rejected',
}

/** Shape the header health indicator renders. */
export interface ReadyState {
  ok: boolean
  status: string
  dependencies: Record<string, string>
}
