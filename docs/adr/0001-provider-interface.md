# ADR 0001: A provider interface for triage

- Status: accepted
- Date: 2026-09-20
- Deciders: both team members

## Context

The system must read free-text complaints and decide a category, a priority and
a one-line summary. Today the best available reader is a hosted LLM on a free
tier. That will not stay true: free-tier limits change, a fine-tuned classifier
may become cheaper, and on a laptop with no network the only available reader is
a keyword table.

The reader is also the least reliable component in the system. It is a third
party, over the internet, with a rate limit measured in tens of requests per
minute, that returns natural language and can simply be wrong.

## Decision

Define one narrow interface and write every consumer against it:

```python
class TriageProvider(Protocol):
    name: str
    async def triage(self, text: str, location: str) -> TriageResult: ...
```

`TriageResult` (`backend/app/providers/triage/base.py`) is a Pydantic model
whose `category` and `priority` are closed enums. Four implementations are
selected by the `TRIAGE_PROVIDER` environment variable in
`backend/app/providers/triage/factory.py`:

| Implementation | File | Role |
|---|---|---|
| `LLMTriage` | `llm.py` | Production. OpenAI-compatible endpoint, Groq by default. |
| `OllamaTriage` | `ollama.py` | Fully offline, a container in the Compose stack. |
| `RuleBasedTriage` | `rules.py` | Deterministic keywords. Never fails, so it is the fallback. |
| `SimulatedTriage` | `simulated.py` | Deterministic fake with failure injection. What CI uses. |

The resilience policy lives in `TriageService`
(`backend/app/services/triage_service.py`), **not** in any provider: 10s hard
timeout, one jittered retry on retryable errors only, content-hash cache,
fallback to rules, and `triaged_by` recorded per row.

## Consequences

**Good.** Adding a provider is one file plus one branch in the factory; nothing
in `routes/`, `services/` or `repositories/` changes. CI is deterministic
because it runs the same wiring with `TRIAGE_PROVIDER=simulated` rather than
monkey-patching a mock over production code. The failure tests inject a provider
that always raises — there is a real seam to inject at.

**Bad.** The interface is the lowest common denominator. Groq supports native
tool calling and Ollama takes a JSON Schema directly in `format`; neither
capability is expressed in `triage()`, so each provider uses what it has
internally and the caller cannot ask for more. We judged substitutability worth
more than that extra fidelity.

**Also bad.** `TriageResult` is a coupling point. Adding a field means touching
every provider. That is the cost of a shared contract, and it is the right cost.

## Alternatives rejected

- **Call the LLM from the route.** Four lines, and then the timeout, retry,
  fallback and cache logic have nowhere to live except the route, where they
  cannot be unit-tested without HTTP.
- **One provider with `if` branches on a config value.** Same behaviour, but
  every provider's imports and error handling end up in one file, and a change
  to the Ollama path can break the Groq path.
- **LangChain or a similar abstraction layer.** It would supply the interface,
  but the marks and the learning are in the timeout/retry/fallback engineering,
  and a library that hides that hides exactly what we must defend at viva.
