"""Summarise k6's --summary-export for the zero-downtime rollout (cd.yml).

    python scripts/rolling_summary.py rolling-summary.json
"""
from __future__ import annotations

import json
import sys


def main(path: str) -> None:
    metrics = json.load(open(path))["metrics"]
    total = int(metrics["http_reqs"]["count"])
    failed_rate = metrics["http_req_failed"]["value"]
    duration = metrics["http_req_duration"]
    print("### Zero-downtime rolling update")
    print(f"- requests during the rollout window: **{total}**")
    print(f"- failed: **{round(failed_rate * total)}** (rate {failed_rate})")
    print(f"- latency p95 {duration['p(95)']:.1f} ms, max {duration['max']:.1f} ms")


if __name__ == "__main__":
    main(sys.argv[1])
