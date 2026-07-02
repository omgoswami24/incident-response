import random

from app.seed.fault_scenarios import FaultScenario


def estimate_impact(scenario: FaultScenario) -> dict:
    """Pure mock: jitter a plausible snapshot from the scenario's seeded
    impact_profile. No LLM call — keeps this step instant."""
    profile = scenario.impact_profile
    return {
        "affected_users_pct": round(random.uniform(*profile.affected_users_pct_range), 1),
        "revenue_at_risk_per_hr_usd": random.randint(*profile.revenue_at_risk_per_hr_range),
        "p95_latency_ms": random.randint(*profile.p95_latency_ms_range),
        "error_rate_pct": round(random.uniform(*profile.error_rate_pct_range), 1),
        "severity": profile.severity,
    }
