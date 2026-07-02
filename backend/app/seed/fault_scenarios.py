from dataclasses import dataclass


@dataclass(frozen=True)
class ImpactProfile:
    affected_users_pct_range: tuple[float, float]
    revenue_at_risk_per_hr_range: tuple[int, int]
    p95_latency_ms_range: tuple[int, int]
    error_rate_pct_range: tuple[float, float]
    severity: str  # low | medium | high | critical


@dataclass(frozen=True)
class FaultScenario:
    id: str
    title: str
    alert_description: str
    target_commit_message: str
    impact_profile: ImpactProfile
    runbook_filename: str


FAULT_SCENARIOS: dict[str, FaultScenario] = {
    "checkout-n-plus-one": FaultScenario(
        id="checkout-n-plus-one",
        title="Checkout N+1 query",
        alert_description=(
            "ALERT: checkout_p95_latency_ms > 3000 for 5m, scoped to /api/checkout only "
            "(all other endpoints nominal, DB pool size unchanged). "
            "checkout_db_queries_per_request up ~5x vs baseline over the same window."
        ),
        target_commit_message="perf: fetch product details individually during checkout summary",
        impact_profile=ImpactProfile(
            affected_users_pct_range=(8, 15),
            revenue_at_risk_per_hr_range=(15_000, 40_000),
            p95_latency_ms_range=(3000, 6000),
            error_rate_pct_range=(2, 6),
            severity="high",
        ),
        runbook_filename="checkout-slow-query-runbook.md",
    ),
    "cache-ttl-misconfigured": FaultScenario(
        id="cache-ttl-misconfigured",
        title="Cache TTL misconfigured",
        alert_description=(
            "ALERT: product_catalog_api_latency_ms p95 > 1200 for 10m, scoped to "
            "GET /products (checkout query volume unchanged — no checkout code path "
            "involved). Cache hit rate for the catalog cache dropped from ~92% to <20% "
            "with no corresponding deploy of catalog query logic, which points to a "
            "config-only regression (e.g. a cache TTL value) rather than a code change. "
            "DB CPU utilization > 90% as a downstream effect of the cache misses."
        ),
        target_commit_message="chore: tune cache TTL for product catalog",
        impact_profile=ImpactProfile(
            affected_users_pct_range=(30, 60),
            revenue_at_risk_per_hr_range=(3_000, 9_000),
            p95_latency_ms_range=(800, 2000),
            error_rate_pct_range=(1, 3),
            severity="medium",
        ),
        runbook_filename="cache-ttl-runbook.md",
    ),
    "null-pointer-payment-webhook": FaultScenario(
        id="null-pointer-payment-webhook",
        title="Payment webhook null pointer",
        alert_description=(
            "ALERT: payment_webhook_5xx_rate > 15% for 5m. "
            "Orders stuck in pending_payment status rising sharply."
        ),
        target_commit_message="refactor: simplify charge webhook handler",
        impact_profile=ImpactProfile(
            affected_users_pct_range=(2, 6),
            revenue_at_risk_per_hr_range=(20_000, 60_000),
            p95_latency_ms_range=(200, 500),
            error_rate_pct_range=(15, 40),
            severity="critical",
        ),
        runbook_filename="payment-webhook-null-pointer-runbook.md",
    ),
    "connection-pool-config-rollout": FaultScenario(
        id="connection-pool-config-rollout",
        title="DB connection pool slashed",
        alert_description=(
            "ALERT: site_wide_504_rate > 10% for 5m. "
            "Request queue depth climbing across all services."
        ),
        target_commit_message="config: apply staging pool size override",
        impact_profile=ImpactProfile(
            affected_users_pct_range=(60, 100),
            revenue_at_risk_per_hr_range=(50_000, 120_000),
            p95_latency_ms_range=(4000, 10000),
            error_rate_pct_range=(10, 25),
            severity="critical",
        ),
        runbook_filename="connection-pool-config-runbook.md",
    ),
}
