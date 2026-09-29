# Engineering notes

The eight questions from §5.2, answered against this repository.

> **Before you submit:** questions 5, 6 and 8 need numbers and a story only you
> can produce — a real load test on your cluster, a real VPA recommendation, and
> a real failure that cost you an hour. The structure and the reasoning are
> here; the measurements marked **[MEASURE]** are yours to fill in. Generic
> answers score zero, and an invented number is worse than a blank.

---

## 1. Three things that differ between your laptop and a CI runner, and the exact line that freezes each

**a. The Python interpreter.** Our laptop runs Python 3.13.6 (whatever Windows
installed); the runner has whatever `ubuntu-24.04` ships. A 3.13-only syntax
error would pass locally and fail in CI, or worse, the reverse.

Frozen by `backend/Dockerfile:6` — `FROM python:3.12-slim-bookworm`. Everything
that runs in an image runs on 3.12 regardless of host. For the jobs that run
*outside* a container, `.github/workflows/ci.yml` sets `PYTHON_VERSION: '3.12'`
and `actions/setup-python@v5` pins it.

**b. Installed system libraries.** Our laptop has a C toolchain, a Postgres
client and whatever else accumulated over a semester. A fresh runner has almost
none of it, so a dependency that silently compiled against a local header fails
there.

Frozen by `backend/Dockerfile:18-20` — the builder stage installs
`build-essential=12.9` explicitly, pinned to a version, and the runtime stage
(line 39-41) installs only `curl`. Nothing is inherited from the host.

**c. The dependency resolution itself.** `pip install fastapi` on our laptop in
September and on a runner in December are different FastAPI versions.

Frozen by `backend/requirements.txt` — every line is `==`, not `>=` — and by
`frontend/package-lock.json` plus `npm ci` (not `npm install`) at
`.github/workflows/ci.yml`, the *Install frontend dependencies* step. `npm ci`
installs exactly the lockfile and errors if `package.json` disagrees;
`npm install` would happily resolve a newer transitive dependency nobody
reviewed.

A fourth, worth noting because it bit us: the laptop is Windows and the runner
is Linux, so `length()` vs `char_length()` and CRLF line endings are live
differences. See Q8.

---

## 2. Where the pipeline sits on the CI/CD maturity ladder

**Rung: continuous deployment to a non-production environment** — one below
continuous deployment to production.

What we have that justifies the rung:

- Every PR into main runs lint, types, both test suites, an image build, a
  Trivy scan, manifest validation and a full Compose integration test
  (`ci.yml`). These are required checks; the merge button is blocked until they
  are green.
- Every merge to main automatically retests the merged result, builds and
  pushes SHA-tagged images, spins up a real Kubernetes cluster, applies
  migrations, deploys, waits on `kubectl rollout status` and smoke-tests
  through the Ingress (`cd.yml`). No human presses anything after the approval.
- Deployment is by immutable reference and rollback is two documented commands.

What keeps us off the next rung: the cluster in `cd.yml` is ephemeral — created
in the runner and deleted at the end. Nothing persistent is being reconciled, so
we have proven the deployment *works* without ever having deployed to something
that stays up.

**Next rung: continuous deployment to a persistent environment, with automated
rollback on a health signal.** What it buys, concretely: right now a bad deploy
that passes the smoke test would sit in production until a human noticed. The
next rung adds a post-deploy watch on the error rate and `/metrics`, and rolls
back automatically. That turns mean-time-to-recovery from "however long until
someone checks" into a bounded number. The GitOps bonus (Argo CD reconciling
from the repository) is the same rung approached differently: it also makes
drift visible, which an imperative `kubectl apply` never does.

---

## 3. The exact line guaranteeing build-once-deploy-many, and what breaks without it

**The line:** `frontend/docker-entrypoint.sh`, the `cat > "$CONFIG_PATH"`
heredoc that writes

```js
window.__CIVICPULSE_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}" };
```

at **container start**, read back by `apiBaseUrl()` in
`frontend/src/api/client.ts`.

**What breaks without it.** Vite inlines `import.meta.env.*` into the bundle at
build time. Had the client read `import.meta.env.VITE_API_URL`, the API URL
would be frozen into the JavaScript the moment `vite build` runs. One image
would then work against exactly one backend, and dev, CI and the cluster would
each need their own build of the same commit. Three artifacts for one SHA means
the artifact CI tested is provably not the artifact production runs — which is
the entire property build-once-deploy-many exists to give you.

