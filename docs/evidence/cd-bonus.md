# CD bonus evidence

All three items run on **every** CD run; nothing below was done by hand.
Captured from [CD run 36562054653](https://github.com/i222641-byte/SCD_A1/actions/runs/36562054653) (commit `cc23dc2`, all 4 jobs green).

## 1. Deploy by image digest, Cosign-signed and verified (+3)

`build-push` signs both images keyless by digest; `deploy-k8s` verifies them against this workflow's identity (`https://github.com/<repo>/.github/workflows/cd.yml@<ref>`, issuer `token.actions.githubusercontent.com`) before applying anything:

```
== ghcr.io/i222641-byte/scd_a1/civicpulse-backend@sha256:92b6f923dce9481f03339f6a3c93abc7e5681d9da538a444d9a21e8e347d8646
The following checks were performed on each of these signatures:
  - The cosign claims were validated
  - Existence of the claims in the transparency log was verified offline
  - The code-signing certificate was verified using trusted certificate authority certificates
== ghcr.io/i222641-byte/scd_a1/civicpulse-frontend@sha256:858368e2d6b9724874698d2a8b82424a1998b1ae793b9fec979f713e4d7a697d
The following checks were performed on each of these signatures: (same three checks)
```

What was then deployed (`kustomize build` of the pinned overlay; the step fails if any tag reference remains):

```
image: ghcr.io/i222641-byte/scd_a1/civicpulse-backend@sha256:92b6f923dce9481f03339f6a3c93abc7e5681d9da538a444d9a21e8e347d8646
image: ghcr.io/i222641-byte/scd_a1/civicpulse-frontend@sha256:858368e2d6b9724874698d2a8b82424a1998b1ae793b9fec979f713e4d7a697d
```

## 2. Zero-downtime rolling update under live load (+4)

`load/k6-rolling.js` offers a constant 20 req/s through the Ingress; 20 s in, `kubectl rollout restart` replaces **every** backend and frontend pod. The threshold is `http_req_failed rate==0`, and the step fails if the load finished before the rollout did.

```
rollout finished at 11:35:16   (load still running: checked)
✓ status is 200
http_req_failed................: 0.00%  0 out of 3001
http_reqs......................: 3001   20.00599/s
latency p95 5.5 ms, max 73.8 ms
```

**3,001 requests, 0 failed.** What makes it hold: `maxUnavailable: 0` plus readiness probes (capacity never dips), a `preStop` sleep on both Deployments (the pod keeps serving while ingress-nginx drops its endpoint), and the SIGTERM drain in `backend/app/main.py`. The k6 log and summary are uploaded as the run's `zero-downtime-rollout` artifact.

## 3. GitOps: Argo CD reconciling the cluster from the repository (+4)

A second ephemeral cluster. The only thing applied is `k8s/argocd/application.yaml` (path `k8s/overlays/gitops`, pinned to the commit and the signed digests); Argo CD v3.5.3 does the rest, in sync waves: ConfigMap → Postgres/Redis → migrate Job (Sync hook) → the rest.

```
11:34:25 sync=OutOfSync health=Progressing
11:34:45 sync=Synced    health=Progressing
11:35:05 sync=Synced    health=Degraded     <- HPA waiting for its first metrics window
11:35:15 sync=Synced    health=Healthy
synced revision: cc23dc284a7f73c71cd5cc5b7cd5b0a054966a67   (asserted == the commit under test)
```

Self-heal: drift introduced by hand, reverted from git:

```
frontend replicas in git: 2
--- drift 1: scale the frontend by hand to 5
11:35:16 spec.replicas=5
11:35:18 spec.replicas=2
--- drift 2: delete the frontend Service
both drifts reverted by Argo CD      (Service recreated; page served through the Ingress again)
```
