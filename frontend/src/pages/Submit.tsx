import { useState, type FormEvent } from 'react'

import { ApiError, submitComplaint } from '../api/client'
import type { Complaint } from '../api/types'
import {
  CategoryBadge,
  PRIORITY_MEANING,
  PriorityBadge,
  ProviderBadge,
} from '../components/Badge'
import { IconArrowLeft, IconCheck, IconCopy, IconExternal, IconSend } from '../components/Icon'
import { Link } from '../components/Link'
import { Alert, FieldError } from '../components/ui'
import {
  TEXT_MAX,
  hasErrors,
  validateDraft,
  type DraftComplaint,
  type ValidationErrors,
} from '../validation'

const EMPTY: DraftComplaint = { text: '', location: '', reporter_contact: '' }

/** Warn before the citizen hits the wall, not at it. */
const COUNTER_WARN_AT = TEXT_MAX - 200

export function Submit() {
  const [draft, setDraft] = useState<DraftComplaint>(EMPTY)
  const [errors, setErrors] = useState<ValidationErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<Complaint | null>(null)
  const [serverError, setServerError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  function update(field: keyof DraftComplaint, value: string) {
    setDraft((prev) => ({ ...prev, [field]: value }))
    // Clear a field's error the moment the citizen starts fixing it. Leaving
    // it up while they type reads as the form arguing with them.
    setErrors((prev) => ({ ...prev, [field]: undefined }))
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setServerError(null)
    setResult(null)

    const clientErrors = validateDraft(draft)
    if (hasErrors(clientErrors)) {
      setErrors(clientErrors)
      // Move focus to the first bad field: a citizen on a phone may not have
      // the error in view at all.
      const first = Object.keys(clientErrors)[0]
      document.getElementById(first)?.focus()
      return
    }

    setSubmitting(true)
    try {
      const complaint = await submitComplaint({
        text: draft.text.trim(),
        location: draft.location.trim(),
        reporter_contact: draft.reporter_contact.trim() || undefined,
      })
      setResult(complaint)
      setDraft(EMPTY)
      setErrors({})
      setCopied(false)
    } catch (error) {
      if (error instanceof ApiError) {
        // The server is the authority on validity. If it rejected fields we
        // thought were fine, show ITS messages, not ours.
        const fieldErrors = error.fieldErrors()
        if (Object.keys(fieldErrors).length > 0) {
          setErrors(fieldErrors as ValidationErrors)
        } else {
          setServerError(error.body.detail)
        }
      } else {
        setServerError('Something unexpected happened. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function copyReference(id: string) {
    try {
      await navigator.clipboard.writeText(id)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked -- the reference is still on screen to write down */
    }
  }

  const overWarn = draft.text.length >= COUNTER_WARN_AT

  return (
    <section className="submit-grid">
     <div className="submit-layout">
      <div className="page-head">
        <h2>Report a problem</h2>
        <p className="lede">
          Describe what is wrong in your own words. You do not need to pick a
          category &mdash; the system reads your report and routes it.
        </p>
      </div>

      <form onSubmit={onSubmit} noValidate className="panel panel-pad">
        <div className="field">
          <label className="field-label" htmlFor="text">
            <span>What is the problem?</span>
            <span className={overWarn ? 'counter counter-warn' : 'counter'}>
              {draft.text.length}/{TEXT_MAX}
            </span>
          </label>
          <textarea
            id="text"
            name="text"
            rows={5}
            value={draft.text}
            onChange={(e) => update('text', e.target.value)}
            aria-invalid={Boolean(errors.text)}
            aria-describedby={errors.text ? 'text-error' : 'text-hint'}
            placeholder="Burst water main flooding Street 12 since fajr, water entering ground floors"
          />
          {errors.text ? (
            <FieldError id="text-error">{errors.text}</FieldError>
          ) : (
            <span className="field-hint" id="text-hint">
              Include what is happening and how long it has been going on.
            </span>
          )}
        </div>

        <div className="field">
          <label className="field-label" htmlFor="location">
            <span>Where is it?</span>
          </label>
          <input
            id="location"
            name="location"
            type="text"
            value={draft.location}
            onChange={(e) => update('location', e.target.value)}
            aria-invalid={Boolean(errors.location)}
            aria-describedby={errors.location ? 'location-error' : undefined}
            placeholder="Street 12, G-9/4, Islamabad"
          />
          {errors.location && (
            <FieldError id="location-error">{errors.location}</FieldError>
          )}
        </div>

        <div className="field">
          <label className="field-label" htmlFor="reporter_contact">
            <span>Your contact</span>
            <span className="optional">optional</span>
          </label>
          <input
            id="reporter_contact"
            name="reporter_contact"
            type="text"
            value={draft.reporter_contact}
            onChange={(e) => update('reporter_contact', e.target.value)}
            aria-invalid={Boolean(errors.reporter_contact)}
            aria-describedby="contact-hint"
            placeholder="0300-1234567"
          />
          {errors.reporter_contact ? (
            <FieldError>{errors.reporter_contact}</FieldError>
          ) : (
            /* Stated plainly, because ADR 0004 promises it and a citizen
               deserves to know before they type a phone number. */
            <span className="field-hint" id="contact-hint">
              Only used if someone needs to reach you. Never sent to the AI service.
            </span>
          )}
        </div>

        <button type="submit" className="button button-lg" disabled={submitting}>
          {submitting ? (
            <>
              <span className="spinner" />
              Reading your report&hellip;
            </>
          ) : (
            <>
              <IconSend />
              Submit report
            </>
          )}
        </button>

        {/* An honest loading state. The AI call genuinely takes seconds, and a
            bare spinner makes people press submit twice. */}
        {submitting && (
          <p className="loading-note" role="status" aria-live="polite">
            Your report is being read and categorised. This usually takes a few seconds.
          </p>
        )}

        {serverError && (
          <div style={{ marginTop: '1rem' }}>
            <Alert tone="error">{serverError}</Alert>
          </div>
        )}
      </form>

      {result && (
        <div className="panel receipt result-panel" role="status" aria-live="polite">
          <div className="receipt-head">
            <IconCheck />
            Report received
          </div>

          <div className="panel-pad">
            <p className="reference">
              <span>Your reference</span>
              <code>{result.id}</code>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void copyReference(result.id)}
              >
                <IconCopy />
                {copied ? 'Copied' : 'Copy'}
              </button>
            </p>

            <dl className="result-grid">
              <dt>Category</dt>
              <dd>
                <CategoryBadge category={result.category} />
              </dd>

              <dt>Priority</dt>
              <dd>
                <PriorityBadge priority={result.priority} />
                {/* A citizen does not know what our enum means. Say it. */}
                <p className="plain-reason">{PRIORITY_MEANING[result.priority]}</p>
              </dd>

              <dt>Summary</dt>
              <dd>{result.ai_summary}</dd>

              <dt>Decided by</dt>
              <dd>
                <ProviderBadge
                  provider={result.triaged_by}
                  latencyMs={result.triage_latency_ms}
                />
                {result.triaged_by === 'rules:fallback' && (
                  <p className="note">
                    The AI service was unavailable, so keyword rules categorised this
                    report. It has still been recorded and will be actioned.
                  </p>
                )}
              </dd>
            </dl>

            <div className="receipt-actions">
              {/* GET /api/complaints/{id}: the reference is a real, shareable page. */}
              <Link to={`/complaints/${result.id}`} className="button button-quiet">
                <IconExternal />
                Open this complaint
              </Link>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => {
                  setResult(null)
                  document.getElementById('text')?.focus()
                }}
              >
                <IconArrowLeft />
                Report another
              </button>
            </div>
          </div>
        </div>
      )}
     </div>

      {/* Presentation only: how the process works, in plain language. No
          numbers here -- every figure in this app comes from the API. */}
      <aside className="submit-aside" aria-label="What happens next">
        <div className="panel panel-pad aside-card">
          <h3 className="section-title">What happens next</h3>
          <ol className="steps">
            <li>
              <span className="step-no">1</span>
              <div>
                <strong>Your words are read</strong>
                <p>An AI model reads the report and decides the category and how urgent it is.</p>
              </div>
            </li>
            <li>
              <span className="step-no">2</span>
              <div>
                <strong>It is routed</strong>
                <p>Urgent reports &mdash; flooding, live wires, sewage in homes &mdash; go to the top of the queue.</p>
              </div>
            </li>
            <li>
              <span className="step-no">3</span>
              <div>
                <strong>An operator acts</strong>
                <p>The team moves it from open to in progress to resolved. Keep your reference to follow it.</p>
              </div>
            </li>
          </ol>
        </div>
        <div className="panel panel-pad aside-card aside-privacy">
          <h3 className="section-title">Your privacy</h3>
          <p>
            Only the description and location are sent for triage. Your contact
            details stay with the municipality and are never sent to the AI service.
          </p>
        </div>
      </aside>
    </section>
  )
}