**The supporting half:** `frontend/nginx.conf` proxies `/api` to
`${BACKEND_ORIGIN}`, so in the normal deployment `API_BASE_URL` is empty and the
bundle contains no backend URL *at all*. There is nothing to bake in.

`frontend/tests/StatsView.test.tsx` has two tests asserting the runtime lookup,
so a regression to `import.meta.env` fails CI rather than being discovered on a
cluster. Full reasoning in `docs/adr/0002-frontend-runtime-config.md`.

---

## 4. What "correct" means for a probabilistic component, and how CI stays deterministic

**"Correct" is not "returns the right category."** With `TRIAGE_PROVIDER=llm`
the same complaint can produce different output on two calls, and no assertion
on the output can be both meaningful and stable. Asking for that would produce
a flaky suite, and a flaky pipeline trains a team to ignore red — worse than
having no pipeline.

So correctness is defined on the **envelope**, not the value. For the triage
component, correct means:

1. **The output is always in the schema.** Whatever the model returns, what
   reaches the database is a valid `Category`, a valid `Priority`, a summary of
   at most 140 characters and a confidence in [0, 1]. Anything else is rejected
   by `TriageResult` in `backend/app/providers/triage/base.py`.
2. **A caller never sees a 500 because a third party misbehaved.** Timeout,
   429, 5xx, prose, an invented category — every one of these ends in a
   rule-based result and a 201, with `triaged_by = "rules:fallback"`.
3. **Every call terminates within the timeout.** 10s hard cap via
   `asyncio.wait_for` in `TriageService._call_with_retry`, regardless of what
   the provider's own client does.
4. **The decision is attributable.** Every row records which reader decided it
   and how long it took.

Those are all testable without any model being involved, which is the point.

**How CI stays green on every run:**

- `TRIAGE_PROVIDER=simulated` is set at the job level in `ci.yml` and `cd.yml`.
  `SimulatedTriage` derives its output from a SHA-256 of the input plus a fixed
  seed, so the same complaint always gives the same answer — and, because the
  seed is *content*-derived rather than call-order-derived, a test gets the same
  answer regardless of what ran before it.
- Failure paths use injected providers rather than network conditions:
  `AlwaysRaises`, `Hangs` and `Counting` in
  `backend/tests/test_triage_resilience.py`.
- Malformed output is tested by feeding `parse_triage_json` the exact shapes a
  real model produces when it misbehaves — a code fence, a prose preamble, an
  invented enum value, a 400-character "one-line" summary.
- The LLM provider's HTTP behaviour is tested against `httpx.MockTransport`
  (`backend/tests/test_llm_provider.py`), so the status-code-to-retry-policy
  mapping is asserted without a network.
- Jitter is injected (`sleep=_no_sleep`, `rng=_FixedRandom()`), so the retry
  path is exercised without the suite actually sleeping. **There is no
  `time.sleep()` anywhere in the test suite**, and no test is re-run to get a
  pass.

**The test that matters most**, per the assignment:
`test_provider_that_always_raises_still_returns_a_result_via_fallback` — given a
provider that always raises, `POST /api/complaints` still returns 201 and
`triaged_by == "rules:fallback"`.

---

## 5. HPA lag

**Setup.** Measured on 2026-09-29 on a local k3d cluster (1 server, 1 agent),
deployed with the prod overlay through ingress-nginx, with metrics-server at its
default resolution. `load/k6-script.js` ran against the Ingress: 5 VUs for a
minute, a ramp to 60 VUs over the next, then a 3-minute hold.
`kubectl get hpa backend-hpa -n civicpulse -w` recorded alongside, with every
line time-stamped, into `docs/evidence/hpa-watch.txt`; a 5-second sampler
recorded desired vs ready replicas. The chart is
`docs/evidence/hpa-scaling-chart.png`.

**Measured lag: 37 seconds** from the offered load doubling to a new replica
serving traffic. It splits into two parts that behave very differently:

