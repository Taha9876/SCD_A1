# Runbook

Operational procedures for CivicPulse. Written to be followed at 3am by someone
who did not write the code.

---

## Deploy

### Normal path — automatic

A merge to `main` triggers `.github/workflows/cd.yml`, which retests the merged
result, builds and pushes SHA-tagged images to GHCR, then deploys to a cluster,
runs migrations, waits on rollout status and smoke-tests through the Ingress.
Nothing is pressed by a human after the PR approval.

Watch it: **Actions → CD → the run for your commit.** The run summary carries
the image digests that were actually deployed.

### Manual deploy of a specific commit

Never deploy `:latest`. Always name a commit SHA.

```bash
export SHA=<the 40-character commit sha>
export REPO=<owner>/<repo>        # lowercase

cd k8s/overlays/prod
kustomize edit set image \
  ghcr.io/OWNER/REPO/civicpulse-backend=ghcr.io/$REPO/civicpulse-backend:$SHA
kustomize edit set image \
  ghcr.io/OWNER/REPO/civicpulse-frontend=ghcr.io/$REPO/civicpulse-frontend:$SHA

# Check what you are about to apply BEFORE applying it.
kustomize build . | grep 'image:'

cd ../../..
kustomize build k8s/overlays/prod > /tmp/prod.yaml

# 1. Data layer first.
kubectl apply -f /tmp/prod.yaml --selector app.kubernetes.io/component=database
kubectl apply -f /tmp/prod.yaml --selector app.kubernetes.io/component=cache
kubectl -n civicpulse rollout status statefulset/postgres --timeout=240s

# 2. Migrations as a single Job, waited on. Never as an initContainer:
#    with 2 replicas that runs concurrently and deadlocks on the version table.
kubectl apply -f /tmp/prod.yaml --selector app.kubernetes.io/name=migrate
kubectl -n civicpulse wait --for=condition=complete job/civicpulse-migrate --timeout=180s

# 3. Everything else.
kubectl apply -f /tmp/prod.yaml
kubectl -n civicpulse rollout status deployment/backend --timeout=300s
```

**Do not commit the `kustomize edit` change.** The repository keeps its
placeholder so CI remains the source of truth for what is deployed.

### Local, one command

```bash
cp .env.example .env    # then edit POSTGRES_PASSWORD
docker compose up -d --build
open http://localhost:8080
```

Migrations and the seed run automatically in the one-shot `migrate` job before
the backend starts. If the backend never becomes healthy, check that job first:

```bash
docker compose ps -a migrate          # expect: Exited (0)
docker compose logs migrate           # the alembic and seed output
```

---

## Roll back

Two mechanisms. Use the first during an incident, the second once the fire is
out.

### 1. `kubectl rollout undo` — fast, imperative, the 3am answer

```bash
kubectl -n civicpulse rollout undo deployment/backend
kubectl -n civicpulse rollout status deployment/backend --timeout=180s
```

About thirty seconds. Kubernetes still has the previous ReplicaSet with its pod
spec, so this needs no registry lookup, no CI run and no repository access.

**Use it when:** the site is down or erroring and you need it working now.

**Its cost:** the cluster now disagrees with `main`. Nothing in Git records that
you did this, and the *next* deploy from `main` will silently reinstate the bad
version. So this buys time; it does not finish the job.

Target a specific revision instead of the previous one:

```bash
kubectl -n civicpulse rollout history deployment/backend
kubectl -n civicpulse rollout undo deployment/backend --to-revision=3
```

### 2. Re-apply the previous SHA — declarative, auditable, the correct answer

```bash
git log --oneline -10 main          # find the last good commit
export SHA=<last good sha>
# then the manual deploy procedure above, with that SHA
```

**Use it when:** the immediate fire is out, or the bad deploy has not yet caused
an outage. This leaves the cluster and the repository in agreement, and the
deploy is reproducible from the SHA by anyone.

**Follow either with:** a revert PR on `main`, so the next automatic deploy does
not reinstate the problem.

### Rolling back a migration

