import { useCallback, useEffect, useState } from 'react'

import { ApiError, listComplaints, updateStatus } from '../api/client'
import {
  CATEGORIES,
  PRIORITIES,
  STATUSES,
  STATUS_LABELS,
  type Category,
  type Complaint,
  type ComplaintPage,
  type Priority,
  type Status,
} from '../api/types'
import {
  CategoryBadge,
  CategoryTile,
  PriorityBadge,
  ProviderBadge,
  StatusBadge,
} from '../components/Badge'
import { IconCheck, IconClock, IconClose, IconPin } from '../components/Icon'
import { Link } from '../components/Link'
import { Alert, EmptyState, SkeletonCards } from '../components/ui'

const PAGE_SIZE = 10

/** Presentation only: which icon sits on a transition button. */
const TRANSITION_ICON = {
  open: IconClock,
  in_progress: IconClock,
  resolved: IconCheck,
  rejected: IconClose,
} as const

export function Dashboard() {
  const [page, setPage] = useState(1)
  const [category, setCategory] = useState<Category | ''>('')
  const [priority, setPriority] = useState<Priority | ''>('')
  const [status, setStatus] = useState<Status | ''>('')

  const [data, setData] = useState<ComplaintPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  /** Keyed by complaint id, so one row's 409 does not blank the whole table. */
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      setData(
        await listComplaints({
          page,
          page_size: PAGE_SIZE,
          category: category || undefined,
          priority: priority || undefined,
          status: status || undefined,
        }),
      )
    } catch (error) {
      setLoadError(
        error instanceof ApiError ? error.body.detail : 'Could not load complaints.',
      )
    } finally {
      setLoading(false)
    }
  }, [page, category, priority, status])

  useEffect(() => {
    void load()
  }, [load])

  function clearFilters() {
    setPage(1)
    setCategory('')
    setPriority('')
    setStatus('')
  }

  async function advance(complaint: Complaint, next: Status) {
    setBusyId(complaint.id)
    setRowErrors((prev) => ({ ...prev, [complaint.id]: '' }))
    try {
      await updateStatus(complaint.id, next)
      await load()
    } catch (error) {
      if (error instanceof ApiError) {
        // The server's 409 message is shown verbatim. It names the attempted
        // transition and what is allowed instead; replacing it with "Error"
        // throws away the only actionable part.
        setRowErrors((prev) => ({ ...prev, [complaint.id]: error.body.detail }))
      } else {
        setRowErrors((prev) => ({ ...prev, [complaint.id]: 'Update failed.' }))
      }
    } finally {
      setBusyId(null)
    }
  }

  const activeFilters: { key: string; label: string; clear: () => void }[] = []
  if (category)
    activeFilters.push({
      key: 'category',
      label: `Category: ${category}`,
      clear: () => {
        setPage(1)
        setCategory('')
      },
    })
  if (priority)
    activeFilters.push({
      key: 'priority',
      label: `Priority: ${priority}`,
      clear: () => {
        setPage(1)
        setPriority('')
      },
    })
  if (status)
    activeFilters.push({
      key: 'status',
      label: `Status: ${STATUS_LABELS[status]}`,
      clear: () => {
        setPage(1)
        setStatus('')
      },
    })

  return (
    <section>
      <div className="page-head">
        <h2>Operations dashboard</h2>
        <p className="lede">
          Newest first. The coloured rail on each card is its priority.
        </p>
      </div>

      <div className="panel toolbar">
        <label className="filter" htmlFor="filter-category">
          <span>Category</span>
          <select
            id="filter-category"
            value={category}
            onChange={(e) => {
              // Any filter change invalidates the page number: page 4 of an
              // unfiltered list is usually past the end of a filtered one.
              setPage(1)
              setCategory(e.target.value as Category | '')
            }}
          >
            <option value="">All</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label className="filter" htmlFor="filter-priority">
          <span>Priority</span>
          <select
            id="filter-priority"
            value={priority}
            onChange={(e) => {
              setPage(1)
              setPriority(e.target.value as Priority | '')
            }}
          >
            <option value="">All</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label className="filter" htmlFor="filter-status">
          <span>Status</span>
          <select
            id="filter-status"
            value={status}
            onChange={(e) => {
              setPage(1)
              setStatus(e.target.value as Status | '')
            }}
          >
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </label>

        <div className="toolbar-end">
          {data && !loading && (
            <p className="result-count">
              <strong>{data.total}</strong> complaint{data.total === 1 ? '' : 's'}
              {data.total > 0 && ` — page ${data.page} of ${data.pages}`}
            </p>
          )}
        </div>
      </div>

      {activeFilters.length > 0 && (
        <div className="chips">
          {activeFilters.map((f) => (
            <span className="chip" key={f.key}>
              {f.label}
              <button type="button" onClick={f.clear} aria-label={`Clear ${f.label}`}>
                <IconClose />
              </button>
            </span>
          ))}
          <button type="button" className="button button-ghost" onClick={clearFilters}>
            Clear all
          </button>
        </div>
      )}

      {loading && <SkeletonCards count={4} />}

      {loadError && !loading && <Alert tone="error">{loadError}</Alert>}

      {data && !loading && !loadError && (
        <>
          {data.items.length === 0 ? (
            <div className="panel">
              <EmptyState
                title="No complaints match these filters"
                body="Nothing here yet. Try widening the filters, or clear them to see everything."
                action={
                  activeFilters.length > 0 ? (
                    <button type="button" className="button button-quiet" onClick={clearFilters}>
                      Clear all filters
                    </button>
                  ) : undefined
                }
              />
            </div>
          ) : (
            <ul className="complaint-list">
              {data.items.map((complaint) => (
                <li key={complaint.id} className={`complaint-card card-${complaint.priority}`}>
                  <div className="card-body">
                  <CategoryTile category={complaint.category} />
                  <div className="card-main">
                  <div className="complaint-head">
                    <PriorityBadge priority={complaint.priority} />
                    <CategoryBadge category={complaint.category} />
                    <StatusBadge status={complaint.status} />
                    <span className="spacer" />
                    <ProviderBadge
                      provider={complaint.triaged_by}
                      latencyMs={complaint.triage_latency_ms}
                    />
                  </div>

                  <p className="complaint-summary">
                    {/* GET /api/complaints/{id}: every card opens its own page. */}
                    <Link to={`/complaints/${complaint.id}`}>{complaint.ai_summary}</Link>
                  </p>
                  <p className="complaint-text">{complaint.text}</p>

                  <p className="complaint-meta">
                    <span>
                      <IconPin />
                      {complaint.location}
                    </span>
                    <span>
                      <IconClock />
                      {new Date(complaint.created_at).toLocaleString()}
                    </span>
                  </p>

                  <div className="transitions">
                    {/* Rendered straight from the server's allowed_transitions.
                        The client holds no copy of the state machine, so adding
                        a status to the backend changes this UI with no frontend
                        release. */}
                    {complaint.allowed_transitions.length === 0 ? (
                      <span className="terminal-note">
                        <IconCheck />
                        {STATUS_LABELS[complaint.status]} &mdash; no further changes
                      </span>
                    ) : (
                      complaint.allowed_transitions.map((next) => {
                        const Icon = TRANSITION_ICON[next]
                        return (
                          <button
                            key={next}
                            type="button"
                            className="button button-quiet"
                            disabled={busyId === complaint.id}
                            onClick={() => void advance(complaint, next)}
                          >
                            <Icon />
                            Mark {STATUS_LABELS[next].toLowerCase()}
                          </button>
                        )
                      })
                    )}
                  </div>

                  {rowErrors[complaint.id] && (
                    <div className="row-alert">
                      <Alert tone="error">{rowErrors[complaint.id]}</Alert>
                    </div>
                  )}
                  </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {data.pages > 1 && (
            <nav className="pagination" aria-label="Pagination">
              <button
                type="button"
                className="button button-quiet"
                disabled={data.page <= 1}
                onClick={() => setPage(data.page - 1)}
              >
                Previous
              </button>
              <span>
                Page {data.page} of {Math.max(1, data.pages)}
              </span>
              <button
                type="button"
                className="button button-quiet"
                disabled={data.page >= data.pages}
                onClick={() => setPage(data.page + 1)}
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  )
}