| Time | t+ | Event | Source |
|---|---|---|---|
| 08:47:00 | 0s | k6 starts, 5 VUs, ~13 req/s | `load/results` |
| 08:48:05 | 65s | offered load doubles (ramp towards 60 VUs) | k6 per-request log |
| 08:48:12 | 72s | HPA reads **60%/60% and does nothing** | `hpa-watch.txt` line 12 |
| 08:48:27 | 87s | HPA reads 75%, above target | `hpa-watch.txt` line 13 |
| 08:48:29 | 89s | desired replicas 2 → 3: **decision lag 24s** | sampler |
| 08:48:42 | 102s | 3rd pod Ready and in the Service: **start-up 13s** | sampler |
| 08:49:13 | 133s | desired 10 = `maxReplicas`; CPU peaks at 353% of request | `hpa-watch.txt` line 16 |

**Where the time went.**

- **24s of it was deciding**, and none of that was Kubernetes being slow. It
  is the metrics pipeline plus one rule. `hpa-watch.txt` updates every 15
  seconds, which is metrics-server's resolution, so a load change is invisible
  until the next reading. Then at 08:48:12 the HPA saw *exactly* 60% and did
  nothing: it only acts when utilisation exceeds the target by more than its
  10% tolerance, i.e. above 66%. It acted on the *next* reading, 15 seconds
  later.
- **13s of it was starting a pod**: scheduling, container start (no pull —
  `IfNotPresent` and the image already on the node), and the `startupProbe`
  and `readinessProbe` passing.

**What happened during the lag.** The two existing pods absorbed the step,
running at up to 353% of their CPU *request*. They could, because the limit is
500m (5× the 100m request) — a limit close to the request would have throttled
them exactly when it mattered. That is why the run had **0.00% failed requests
and a 47 ms p95** despite the lag (`docs/evidence/hpa-k6-summary.txt`).

**Two findings the run surfaced.**

1. **The HPA hit its ceiling.** It reached `maxReplicas: 10` at t+133s and CPU
   still sat at 130–170% of request for the whole hold. At 60 VUs, ten pods
   of 100m is not enough; the 100m request is an underestimate of real use.
   That is exactly the question the VPA loop (question 6) answers.
2. **Scale-down waited on purpose.** After the load stopped, replicas stayed
   at 10 for the whole capture: `scaleDown.stabilizationWindowSeconds: 300`
   holding capacity rather than flapping.

**Where the time goes in general.** It is not one delay, it is several stacked:

| Stage | Typical | Why |
|---|---|---|
| kubelet cAdvisor window | ~10s | CPU usage is averaged over a window; a spike is not visible until the window closes. |
| metrics-server scrape | ~15s | Default `--metric-resolution`. It polls kubelets; a fresh reading waits for the next poll. |
| HPA controller sync | ~15s | `--horizontal-pod-autoscaler-sync-period`, default 15s. The decision is only reconsidered each tick. |
| Pod start | ~10-30s | Scheduling, image pull (fast here: `IfNotPresent` and the image is already on the node), then the `startupProbe` at `failureThreshold: 30, periodSeconds: 2`. |

Our measured 37s is the fast end of that range, because the image was already on
the node. On a real cluster a first pull of the backend image (75 MB compressed)
adds tens of seconds to every new node's first pod. Our
`behavior.scaleUp.stabilizationWindowSeconds: 0` removes one more delay that
would otherwise be added on top.

**What would reduce it.** In rough order of effect for effort:

1. **Lower the utilisation target** (60% → 50%). Does not shorten the lag at
   all; it starts the clock earlier, which is usually what people actually want.
2. **Shrink the startup path.** The `startupProbe` can allow up to 60s. Our app
   starts in about 2s, so most pods are ready on the first or second probe —
   but `periodSeconds: 2` means up to 2s of pure waiting. Worth 1–2s, not more.
3. **Tighten `--metric-resolution` on metrics-server** to 10s. Buys ~5s at the
   cost of more kubelet load.
4. **Scale on a leading indicator instead of CPU.** CPU is a *lagging* signal —
   it rises after the queue has already built. Requests-per-second or queue
   depth via KEDA would react to load arriving rather than to its effect.
5. **Keep warm capacity.** `minReplicas: 2` already does some of this.

**The lesson.** For the whole of that lag, the traffic is being served by the
pods you already had. Autoscaling protects you from sustained load, not from a
spike — which is why it is not a substitute for capacity planning, and why
`minReplicas` matters more than `maxReplicas` for user-visible latency.

---

## 6. Why VPA is in Off mode **[MEASURE the recommendation]**

