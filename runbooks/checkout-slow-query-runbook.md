# Runbook: Checkout Latency / Slow Query

**Applies to alerts:** `checkout_p95_latency_ms` high, DB connection pool exhaustion during checkout.

## Diagnosis

1. Check APM for query counts on `/api/checkout` — a spike in per-request query count (vs. a flat baseline) points to a batching regression rather than raw traffic growth.
2. Pull the last 15 commits touching the checkout code path and diff for query-shape changes: a loop calling a single-item lookup function where a batched lookup used to be is the classic signature of an accidental N+1.
3. Confirm DB connection pool utilization correlates with the checkout endpoint specifically, not site-wide (site-wide points to a different root cause — see the connection-pool-config runbook instead).

## Mitigation

1. Revert the offending commit, or patch the endpoint to use the batched lookup function again.
2. If an immediate revert isn't safe, scale the DB connection pool size as a stopgap while the fix is prepared.
3. Redeploy and confirm `checkout_p95_latency_ms` returns to baseline (< 800ms) within one deploy cycle.

## Prevention

- Add a query-count assertion to checkout integration tests so a per-item loop regression fails CI.
