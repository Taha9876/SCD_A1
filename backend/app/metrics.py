"""Prometheus metrics, hand-rolled in the text exposition format.

No prometheus_client dependency: the format is twelve lines of code, and
writing it here means the histogram buckets are a visible, defensible choice
rather than a library default nobody on the team can explain.
"""
from __future__ import annotations

import threading
from collections import defaultdict

#: Seconds. Chosen around what this service actually does: sub-100ms for reads
#: off the cache, and a long tail up to the 10s triage timeout for writes.
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._req_buckets: dict[tuple[str, str], list[int]] = {}
        self._req_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._req_count: dict[tuple[str, str], int] = defaultdict(int)
        self._triage_buckets: list[int] = [0] * (len(_LATENCY_BUCKETS) + 1)
        self._triage_sum = 0.0
        self._triage_count = 0
        self._fallbacks = 0
        self._rate_limited = 0

    def observe_request(self, method: str, path: str, status: int, seconds: float) -> None:
        key = (method, path)
        with self._lock:
            self._requests[(method, path, status)] += 1
            buckets = self._req_buckets.setdefault(key, [0] * (len(_LATENCY_BUCKETS) + 1))
            _bump(buckets, seconds)
            self._req_sum[key] += seconds
            self._req_count[key] += 1

    def observe_triage(self, seconds: float, *, fallback: bool) -> None:
        with self._lock:
            _bump(self._triage_buckets, seconds)
            self._triage_sum += seconds
            self._triage_count += 1
            if fallback:
                self._fallbacks += 1

    def observe_rate_limited(self) -> None:
        with self._lock:
            self._rate_limited += 1

    def render(self) -> str:
        with self._lock:
            lines: list[str] = []

            lines.append("# HELP civicpulse_requests_total Total HTTP requests.")
            lines.append("# TYPE civicpulse_requests_total counter")
            for (method, path, status), count in sorted(self._requests.items()):
                lines.append(
                    f'civicpulse_requests_total{{method="{method}",path="{path}",'
                    f'status="{status}"}} {count}'
                )

            lines.append("# HELP civicpulse_request_duration_seconds Request latency.")
            lines.append("# TYPE civicpulse_request_duration_seconds histogram")
            for (method, path), buckets in sorted(self._req_buckets.items()):
                labels = f'method="{method}",path="{path}"'
                lines.extend(
                    _render_histogram(
                        "civicpulse_request_duration_seconds",
                        buckets,
                        self._req_sum[(method, path)],
                        self._req_count[(method, path)],
                        labels,
                    )
                )

            lines.append("# HELP civicpulse_triage_duration_seconds Triage latency.")
            lines.append("# TYPE civicpulse_triage_duration_seconds histogram")
            lines.extend(
                _render_histogram(
                    "civicpulse_triage_duration_seconds",
                    self._triage_buckets,
                    self._triage_sum,
                    self._triage_count,
                    "",
                )
            )

            lines.append(
                "# HELP civicpulse_triage_fallback_total Triage calls that fell back to rules."
            )
            lines.append("# TYPE civicpulse_triage_fallback_total counter")
            lines.append(f"civicpulse_triage_fallback_total {self._fallbacks}")

            lines.append("# HELP civicpulse_rate_limited_total Requests rejected with 429.")
            lines.append("# TYPE civicpulse_rate_limited_total counter")
            lines.append(f"civicpulse_rate_limited_total {self._rate_limited}")

            return "\n".join(lines) + "\n"


def _bump(buckets: list[int], seconds: float) -> None:
    for i, edge in enumerate(_LATENCY_BUCKETS):
        if seconds <= edge:
            buckets[i] += 1
            break
    else:
        buckets[-1] += 1


def _render_histogram(
    name: str, buckets: list[int], total: float, count: int, labels: str
) -> list[str]:
    lines: list[str] = []
    cumulative = 0
    sep = "," if labels else ""
    for i, edge in enumerate(_LATENCY_BUCKETS):
        cumulative += buckets[i]
        lines.append(f'{name}_bucket{{{labels}{sep}le="{edge}"}} {cumulative}')
    cumulative += buckets[-1]
    lines.append(f'{name}_bucket{{{labels}{sep}le="+Inf"}} {cumulative}')
    brace = f"{{{labels}}}" if labels else ""
    lines.append(f"{name}_sum{brace} {total}")
    lines.append(f"{name}_count{brace} {count}")
    return lines


metrics = Metrics()