**Why Off.** VPA in `Auto` and an HPA scaling on CPU act on opposite sides of
the same fraction, and they oscillate:

```
VPA (Auto) sees a busy pod and RAISES resources.requests.cpu
  -> HPA's utilisation = usage / request  FALLS, on identical real load
  -> HPA reads low utilisation and SCALES IN
  -> fewer pods carry the same traffic, so per-pod usage RISES
  -> VPA sees busy pods and raises the request again
  -> ... and the cycle repeats
```

Neither controller is wrong on its own terms. The HPA's denominator is the
VPA's output, so the VPA is continuously moving the ground the HPA measures
against. The visible result is replica count and pod size both thrashing while
the actual offered load is flat — and every oscillation costs a pod restart,
because VPA in `Auto` mode resizes by *evicting*.

`updateMode: "Off"` breaks the loop by removing the feedback edge: VPA observes
and recommends, a human reads the recommendation and commits a new request, and
the HPA's denominator then stays fixed until the next deliberate change. That
is current industrial practice for exactly this reason, and the human step is
where capacity-planning judgement belongs.

**The loop we ran:**

1. **Guessed requests** (committed in `k8s/base/backend.yaml` before any
   measurement): `cpu: 100m`, `memory: 192Mi`.
2. Ran `load/k6-script.js` against the cluster.
3. `kubectl describe vpa backend-vpa -n civicpulse`:

   | | CPU | Memory |
   |---|---|---|
   | Lower Bound | **[MEASURE]** | **[MEASURE]** |
   | Target | **[MEASURE]** | **[MEASURE]** |
   | Upper Bound | **[MEASURE]** | **[MEASURE]** |

   *(paste the full output into `docs/evidence/vpa-describe.txt`)*

4. **Updated `resources.requests` to the Target** in `k8s/base/backend.yaml`,
   as a reviewed commit.
5. **Re-ran the load test. What changed about HPA behaviour: [MEASURE].**

   What to look for and explain: if the Target was *higher* than our guess, the
   same load now computes to a *lower* utilisation percentage, so the HPA scales
   out later and to fewer replicas — you get bigger, fewer pods. If it was
   *lower*, the opposite: utilisation reads higher, the HPA scales earlier and
   further, giving more, smaller pods. Either way the total CPU doing the work
   is roughly unchanged; what moved is how it is packed, and packing affects
   scheduling latency and bin-packing efficiency on the nodes.

---

## 7. `internal: true` blocks outbound traffic — where does that leave the LLM call?

**The conflict.** `compose.yaml` puts `database` and `cache` on a network
declared `internal: true`, which means no route to the outside world — that is
the whole point, and it is what makes `docker compose exec frontend ping
database` fail. But `LLMTriage` has to reach `api.groq.com`, and the backend is
the service that calls it.

**What we did.** The backend joins **both** networks:

```yaml
backend:
  networks:
    - edge        # can reach the internet, and the frontend can reach it
    - internal    # can reach the database and the cache
```

It is the single bridge between the two segments, and it is the only service
that needs to be one. `database` and `cache` stay on `internal` alone, and
`frontend` stays on `edge` alone — so the property that actually matters
(*the internet-facing component has no route to the data*) is preserved.

**The honest cost.** The bridge is also the blast radius. If the backend is
compromised, the attacker has both the database and outbound internet in one
process — which is the classic exfiltration path. We have accepted that, and the
mitigations are ordinary rather than clever: the container runs as a non-root
user with `readOnlyRootFilesystem: true` and all capabilities dropped, and the
only outbound call it makes is to a single configured base URL.

**Two defensible alternatives we rejected:**

1. **An egress proxy on `edge`.** Backend stays `internal`-only and sends LLM
   requests through a forward proxy that is allowed to reach exactly
   `api.groq.com` and nothing else. Strictly better security: the backend keeps
   no general internet route, so a compromise cannot exfiltrate to an arbitrary
   host. Rejected for this assignment because it adds a fifth service and a
   second place where TLS can go wrong, for a property we can state but not
   demonstrate in a five-minute video.
2. **A separate triage worker.** The API stays `internal`-only and writes
   complaints with `status: pending_triage`; a worker on `edge` picks them up,
   calls the LLM and writes the result back. This is the right answer at scale —
   it also removes the LLM latency from the request path entirely, so the
   citizen gets an instant 201 instead of waiting several seconds. Rejected
   because it makes the response asynchronous, and the assignment's contract
   requires `POST /api/complaints` to return the category and summary in the
   201 body.

