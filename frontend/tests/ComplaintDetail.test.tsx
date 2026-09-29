import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ComplaintDetail } from '../src/pages/ComplaintDetail'
import { href, parse } from '../src/router'
import { jsonResponse } from './setup'

const ID = '11111111-1111-4111-8111-111111111111'

const COMPLAINT = {
  id: ID,
  text: 'Bijli ki taar gir gayi hai footpath par, bachay school isi raste se jaate hain.',
  location: 'Street 3, Chaklala Scheme 3, Rawalpindi',
  reporter_contact: '0300-1234567',
  category: 'electricity',
  priority: 'high',
  status: 'open',
  ai_summary: 'Live electrical wire fallen on footpath near school route',
  triaged_by: 'llm:groq',
  triage_latency_ms: 378,
  triage_confidence: 0.94,
  created_at: '2026-09-28T06:30:00Z',
  updated_at: '2026-09-28T06:30:00Z',
  allowed_transitions: ['in_progress', 'rejected'],
}

describe('Complaint detail page', () => {
  it('loads the complaint from GET /api/complaints/{id}', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(COMPLAINT))
    vi.stubGlobal('fetch', fetchMock)

    render(<ComplaintDetail id={ID} />)

    expect(
      await screen.findByRole('heading', { name: COMPLAINT.ai_summary }),
    ).toBeInTheDocument()
    expect(String(fetchMock.mock.calls[0][0])).toBe(`/api/complaints/${ID}`)
    expect(screen.getByText(COMPLAINT.text)).toBeInTheDocument()
    expect(screen.getByText(COMPLAINT.location)).toBeInTheDocument()
    expect(screen.getByTestId('provider-badge')).toHaveTextContent('llm:groq')
    expect(screen.getByText('94%')).toBeInTheDocument()
  })

  it('offers only the transitions the server allows', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(COMPLAINT)))

    render(<ComplaintDetail id={ID} />)

    expect(await screen.findByRole('button', { name: /mark in progress/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark rejected/i })).toBeInTheDocument()
    // No client-side copy of the state machine: resolved is not offered from open.
    expect(screen.queryByRole('button', { name: /mark resolved/i })).not.toBeInTheDocument()
  })

  it('updates in place after a successful transition', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(COMPLAINT))
        .mockResolvedValueOnce(
          jsonResponse({
            ...COMPLAINT,
            status: 'in_progress',
            allowed_transitions: ['rejected', 'resolved'],
          }),
        ),
    )

    render(<ComplaintDetail id={ID} />)
    await user.click(await screen.findByRole('button', { name: /mark in progress/i }))

    await waitFor(() =>
      expect(screen.getByTestId('status-badge')).toHaveTextContent('In progress'),
    )
    expect(screen.getByRole('button', { name: /mark resolved/i })).toBeInTheDocument()
  })

  it('surfaces the server 409 message verbatim', async () => {
    const user = userEvent.setup()
    const message =
      'Invalid status transition open -> in_progress. Allowed from open: rejected.'
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(COMPLAINT))
        .mockResolvedValueOnce(
          jsonResponse({ error: 'invalid_transition', detail: message }, { status: 409 }),
        ),
    )

    render(<ComplaintDetail id={ID} />)
    await user.click(await screen.findByRole('button', { name: /mark in progress/i }))

    expect(await screen.findByText(message)).toBeInTheDocument()
  })

  it('shows the server 404 detail for an unknown id', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { error: 'not_found', detail: `No complaint with id ${ID}.` },
            { status: 404 },
          ),
        ),
    )

    render(<ComplaintDetail id={ID} />)

    expect(await screen.findByRole('heading', { name: /complaint not found/i })).toBeInTheDocument()
    expect(screen.getByText(`No complaint with id ${ID}.`)).toBeInTheDocument()
  })

  it('says so when no contact was given, instead of leaving a blank', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ ...COMPLAINT, reporter_contact: null })),
    )

    render(<ComplaintDetail id={ID} />)

    expect(await screen.findByText(/not provided/i)).toBeInTheDocument()
  })
})

describe('router', () => {
  it('maps every path in the app to its view', () => {
    expect(parse('/')).toEqual({ name: 'submit' })
    expect(parse('/dashboard')).toEqual({ name: 'dashboard' })
    expect(parse('/dashboard/')).toEqual({ name: 'dashboard' })
    expect(parse('/stats')).toEqual({ name: 'stats' })
    expect(parse(`/complaints/${ID}`)).toEqual({ name: 'complaint', id: ID })
  })

  it('rejects a complaint path that is not a UUID rather than calling the API with it', () => {
    expect(parse('/complaints/not-a-uuid').name).toBe('not-found')
    expect(parse('/complaints/../../etc').name).toBe('not-found')
  })

  it('round-trips a route through href', () => {
    expect(parse(href({ name: 'complaint', id: ID }))).toEqual({ name: 'complaint', id: ID })
  })
})
