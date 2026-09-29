# ADR 0003: Deploy by immutable reference, never by `latest`

- Status: accepted
- Date: 2026-09-20
- Deciders: both team members

## Context

"What is production running?" must have one answer, and it must be checkable.
A moving tag cannot give that answer. `civicpulse-backend:latest` points at
different bytes on Tuesday than it did on Monday, so:

- two pods started an hour apart can run different code, with nothing in the
  cluster recording which is which;
- `kubectl rollout undo` rolls back to a pod spec naming `:latest` — which now
  resolves to the same broken image, so the rollback silently does nothing;
- a green CI run proves nothing about the image a pod actually pulled.

## Decision

**`:latest` may be pushed. It may never be deployed.**

- `cd.yml` pushes both `${{ github.sha }}` and `latest` for each image.
  `latest` exists for humans pulling by hand.
- Deployment pins the SHA. From `k8s/overlays/prod`, CI runs
  `kustomize edit set image ...civicpulse-backend=...:${{ github.sha }}`. That
  edit happens in the runner's checkout and is never committed, so the
  repository keeps its `PLACEHOLDER_SET_BY_CI` and the deploy stays reproducible
  from the SHA alone.
- `compose.prod.yaml` uses `${IMAGE_TAG:?set IMAGE_TAG to a commit SHA or
  digest}`, which **fails the command** rather than defaulting to something.
- `imagePullPolicy: IfNotPresent` is only safe *because* the tag is immutable.
  With `:latest` it would be actively wrong.
- `scripts/check_submission.py` fails if `:latest` appears near a
  `kubectl apply` or `kustomize edit set image` line, in `compose.prod.yaml`, or
  in any `image:` / `newTag:` field under `k8s/`.

The bonus step is the digest rather than the tag. A tag is still a mutable
pointer *at the registry*; a digest is content-addressed and cannot be
repointed. `cd.yml` already captures `steps.backend.outputs.digest` as a job
output and prints it to the run summary, so the switch is a one-line change to
the `kustomize edit set image` argument.

## Consequences

**Good.** `git show <sha>` shows exactly the source running in production.
Rollback is real: the previous ReplicaSet names a different, still-existing
image. The run summary of every `cd.yml` run is an audit record.

**Bad.** Tags accumulate in GHCR, one per commit to main. A retention policy is
needed eventually; we have not written one.

**Bad.** Nobody can deploy by hand without knowing a SHA. That is the intended
friction, and it is why `docs/RUNBOOK.md` spells out the exact command with the
substitution written out.

## Alternatives rejected

- **Semver tags for deploys.** Right for consumers of a released artifact,
  wrong for continuous deployment: not every commit to main warrants a version
  bump, and `v1.4` is still a moving pointer.
- **`imagePullPolicy: Always` with `:latest`.** Makes every pod restart a
  surprise upgrade, and still leaves rollback broken.