**In Kubernetes** the same property needs asserting differently, because every
pod can reach every other pod by default. `k8s/base/networkpolicy.yaml` does it
explicitly: default-deny ingress, then `postgres` and `redis` accept traffic
only from pods labelled `backend` (plus the migrate/seed Jobs). **Note this only
holds if your CNI enforces NetworkPolicy** — k3d's default Flannel does **not**.
A policy that is applied but not enforced is worse than none, because it looks
like protection. Verify before you claim it:

```bash
kubectl run probe --rm -it --image=busybox:1.37 -n civicpulse --restart=Never \
  --labels=app.kubernetes.io/name=frontend -- sh -c 'nc -zvw2 postgres-client 5432'
# expect: timed out
```

---

## 8. The failure that cost more than an hour **[WRITE YOUR OWN]**

> This must be your own. Below is the one from building this repository, in the
> format the question asks for — symptoms, what we wrongly believed first, and
> the exact line that told us the truth. Replace it with yours if a different
> failure cost you the hour.

**Symptoms.** Every test that touched the database errored in fixture setup with
`sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) near "(": syntax
error`. Twenty-eight tests, all in `conftest`'s `engine` fixture, all at
`Base.metadata.create_all`. The pure-logic tests passed, which made it look like
a test-infrastructure problem rather than a schema one.

**What we wrongly believed first.** That the CHECK constraints were at fault. The
error pointed at a parenthesis, the constraints were the only expressions with
parentheses we had hand-written, and `char_length()` is genuinely a Postgres
function that SQLite does not have. We changed both constraints to `length()`,
which is valid on both — and the error did not change at all. That should have
been the clue, and instead we spent the next while assuming the fix had not
applied properly.

**The exact line that told us the truth.** Dumping the generated DDL rather than
reading the error:

```python
print(CreateTable(Complaint.__table__).compile(dialect=sqlite.dialect()))
```

which printed

```
id CHAR(32) DEFAULT gen_random_uuid() NOT NULL,
```

SQLite requires an expression default to be parenthesised — `DEFAULT (expr)` —
so it fails at the parser, on the `(` of `gen_random_uuid()`, before it ever
reaches the CHECK constraints further down. The error was pointing at a
different parenthesis than the one we assumed.

**The fix, and why it is better than a workaround.** We removed
`server_default=sa.text("gen_random_uuid()")` from the model entirely rather
than making it conditional on dialect. The model describes what the application
writes, and the application always writes an explicit `uuid.uuid4()`. The
server-side default belongs in `alembic/versions/0001_initial_schema.py`, which
is the only thing that emits DDL and only ever runs against Postgres. The fix
made the layering *more* correct, not less.

**What we would do differently.** Read the generated artifact before theorising
about the error message. The DDL dump took thirty seconds and would have ended
this in the first five minutes.

---

## Index justification

Both indexes in `backend/alembic/versions/0001_initial_schema.py`, each with the
query it serves. An unexplained index is cargo cult.

**`ix_complaints_status_priority` on `(status, priority)`**

Serves the dashboard's filtered view — the hot read path, hit on every operator
page load:

```sql
SELECT * FROM complaints
WHERE status = :status AND priority = :priority
ORDER BY created_at DESC
LIMIT :page_size OFFSET :offset;
```

Built by `ComplaintRepository.list()`. Column order matters: `status` first
because it is the more selective and far more commonly used filter on its own
(an operator filters to `open` constantly and to a specific priority rarely). A
composite index serves a prefix of its columns, so `(status, priority)` also
serves a `status`-only query; `(priority, status)` would not serve a
`status`-only query at all.

**`ix_complaints_created_at` on `created_at`**

Serves the unfiltered first page, which is the default dashboard view and what
the seed demo shows:

```sql
SELECT * FROM complaints ORDER BY created_at DESC LIMIT 10 OFFSET 0;
```

Without it this is a full scan plus a sort on every page load. It also serves
any future time-window aggregate ("complaints this week") on `/api/stats`.

**A third, `ix_complaints_content_hash`**, is not one of the two required but is
load-bearing: it turns the seed's idempotency check
(`ComplaintRepository.get_by_content_hash`) from a full scan per row — 36 scans
on every seed run — into 36 index lookups.

---

