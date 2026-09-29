# AI usage disclosure

Per §5.5: honest attribution, not avoidance. Specific disclosure carries no
penalty. Presenting AI-generated work as your own original work does.

> **This file is a template that is currently telling the truth about how the
> repository was produced. Before you submit, edit it to describe what *you*
> actually did** — which parts you changed, what you rejected, what you had to
> fix. The viva does not care who wrote a line; it cares whether you can defend
> it. A line you cannot defend is worth nothing regardless of its author.

---

## Tools used

| Tool | Used for |
|---|---|
| Claude (Anthropic), via Claude Code | Initial implementation of the backend, frontend, Docker, Kubernetes manifests, CI/CD workflows and this documentation set. |
| *(add yours: Copilot, ChatGPT, Cursor, …)* | |

---

## What the AI wrote, and what we changed

### Written largely by AI, then reviewed

- **Backend application code** (`backend/app/`) — layering, the triage provider
  interface and its four implementations, the resilience policy in
  `TriageService`, the repository, routes, middleware, metrics and structured
  logging.
- **Test suite** (`backend/tests/`, `frontend/tests/`) — 103 backend tests and
  20 frontend tests.
- **Infrastructure** — both Dockerfiles, `compose.yaml`, `compose.prod.yaml`,
  the Kustomize base and overlays, the three GitHub Actions workflows,
  `load/k6-script.js` and `scripts/check_submission.py`.
- **Documentation** — this file, the four ADRs, `RUNBOOK.md`, `TRIAGE.md` and
  the structure of `ENGINEERING-NOTES.md`.

### Bugs found by running it, and fixed

Three real defects surfaced only by executing the code, and are worth being able
to explain because each one is a genuine portability lesson:

1. **`char_length()` in a CHECK constraint** — a Postgres function SQLite does
   not have, so the entire test suite errored at fixture setup. Changed to
   `length()`, which is valid on both. (`backend/app/models.py`,
   `backend/alembic/versions/0001_initial_schema.py`)
2. **`server_default=gen_random_uuid()` on the model** — SQLite requires an
   expression default to be parenthesised, so DDL generation failed at the
   parser. Fixed by removing the server default from the *model* and leaving it
   in the *migration*, which is the only thing that emits DDL and only ever runs
   against Postgres. This made the layering more correct, not less. The full
   debugging story is question 8 of `ENGINEERING-NOTES.md`.
3. **Two copies of Vite** — `vitest` bundles its own, so `tsc` compared two
   structurally identical but nominally different `Plugin` types and failed.
   Fixed with an `overrides` entry in `package.json` forcing a single version,
   and by splitting `vitest.config.ts` from `vite.config.ts`.

### Four more, found only on real infrastructure

The first three were caught against SQLite. These four surfaced only when the
stack ran under Docker Compose against real Postgres, nginx and Groq. Unit
tests could not have caught any of them, which is the argument for the Compose
integration job in `ci.yml`.

4. **The migration created its enum types twice.** It called `.create()` on
   each type explicitly, and then `create_table` emitted `CREATE TYPE` again for
   every enum column, failing with `type "category_enum" already exists`.
   Postgres's transactional DDL rolled the whole thing back cleanly. Fixed with
   `postgresql.ENUM(..., create_type=False)`. The downgrade was then verified
   too: `alembic downgrade base` leaves zero tables and zero types.
5. **The frontend container reported `unhealthy` while serving fine.** Inside
   the Alpine image `localhost` resolves to `::1` first, nginx listened only on
   IPv4, and busybox `wget` does not fall back. Fixed by adding
   `listen [::]:8080;` to `nginx.conf`, rather than editing three healthchecks.
6. **Groq had retired `llama-3.1-8b-instant`.** Every call returned 404. The
   system stayed up: 404 is non-retryable, so each request fell back to rules in
   ~200 ms. Four candidate models were then benchmarked through the real code
   path and `qwen/qwen3.8-27b` chosen; see `docs/TRIAGE.md`.
7. **The frontend image installed `gettext` for nothing.** The nginx base
   already ships `envsubst`. `docker history` showed 2.94 MB of waste plus a
   package pin that would have broken the build. Removed.

### Verified, not assumed

Everything below was actually run, not asserted:

```
backend:  112 tests pass, 88.6% coverage, ruff clean, mypy clean
frontend: 41 tests pass, tsc clean, eslint clean, production build
k8s:      all 18 manifests parse
compose:  all 4 services healthy; migrations up AND down; seed idempotent;
          real Groq triage; frontend provably cannot reach the database;
          every row survives `down` + `up`; images non-root; no Node in the
          frontend runtime image (53.2 MB)
```

Build-context and image sizes in `ENGINEERING-NOTES.md` are measured, not
estimated.

---

## What we changed for our own reasons

*(Fill this in. Examples of the kind of thing that belongs here:)*

- *Rejected the AI's initial suggestion of X because Y.*
- *Rewrote the keyword tables in `rules.py` — the generated ones did not match
  the vocabulary our complaints actually use.*
- *Changed the rate limit from N to M after discovering our provider's real
  limit was lower than assumed.*
- *Added the Nth test after noticing a case the suite did not cover.*

---

## What is not written yet, and is yours

These carry marks and **cannot** be produced by an AI, because they are records
of things you did:

| Item | Where |
|---|---|
| Real load-test numbers and the HPA lag | `ENGINEERING-NOTES.md` Q5 |
| Real VPA recommendation and the follow-up | `ENGINEERING-NOTES.md` Q6 |
| Your own hour-long failure | `ENGINEERING-NOTES.md` Q8 |
| Branch-protection screenshot | `docs/evidence/` |
| Five+ PRs with your partner's review comments | GitHub |
| The deliberate merge conflict and its resolution | `docs/evidence/` |
| Red-then-green pipeline evidence | `docs/evidence/` |
| `kubectl get hpa -w` capture and the replicas chart | `docs/evidence/` |
| The demo video, both partners speaking | Submission form |

---

## How we worked with it

*(Replace with your own account. What honest disclosure looks like:)*

We used the AI as a fast implementer of decisions we made, not as a decision
maker. The architectural choices that carry the marks — four-layer separation,
the provider interface, two networks with the backend as the sole bridge, deploy
by SHA, the PII position — are recorded as ADRs with the alternatives we
rejected and why, and we can each defend them without reference to the tool.

Where we could not defend something, we changed it until we could, or removed
it. That is the standard we applied, and it is the standard the viva applies.
