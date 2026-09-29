import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Submit } from '../src/pages/Submit'
import { jsonResponse } from './setup'

const CREATED = {
  id: '11111111-1111-4111-8111-111111111111',
  text: 'Burst water main flooding Street 12 since fajr this morning.',
  location: 'Street 12, G-9/4, Islamabad',
  reporter_contact: null,
  category: 'water',
  priority: 'high',
  status: 'open',
  ai_summary: 'Burst main flooding Street 12, water entering ground floors',
  triaged_by: 'llm:groq',
  triage_latency_ms: 842,
  triage_confidence: 0.93,
  created_at: '2026-09-20T06:30:00Z',
  updated_at: '2026-09-20T06:30:00Z',
  allowed_transitions: ['in_progress', 'rejected'],
}

const VALID_TEXT = 'Burst water main flooding Street 12 since fajr this morning.'
const VALID_LOCATION = 'Street 12, G-9/4, Islamabad'

describe('Submit view', () => {
  it('renders the triage result including which provider decided it', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(CREATED, { status: 201 })),
    )

    render(<Submit />)

    await user.type(screen.getByLabelText(/what is the problem/i), VALID_TEXT)
    await user.type(screen.getByLabelText(/where is it/i), VALID_LOCATION)
    await user.click(screen.getByRole('button', { name: /submit report/i }))

    await waitFor(() => expect(screen.getByText(/report received/i)).toBeInTheDocument())
    expect(screen.getByTestId('category-badge')).toHaveTextContent('water')
    expect(screen.getByTestId('priority-badge')).toHaveTextContent('high')
    expect(screen.getByText(CREATED.ai_summary)).toBeInTheDocument()
    // The provider is surfaced, not hidden -- that is the observability point.
    expect(screen.getByTestId('provider-badge')).toHaveTextContent('llm:groq')
    expect(screen.getByTestId('provider-badge')).toHaveTextContent('842 ms')
  })

  it('blocks submission client-side without calling the API', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<Submit />)

    await user.type(screen.getByLabelText(/what is the problem/i), 'too short')
    await user.type(screen.getByLabelText(/where is it/i), VALID_LOCATION)
    await user.click(screen.getByRole('button', { name: /submit report/i }))

    expect(await screen.findByText(/at least 10 characters/i)).toBeInTheDocument()
    // Mirroring the server rules means not wasting a round trip on input we
    // already know it will reject.
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows the server field-level error when the server disagrees with us', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: 'validation_error',
            detail: 'One or more fields are invalid.',
            fields: [
              { field: 'location', message: 'Location is not recognised', type: 'value_error' },
            ],
          },
          { status: 400 },
        ),
      ),
    )

    render(<Submit />)

    await user.type(screen.getByLabelText(/what is the problem/i), VALID_TEXT)
    await user.type(screen.getByLabelText(/where is it/i), VALID_LOCATION)
    await user.click(screen.getByRole('button', { name: /submit report/i }))

    // The server is the authority; its message wins over ours.
    expect(await screen.findByText('Location is not recognised')).toBeInTheDocument()
  })

  it('shows an honest loading state while the AI call is in flight', async () => {
    const user = userEvent.setup()
    let release: (value: Response) => void = () => {}
    const pending = new Promise<Response>((resolve) => {
      release = resolve
    })
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending))

    render(<Submit />)

    await user.type(screen.getByLabelText(/what is the problem/i), VALID_TEXT)
    await user.type(screen.getByLabelText(/where is it/i), VALID_LOCATION)
    await user.click(screen.getByRole('button', { name: /submit report/i }))

    // "Reading your report" says what is happening; a bare spinner does not,
    // and people press submit twice when it does not.
    expect(await screen.findByText(/reading your report/i)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/a few seconds/i)
    expect(screen.getByRole('button', { name: /reading your report/i })).toBeDisabled()

    release(jsonResponse(CREATED, { status: 201 }))
    await waitFor(() => expect(screen.getByText(/report received/i)).toBeInTheDocument())
  })

  it('tells the citizen when triage fell back to rules', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ ...CREATED, triaged_by: 'rules:fallback' }, { status: 201 }),
      ),
    )

    render(<Submit />)

    await user.type(screen.getByLabelText(/what is the problem/i), VALID_TEXT)
    await user.type(screen.getByLabelText(/where is it/i), VALID_LOCATION)
    await user.click(screen.getByRole('button', { name: /submit report/i }))

    expect(await screen.findByTestId('provider-badge')).toHaveTextContent('rules:fallback')
    // A degraded path is explained, not hidden -- and it is still a success.
    expect(screen.getByText(/has still been recorded/i)).toBeInTheDocument()
  })

  it('reports a network failure without pretending it was a validation error', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    render(<Submit />)

    await user.type(screen.getByLabelText(/what is the problem/i), VALID_TEXT)
    await user.type(screen.getByLabelText(/where is it/i), VALID_LOCATION)
    await user.click(screen.getByRole('button', { name: /submit report/i }))

    expect(await screen.findByText(/could not reach the server/i)).toBeInTheDocument()
  })
})