## Image sizes (measured)

Measured on 2026-09-28 by summing `docker history` layers, which is the image's
real content. `docker image ls` reported the frontend as 78.3 MB, but that
figure comes from Docker 29's containerd store and counts the compressed blobs
*as well as* the unpacked layers, so it overstates what the image contains.

| Image | Final stage | Of which ours | Compressed (as pushed to GHCR) |
|---|---|---|---|
| `civicpulse-frontend` | **53.2 MB** | 0.6 MB on top of `nginx:1.27-alpine` (52.6 MB) | 21.0 MB |
| `civicpulse-backend` | 248.0 MB | venv + app on top of `python:3.12-slim-bookworm` | 75.3 MB |

The frontend clears the spec's ~60 MB bar, which is the evidence that the
multi-stage split works: the build stage holds Node, `node_modules` and the
TypeScript source (hundreds of MB), and none of it reaches the runtime image.
CI checks this directly (`ci.yml` → *Assert no Node toolchain in the frontend
runtime image*).

`docker history` also caught a mistake. An earlier Dockerfile ran
`apk add gettext=0.22.5-r0` to get `envsubst`, but the nginx base image already
ships it. That added 2.94 MB for nothing, and pinning an exact Alpine package
revision would have broken the build as soon as Alpine published the next one.
It is removed now.

## Build context sizes (measured)

`.dockerignore` in each build context, with before and after:

| Context | Without `.dockerignore` | With | Reduction |
|---|---|---|---|
| `frontend/` | 122 MB | 272 KB | ~460x |
| `backend/` | 60 MB | 198 KB | ~310x |

The frontend number is almost entirely `node_modules` (122 MB of the 122 MB),
which `npm ci` rebuilds from the lockfile inside the builder stage anyway —
copying it in would both slow every build and defeat the multi-stage split. The
backend number is dominated by `.pytest_cache`, `.mypy_cache`, `.ruff_cache` and
`__pycache__`, none of which belong in an image.

Reproduce with:

```bash
du -sh frontend backend
du -sh --exclude=node_modules --exclude=dist --exclude=tests --exclude=.git frontend
du -sh --exclude=.pytest_cache --exclude=.mypy_cache --exclude=.ruff_cache --exclude=tests backend
```

---

## Why Redis needs a volume when a cache can be rebuilt

Because this Redis does **two** jobs, and only one of them is a cache.

| Job | Disposable? |
|---|---|
| Read-through cache for `/api/stats` | **Yes.** Losing it costs one slower request; the next MISS rebuilds it from Postgres. |
| Distributed rate-limiter counters | **No.** These are the live state of a security control. |

Losing the counters is not a cache miss, it is a **quota reset**. Every client
gets a fresh allowance the instant Redis restarts — and a restart is exactly
what happens during a redeploy, a node drain, or an OOM kill, which are also
exactly the moments an abusive client would notice and exploit. The control
fails *open*.

So: `appendonly yes` with `appendfsync everysec` on a named volume
(`redisdata`). Losing up to one second of counter increments on an unclean
shutdown is acceptable; losing all of them is not.

The related choice is `maxmemory-policy noeviction` rather than `allkeys-lru`.
Under memory pressure an LRU policy evicts whatever is coldest — quite possibly
a rate-limit counter for a client who is pacing themselves, which resets their
quota. Refusing writes is the safer failure: `/api/stats` degrades to a
permanent MISS (the service handles a cache write failure without a 500) and the
limiter keeps counting accurately.

---

## Why TTL *and* explicit invalidation on `/api/stats`

Either alone looks sufficient. Neither is.

- **TTL alone is wrong** because a write makes the cached value incorrect
  *immediately*. A citizen who submits a complaint and opens the dashboard would
  watch a stale total for up to 30 seconds and reasonably conclude their report
  was lost.
- **Explicit invalidation alone is wrong** because it only covers writes *this
  process knows about*. The seed script, a `psql` session, a future second
  service, or any write path we forget to hook, all leave a permanently stale
  key with no expiry to save it.

Together: correct immediately after our own writes, and self-healing within 30
seconds after anybody else's. `StatsService` (`backend/app/services/stats_service.py`)
implements both; `ComplaintService.submit` and `ComplaintService.change_status`
each call `stats.invalidate()`, and `backend/tests/test_cache_and_limits.py`
asserts both invalidation paths.
