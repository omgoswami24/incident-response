"""Estimates business impact from measured traffic, not canned numbers.

Inputs are the frozen healthy baseline and the degraded detection window that
were captured on the incident when the detector fired. The only assumption is
a business constant (average order value, configurable); throughput, error
rates, and latency inflation are all measured from live traffic.
"""

import json

from app.config import settings
from app.models import Incident

CHECKOUT = "POST /checkout/summary"
WEBHOOK = "POST /webhooks/payments"

# Fractions of revenue-bearing requests assumed lost to latency-driven
# abandonment. Hard errors always count fully.
ABANDONMENT_AT_2X = 0.10
ABANDONMENT_AT_3X = 0.25


def estimate_impact(incident: Incident) -> dict:
    baseline: dict = json.loads(incident.baseline_json or "{}")
    current: dict = json.loads(incident.detection_stats_json or "{}")

    degraded: dict[str, dict] = {}
    total_rps = sum(s["rps"] for s in current.values()) or 1.0
    degraded_rps = 0.0
    for group, cur in current.items():
        base = baseline.get(group)
        if not base:
            continue
        latency_ratio = cur["p95_ms"] / max(base["p95_ms"], 0.1)
        error_delta = cur["error_rate_pct"] - base["error_rate_pct"]
        if latency_ratio >= 2 or error_delta >= 5:
            degraded[group] = {
                "p95_ms": cur["p95_ms"],
                "baseline_p95_ms": base["p95_ms"],
                "latency_ratio": round(latency_ratio, 1),
                "error_rate_pct": cur["error_rate_pct"],
                "rps": cur["rps"],
            }
            degraded_rps += cur["rps"]

    revenue_at_risk_per_hr = 0.0
    for group in (CHECKOUT, WEBHOOK):
        info = degraded.get(group)
        if not info:
            continue
        if info["latency_ratio"] >= 3:
            abandonment = ABANDONMENT_AT_3X
        elif info["latency_ratio"] >= 2:
            abandonment = ABANDONMENT_AT_2X
        else:
            abandonment = 0.0
        failure_fraction = min(1.0, info["error_rate_pct"] / 100 + abandonment)
        revenue_at_risk_per_hr += (
            info["rps"] * 3600 * failure_fraction * settings.avg_order_value_usd
        )

    payments_broken = WEBHOOK in degraded and degraded[WEBHOOK]["error_rate_pct"] >= 5
    if payments_broken or len(degraded) >= 3:
        severity = "critical"
    elif CHECKOUT in degraded:
        severity = "high"
    elif degraded:
        severity = "medium"
    else:
        severity = "low"

    return {
        "severity": severity,
        "degraded_endpoints": degraded,
        "affected_traffic_pct": round(100 * degraded_rps / total_rps, 1),
        "requests_affected_per_hr": round(degraded_rps * 3600),
        "est_revenue_at_risk_per_hr_usd": round(revenue_at_risk_per_hr),
        "method": (
            "Measured from live traffic (detection window vs learned baseline); "
            f"revenue extrapolated with avg order value ${settings.avg_order_value_usd:.0f} "
            "and latency-abandonment factors."
        ),
    }