Rolling back the *application* does not roll back the *schema*, and this is
where rollbacks go wrong. If the bad release included a migration:

```bash
kubectl -n civicpulse run migrate-down --rm -it --restart=Never \
  --image=ghcr.io/$REPO/civicpulse-backend:$SHA \
  --env="DATABASE_URL=$DATABASE_URL" \
  --command -- alembic downgrade -1
```

Check first that the previous application version can actually read the current
schema. An additive migration (a new nullable column) is usually fine to leave
in place; a destructive one (a dropped or renamed column) is not, and the older
code will error on every query. Prefer leaving an additive migration applied.

---

## Read the logs

Logs are **JSON on stdout**, never a file — a container filesystem is ephemeral.
Every line carries a `request_id` propagated from `X-Request-ID`.

```bash
# Compose
docker compose logs -f backend

# Kubernetes, all replicas at once
kubectl -n civicpulse logs -f -l app.kubernetes.io/name=backend --all-containers --max-log-requests=10

# Pretty, if you have jq
kubectl -n civicpulse logs -l app.kubernetes.io/name=backend --tail=200 | jq -c 'select(.level != "DEBUG")'
```

**Follow one request across the whole system.** This is the point of the
request id:

```bash
# Client side: send your own id
curl -H 'X-Request-ID: debug-me-123' http://localhost:8000/api/complaints

# Then find everything that happened under it
kubectl -n civicpulse logs -l app.kubernetes.io/name=backend --tail=1000 \
  | jq -c 'select(.request_id == "debug-me-123")'
```

**Useful filters:**

```bash
# Every triage fallback, with the error class that caused it
... | jq -c 'select(.event == "triage.fallback")'

# Readiness failures, with the dependency that failed
... | jq -c 'select(.event == "ready.fail")'

# Slow requests
... | jq -c 'select(.duration_ms > 1000)'
```

Probe traffic (`/health`, `/ready`, `/metrics`) logs at DEBUG so it does not
bury real lines. Raise `LOG_LEVEL=DEBUG` only while investigating.

---

## When triage starts failing

**Symptom:** complaints come back with `triaged_by: "rules:fallback"`, the
dashboard shows amber provider badges, and `civicpulse_triage_fallback_total` is
climbing.

The system is **working as designed** — citizens are still getting 201s and
their complaints are still being categorised, just less well. This is a degraded
service, not an outage. Do not page anyone at 3am for it.

### 1. Find out what is actually failing

```bash
curl -s http://localhost:8000/api/meta/providers | jq
```

The `recent` array is the last 20 triage outcomes with a `provider`,
`latency_ms`, `fallback` flag and `error_class`. The error class names the
cause:

| `error_class` | Meaning | Action |
|---|---|---|
| `TriageRateLimited` | Provider returned 429. | Free-tier quota exhausted. See below. |
| `TriageTimeout` | Exceeded the 10s cap. | Provider is slow or the network is bad. Usually transient. |
| `TriageUpstreamError` | 5xx or a connection error. | Provider-side outage. Check their status page. |
| `TriageBadRequest` | 4xx other than 429. | **Ours.** Bad key, wrong model name, malformed request. Not transient — it will not fix itself. |
| `TriageInvalidOutput` | Answered, but failed schema validation. | The model is returning prose or an invented category. Check the prompt and the model name. |

### 2. Act on the cause

**`TriageRateLimited` — quota exhausted.**

```bash
# What is the hit rate? A low one means we are spending quota on duplicates.
curl -s http://localhost:8000/api/meta/providers | jq .triage_cache
```

- Check the provider's live limits page.
- Tighten the intake limiter so the quota lasts:
  `RATE_LIMIT_REQUESTS=5`, `RATE_LIMIT_WINDOW_SECONDS=60`.
- If the hit rate is low, consider a longer `TRIAGE_CACHE_TTL_SECONDS`.
- If it will not recover today, switch provider (below).

**`TriageBadRequest` — this one is ours and will not self-heal.**

