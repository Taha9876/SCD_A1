# Evidence

Screenshots and captures that prove claims made elsewhere in this repository.
Each one is a record of something the team actually did, so none can be
generated in advance. They are listed here so nothing is forgotten before
submission.

| File | What it shows | Rubric line |
|---|---|---|
| `branch-protection.png` | Settings → Branches → rule for `main`: PR required, 1 approval, status checks required, no bypass | A · main protected (3) |
| `merge-conflict.md` | The conflict markers, the resolution, the merge commit hash, and 2–4 sentences on why that version won | A · deliberate merge conflict (3) |
| `red-pipeline.png` | A PR with a deliberately failing test: the red check and the **blocked** merge button | I · red then green (1) |
| `green-pipeline.png` | The same PR after the fix, checks green, merge enabled | I · red then green (1) |
| `hpa-watch.txt` | `kubectl get hpa backend-hpa -n civicpulse -w` output during the k6 run, replicas rising | H · HPA capture (4), §5.8 item 6 |
| `hpa-scaling-chart.png` | Replicas against offered load over time, from the same run | H · HPA capture (4), §5.8 item 6 |
| `vpa-describe.txt` | `kubectl describe vpa backend-vpa -n civicpulse`: Target, Lower Bound, Upper Bound | H · VPA (3) |
| `shortlog.txt` | `git shortlog -sn` output: ≥ 35 commits, neither partner below 35 % | A · commits (3), §5.8 item 5 |

## How to capture the Kubernetes ones

```bash
# terminal 1 -- start this first, then leave it running
kubectl get hpa backend-hpa -n civicpulse -w | tee docs/evidence/hpa-watch.txt

# terminal 2
# HOST_HEADER routes through the Ingress without an /etc/hosts entry
k6 run --env BASE_URL=http://localhost:8081 --env HOST_HEADER=civicpulse.local load/k6-script.js

# after the run
kubectl describe vpa backend-vpa -n civicpulse > docs/evidence/vpa-describe.txt
git shortlog -sn > docs/evidence/shortlog.txt
```

`load/k6-script.js` explains how to read the HPA lag off these two captures,
which is the number `docs/ENGINEERING-NOTES.md` question 5 asks for.
