"""Rolling in-memory metrics for the target app's live traffic.

The load generator records one sample per request; the anomaly detector, the
remediation verifier, the impact estimator, and the dashboard charts all read
windows over this same store. Nothing in here knows about fault scenarios —
it's plain observability data.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass

ENDPOINT_GROUPS = [
    "GET /products",
    "GET /products/{id}",
    "POST /checkout/summary",
    "POST /webhooks/payments",
]


@dataclass(frozen=True)
class Sample:
    ts: float
    group: str
    latency_ms: float
    status: int


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


class MetricsStore:
    def __init__(self, max_samples: int = 100_000):
        self._samples: deque[Sample] = deque(maxlen=max_samples)
        self._error_bodies: deque[tuple[float, str, str]] = deque(maxlen=50)
        self._lock = threading.Lock()

    def record(
        self, group: str, latency_ms: float, status: int, error_body: str | None = None
    ) -> None:
        now = time.time()
        with self._lock:
            self._samples.append(Sample(now, group, latency_ms, status))
            if error_body:
                self._error_bodies.append((now, group, error_body[:160]))

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
            self._error_bodies.clear()

    def _window(self, seconds: float) -> list[Sample]:
        cutoff = time.time() - seconds
        with self._lock:
            return [s for s in self._samples if s.ts >= cutoff]

    def group_stats(self, seconds: float) -> dict[str, dict]:
        """Per endpoint-group stats over the trailing window."""
        by_group: dict[str, list[Sample]] = {}
        for s in self._window(seconds):
            by_group.setdefault(s.group, []).append(s)

        stats: dict[str, dict] = {}
        for group, rows in by_group.items():
            latencies = [r.latency_ms for r in rows]
            errors = [r for r in rows if r.status >= 500]
            stats[group] = {
                "count": len(rows),
                "rps": round(len(rows) / seconds, 1),
                "p50_ms": round(percentile(latencies, 0.50), 1),
                "p95_ms": round(percentile(latencies, 0.95), 1),
                "error_rate_pct": round(100 * len(errors) / len(rows), 1),
            }
        return stats

    def recent_error_samples(self, seconds: float = 60) -> list[dict]:
        """Snippets of recent 5xx response bodies — real diagnostic signal
        (e.g. pool-exhaustion 503s name the pool in their detail message)."""
        cutoff = time.time() - seconds
        with self._lock:
            return [
                {"group": group, "body": body}
                for ts, group, body in self._error_bodies
                if ts >= cutoff
            ]

    def series(self, seconds: float = 240, bucket_s: float = 5) -> dict[str, list[dict]]:
        """Bucketed p95/error-rate time series per group, for the dashboard."""
        now = time.time()
        start = now - seconds
        n_buckets = int(seconds / bucket_s)

        grouped: dict[tuple[str, int], list[Sample]] = {}
        for s in self._window(seconds):
            idx = int((s.ts - start) / bucket_s)
            if 0 <= idx < n_buckets:
                grouped.setdefault((s.group, idx), []).append(s)

        out: dict[str, list[dict]] = {}
        for group in {g for g, _ in grouped}:
            buckets = []
            for i in range(n_buckets):
                rows = grouped.get((group, i), [])
                latencies = [r.latency_ms for r in rows]
                errors = [r for r in rows if r.status >= 500]
                buckets.append(
                    {
                        "t": round(start + i * bucket_s),
                        "count": len(rows),
                        "p95_ms": round(percentile(latencies, 0.95), 1),
                        "error_rate_pct": (
                            round(100 * len(errors) / len(rows), 1) if rows else 0.0
                        ),
                    }
                )
            out[group] = buckets
        return out


store = MetricsStore()