```bash
# Is the key present? (This prints whether it is set, never its value.)
kubectl -n civicpulse exec deploy/backend -- python -c \
  "from app.config import get_settings; print(get_settings().safe_dump()['llm_api_key'])"

# Is the model name still valid? Providers retire models.
kubectl -n civicpulse get configmap civicpulse-config -o jsonpath='{.data.LLM_MODEL}'
```

Rotate the key if it has expired:

```bash
kubectl -n civicpulse create secret generic civicpulse-secrets \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=LLM_API_KEY="$NEW_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n civicpulse rollout restart deployment/backend
```

### 3. Switch provider

Fastest mitigation. A ConfigMap change plus a restart:

```bash
# To keyword rules: instant, no network, no key, worse classification.
kubectl -n civicpulse patch configmap civicpulse-config \
  --type merge -p '{"data":{"TRIAGE_PROVIDER":"rules"}}'
kubectl -n civicpulse rollout restart deployment/backend

# Confirm what is now live
curl -s http://localhost:8000/api/meta/providers | jq .active_provider
```

`ollama` is the other option if that deployment has an Ollama service; it keeps
LLM-quality classification with no key and no data leaving the cluster, at the
cost of latency.

### 4. Backfill afterwards

Complaints triaged during the outage carry `triaged_by: "rules:fallback"` and
are likely mis-prioritised. There is **no backfill command** — this is a known
gap. To find them:

```sql
SELECT id, created_at, category, priority, text
FROM complaints
WHERE triaged_by = 'rules:fallback'
  AND created_at > now() - interval '24 hours'
ORDER BY created_at DESC;
```

Fallback results are deliberately **not** cached, so re-submitting the same text
will call the real provider rather than returning the degraded answer.

---

## Other common situations

### A pod will not become ready

```bash
kubectl -n civicpulse get pods
kubectl -n civicpulse describe pod <pod>
curl -s http://localhost:8000/ready | jq   # names the failed dependency
```

`/ready` returns 503 with `dependencies.database` or `dependencies.cache`
naming what is unreachable. A pod failing readiness is removed from the Service
but **not restarted** — that is correct, and it will rejoin by itself when the
dependency returns.

If it is failing *liveness* and restart-looping, the process itself is wedged —
`/health` touches nothing external, so a liveness failure is never caused by
Postgres or Redis being down.

### Everything returns 429

The rate limiter is per client IP and shared across replicas via Redis.

```bash
# What are the current limits?
kubectl -n civicpulse get configmap civicpulse-config \
  -o jsonpath='{.data.RATE_LIMIT_REQUESTS}{"/"}{.data.RATE_LIMIT_WINDOW_SECONDS}{"s\n"}'
```

If *everyone* is limited, the proxy IP is probably being counted as one client —
check `X-Forwarded-For` is reaching the backend
(`nginx.ietf.kubernetes.io/use-forwarded-headers: "true"` on the Ingress, and
`proxy_set_header X-Forwarded-For` in `frontend/nginx.conf`).

Clear one client's counter:

```bash
kubectl -n civicpulse exec deploy/redis -- redis-cli DEL "ratelimit:complaints:<ip>"
```

### Stats look stale

```bash
curl -si http://localhost:8000/api/stats | grep -i x-cache
```

`HIT` means Redis served it. A write should have invalidated the key — if a new
complaint is not appearing, check that `ComplaintService.submit` is reaching
`stats.invalidate()`. Force it:

```bash
kubectl -n civicpulse exec deploy/redis -- redis-cli DEL stats:v1
```

### Verify data survived

```bash
# Compose
docker compose down && docker compose up -d
curl -s http://localhost:8000/api/stats | jq .total

# Kubernetes: delete the Postgres pod, the PVC keeps the data
kubectl -n civicpulse delete pod postgres-0
kubectl -n civicpulse rollout status statefulset/postgres --timeout=240s
curl -s http://localhost:8000/api/stats | jq .total   # same number
```

---

## Before you submit

```bash
python scripts/check_submission.py
```

It is a lint, not a grader. It catches the mechanical failures behind most of
the automatic deductions: a credential in the history, an unpinned base image, a
`:latest` deploy, a published database port, an ungated publishing job.
