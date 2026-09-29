# ADR 0004: What leaves this machine, and to whom

- Status: accepted
- Date: 2026-09-20
- Deciders: both team members

## Context

Citizen complaints are not neutral text. A real one reads:

> "Burst water main flooding Street 12 since fajr, water entering ground floors.
> My son got a stomach infection. Contact 0300-1234567."

That is a street address, a household, a health detail about a minor, and a
phone number. Triage sends complaint text to a third-party inference API.

The free tiers differ in a way that matters more than their rate limits:

- **Groq** — free developer tier gated by rate limits, no credits system, no
  per-token charge. Checked at <https://console.groq.com/docs/rate-limits> on
  2026-09-20; limits are per-organisation and per-model. Re-check before the
  demo, they move.
- **Google AI Studio (Gemini)** — free tier on Flash / Flash-Lite, no credit
  card. **On the free tier Google may use your inputs to improve its models.**
- **Ollama** — local container. Nothing leaves the machine.

The second bullet is the governance fact. A free tier that trains on inputs
means a citizen's address and their child's medical detail can end up in a
future model's weights, with no deletion path and no consent from the citizen,
who was filling in a municipal form.

## Decision

Three parts.

**1. Never send the contact field.** `reporter_contact` is the most directly
identifying field and it is *irrelevant to triage* — a phone number tells you
nothing about whether a complaint is about water or roads. It is stored in
Postgres and never passed to a provider. `ComplaintService.submit` calls
`self._triage.triage(payload.text, payload.location)` and nothing else; see
`backend/app/services/complaint_service.py`. This is enforced by the
`TriageProvider` signature itself — there is no parameter to pass it through.

**2. Send text and location, and accept that.** Both are load-bearing:
"flooding" decides priority, and "Street 12" is how an operations team
dispatches. Redacting them would leave nothing to classify. So this exposure is
accepted, not eliminated, and the mitigations are: a provider that does not
train on inputs, a 24h content-hash cache so a duplicate complaint is not sent
twice, and `temperature: 0` with `max_tokens: 300` so no more is transmitted
than is needed.

**3. Choose the provider on that basis, not on speed.** Default is **Groq**,
because its free tier does not claim a training right over inputs. **Gemini's
free tier is rejected for this application** — not because it is a worse model,
but because "we may train on your citizens' addresses" is not a trade a
municipality can make on a citizen's behalf. Any deployment handling real
complaints should use **Ollama** and send nothing at all; that path is a
first-class provider (`OllamaTriage`), not a degraded fallback.

## Consequences

**Good.** The worst case is bounded and stateable: complaint body and location
reach one named vendor under a no-training tier; contact details never leave the
database. The zero-exposure option is one environment variable away
(`TRIAGE_PROVIDER=ollama`).

**Bad.** The text still contains PII we do not detect. "My son Ahmed at house
221" names a child, and nothing in the pipeline redacts it. A real deployment
needs a PII-detection pass before the provider call. We did not build one, and
we will not pretend a regex would be adequate.

**Bad.** The 24h triage cache stores complaint hashes in Redis. The hash is not
reversible, but it is a stable identifier for a specific complaint, and the
cached *value* includes the AI summary, which quotes the complaint. Redis has
AOF on a volume, so that survives restarts. A deletion request from a citizen
would need to clear Postgres **and** the Redis key. We have not implemented a
deletion endpoint; this is the gap we would close first.

**Operationally:** switching provider is a governance decision, not a
performance knob. `/api/meta/providers` reports which provider is live, so
anyone can check what the running system is actually doing.

## Alternatives rejected

- **Redact before sending.** Considered and abandoned: location is both the PII
  *and* the signal. Removing it makes triage materially worse at priority, which
  harms the citizens the policy is meant to protect.
- **Send only the first 200 characters.** Arbitrary, and the consequence
  sentence that sets priority is often at the end.
- **Use Gemini and document the exposure.** The assignment permits this. We
  judged that a municipality cannot consent on a citizen's behalf to their
  address becoming training data, so documenting it would not make it
  acceptable.
