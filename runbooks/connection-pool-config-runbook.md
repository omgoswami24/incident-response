# Runbook: Site-Wide Timeouts / DB Connection Pool Undersized

**Applies to alerts:** site-wide `504` rate spike, rising request queue depth across services (not scoped to one endpoint).

## Diagnosis

1. Because the impact is site-wide rather than scoped to one endpoint (contrast with the checkout-slow-query runbook), suspect an infrastructure/config regression rather than an application code path.
2. Compare the current DB connection pool size against its historical baseline — a config value slashed well below normal (e.g. 50 → 5) will cause request queuing under any real load, manifesting as broad timeouts.
3. Diff recent commits to config files for pool-size constants; a staging/dev override value accidentally merged to the production config path is a common cause.

## Mitigation

1. Revert the pool size to its established baseline immediately — this is the highest-severity, broadest-blast-radius class of incident in this system.
2. Restart affected app server instances to pick up the reverted pool size (connection pools are typically sized at process start).
3. Monitor request queue depth and `504` rate closely during recovery; confirm both return to baseline before standing down.

## Prevention

- Gate config changes to production-critical values (pool sizes, timeouts) behind an explicit environment check or a stricter review requirement than routine code changes.
