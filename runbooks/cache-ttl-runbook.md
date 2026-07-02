# Runbook: Product Catalog Cache TTL Misconfiguration

**Applies to alerts:** `product_catalog_api_latency_ms` spike, elevated DB CPU, low cache hit rate.

## Diagnosis

1. Check the cache hit-rate dashboard for the product catalog cache — a sharp drop (e.g. from >90% to <20%) with no corresponding deploy of catalog logic usually means a config-only change, not a code regression.
2. Diff recent commits to `config.py` (or equivalent config module) for `CACHE_TTL_SECONDS` or similar TTL constants — an accidental reduction (e.g. 300s → 3s) causes near-constant cache misses.
3. Cross-check DB CPU utilization timing against the config change's deploy time.

## Mitigation

1. Revert the TTL value to its previous baseline.
2. After redeploying, consider a cache warm-up pass for hot product IDs to avoid a thundering-herd of cold-cache lookups immediately after the fix.
3. Confirm cache hit rate recovers above 85% and DB CPU returns to baseline.

## Prevention

- Add a bounds check / code review rule flagging TTL changes below a sane floor (e.g. 30s) for the catalog cache.
