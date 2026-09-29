import { useCallback, useEffect, useState } from 'react'

import { ApiError, getComplaint, updateStatus } from '../api/client'
import { STATUS_LABELS, type Complaint, type Status } from '../api/types'
import {
  CategoryBadge,
  CategoryTile,
  PRIORITY_MEANING,
  PriorityBadge,
  ProviderBadge,
  StatusBadge,
} from '../components/Badge'
import {
  IconArrowLeft,
  IconCheck,
  IconClock,
  IconClose,
  IconCopy,
  IconPin,
  IconUser,
} from '../components/Icon'
import { Link } from '../components/Link'
import { Alert } from '../components/ui'

/**
 * One complaint, from GET /api/complaints/{id} -- the one endpoint in §2.2's
 * contract that no other view consumed.
 *
 * Note what is not here: a status stepper. A drawn open -> in progress ->
 * resolved track would be a second copy of the state machine living in the
 * browser, which §2.1 forbids. The page shows the current status and exactly
 * the transitions the server sent in allowed_transitions, nothing more.
 */

const TRANSITION_ICON = {
  open: IconClock,
  in_progress: IconClock,
  resolved: IconCheck,
  rejected: IconClose,
} as const

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function ComplaintDetail({ id }: { id: string }) {
  const [complaint, setComplaint] = useState<Complaint | null>(null)
  const [loadError, setLoadError] = useState<{ status: number; detail: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      setComplaint(await getComplaint(id))
    } catch (error) {
      setLoadError(
        error instanceof ApiError
          ? { status: error.status, detail: error.body.detail }
          : { status: 0, detail: 'Could not load this complaint.' },
      )
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  async function advance(next: Status) {
    if (!complaint) return
    setBusy(true)
    setActionError(null)
    try {
      setComplaint(await updateStatus(complaint.id, next))
    } catch (error) {
      // The server's 409 detail, verbatim: it names the attempted transition.
      setActionError(error instanceof ApiError ? error.body.detail : 'Update failed.')
    } finally {
      setBusy(false)
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked -- the reference is still on screen */
    }
  }

  return (
    <section>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/dashboard" className="crumb-back">
          <IconArrowLeft />
          Dashboard
        </Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">Complaint</span>
      </nav>

      {loading && (
        <div className="panel panel-pad" aria-busy="true">
          <div className="sk" style={{ width: '40%', height: '1.3rem', marginBottom: '0.8rem' }} />
          <div className="sk" style={{ width: '90%', marginBottom: '0.5rem' }} />
          <div className="sk" style={{ width: '70%' }} />
        </div>
      )}

      {loadError && !loading && (
        <div className="panel panel-pad detail-missing">
          <h2>{loadError.status === 404 ? 'Complaint not found' : 'Could not load complaint'}</h2>
          {/* The server's own words, not ours. */}
          <Alert tone={loadError.status === 404 ? 'info' : 'error'}>{loadError.detail}</Alert>
          <Link to="/dashboard" className="button button-quiet">
            <IconArrowLeft />
            Back to the dashboard
          </Link>
        </div>
      )}

      {complaint && !loading && (
        <>
          <header className={`detail-head card-${complaint.priority}`}>
            <CategoryTile category={complaint.category} size="lg" />
            <div className="detail-title">
              <div className="complaint-head">
                <PriorityBadge priority={complaint.priority} />
                <CategoryBadge category={complaint.category} />
                <StatusBadge status={complaint.status} />
              </div>
              <h2>{complaint.ai_summary ?? complaint.text}</h2>
            </div>
          </header>

          <div className="detail-grid">
            <div className="detail-main">
              <div className="panel panel-pad">
                <h3 className="section-title">What the citizen reported</h3>
                <p className="detail-text">{complaint.text}</p>

                <dl className="facts">
                  <div>
                    <dt>
                      <IconPin />
                      Location
                    </dt>
                    <dd>{complaint.location}</dd>
                  </div>
                  <div>
                    <dt>
                      <IconUser />
                      Contact
                    </dt>
                    <dd>
                      {complaint.reporter_contact ?? (
                        <span className="muted">Not provided</span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>
                      <IconClock />
                      Reported
                    </dt>
                    <dd>
                      <time dateTime={complaint.created_at}>{when(complaint.created_at)}</time>
                    </dd>
                  </div>
                  <div>
                    <dt>
                      <IconClock />
                      Last updated
                    </dt>
                    <dd>
                      <time dateTime={complaint.updated_at}>{when(complaint.updated_at)}</time>
                    </dd>
                  </div>
                </dl>

                <p className="reference">
                  <span>Reference</span>
                  <code>{complaint.id}</code>
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() => void copy(complaint.id)}
                  >
                    <IconCopy />
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </p>
              </div>
            </div>

            <div className="detail-side">
              <div className="panel panel-pad">
                <h3 className="section-title">Actions</h3>
                <p className="muted small">
                  Current status: <strong>{STATUS_LABELS[complaint.status]}</strong>
                </p>
                <div className="transitions stacked">
                  {/* Straight from the server's allowed_transitions. */}
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
                          className={
                            next === 'rejected' ? 'button button-quiet' : 'button'
                          }
                          disabled={busy}
                          onClick={() => void advance(next)}
                        >
                          <Icon />
                          Mark {STATUS_LABELS[next].toLowerCase()}
                        </button>
                      )
                    })
                  )}
                </div>
                {actionError && (
                  <div className="row-alert">
                    <Alert tone="error">{actionError}</Alert>
                  </div>
                )}
              </div>

              <div className="panel panel-pad">
                <h3 className="section-title">Triage</h3>
                <dl className="facts facts-stack">
                  <div>
                    <dt>Decided by</dt>
                    <dd>
                      <ProviderBadge provider={complaint.triaged_by} />
                    </dd>
                  </div>
                  <div>
                    <dt>Latency</dt>
                    <dd>{complaint.triage_latency_ms} ms</dd>
                  </div>
                  <div>
                    <dt>Priority means</dt>
                    <dd>{PRIORITY_MEANING[complaint.priority]}</dd>
                  </div>
                  {complaint.triage_confidence !== null && (
                    <div>
                      <dt>Confidence</dt>
                      <dd>
                        <span className="meter" aria-hidden="true">
                          <span
                            className="meter-fill"
                            style={{ width: `${Math.round(complaint.triage_confidence * 100)}%` }}
                          />
                        </span>
                        <span className="meter-value">
                          {Math.round(complaint.triage_confidence * 100)}%
                        </span>
                      </dd>
                    </div>
                  )}
                </dl>
                {complaint.triaged_by === 'rules:fallback' && (
                  <p className="note">
                    The AI provider failed for this one, so keyword rules decided it. Worth a
                    human check.
                  </p>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
