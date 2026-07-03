"""Unit tests for the observability layer: metrics windows, breach detection,
alert composition, and recovery verification."""

import time

from app.live.detector import AnomalyDetector
from app.live.metrics import MetricsStore, percentile
from app.pipeline.remediation import _recovered

CHECKOUT = "POST /checkout/summary"
PRODUCTS = "GET /products"


def make_baseline(p95=26.0, err=0.0):
    return {
        CHECKOUT: {"count": 500, "rps": 40.0, "p50_ms": 20.0, "p95_ms": p95, "error_rate_pct": err},
        PRODUCTS: {"count": 700, "rps": 60.0, "p50_ms": 1.5, "p95_ms": 3.0, "error_rate_pct": 0.0},
    }


def stats(count=100, rps=40.0, p50=20.0, p95=26.0, err=0.0):
    return {"count": count, "rps": rps, "p50_ms": p50, "p95_ms": p95, "error_rate_pct": err}


# -- metrics store ----------------------------------------------------------


def test_percentile_basics():
    assert percentile([], 0.95) == 0.0
    assert percentile([5.0], 0.95) == 5.0
    values = [float(i) for i in range(1, 101)]
    assert percentile(values, 0.5) == 51.0
    assert percentile(values, 0.95) == 96.0


def test_group_stats_counts_errors_and_latency():
    store = MetricsStore()
    for i in range(20):
        store.record(CHECKOUT, latency_ms=10.0 + i, status=200)
    store.record(CHECKOUT, latency_ms=5.0, status=503, error_body="pool exhausted")

    s = store.group_stats(seconds=60)[CHECKOUT]
    assert s["count"] == 21
    assert s["error_rate_pct"] == round(100 / 21, 1)
    assert s["p95_ms"] >= 28.0

    errors = store.recent_error_samples(seconds=60)
    assert errors and "pool exhausted" in errors[0]["body"]


def test_window_excludes_old_samples():
    from app.live.metrics import Sample

    store = MetricsStore()
    store._samples.append(Sample(time.time() - 120, CHECKOUT, 10.0, 200))
    store.record(CHECKOUT, 20.0, 200)
    assert store.group_stats(seconds=60)[CHECKOUT]["count"] == 1


# -- detector breach logic --------------------------------------------------


def test_no_breach_when_healthy():
    det = AnomalyDetector()
    det.baseline = make_baseline()
    current = {CHECKOUT: stats(p95=30.0), PRODUCTS: stats(p95=3.2, rps=60.0)}
    assert det._find_breaches(current) == {}


def test_latency_breach_requires_ratio_and_absolute_floor():
    det = AnomalyDetector()
    det.baseline = make_baseline(p95=26.0)
    # 3x ratio and > +30ms absolute -> breach
    breaches = det._find_breaches({CHECKOUT: stats(p95=170.0)})
    assert CHECKOUT in breaches
    # products: huge ratio but tiny absolute delta -> no breach (jitter guard)
    det.baseline = {PRODUCTS: stats(p95=3.0)}
    assert det._find_breaches({PRODUCTS: stats(p95=9.0)}) == {}


def test_error_rate_breach():
    det = AnomalyDetector()
    det.baseline = make_baseline()
    breaches = det._find_breaches({CHECKOUT: stats(err=34.0)})
    assert "error rate" in breaches[CHECKOUT][0]


def test_low_sample_windows_are_ignored():
    det = AnomalyDetector()
    det.baseline = make_baseline()
    assert det._find_breaches({CHECKOUT: stats(count=5, p95=500.0)}) == {}


def test_alert_text_contains_measured_numbers_and_nominal_section():
    det = AnomalyDetector()
    det.baseline = make_baseline()
    current = {CHECKOUT: stats(p95=170.0), PRODUCTS: stats(p95=3.1, rps=60.0)}
    breaches = det._find_breaches(current)
    alert = det._compose_alert(current, breaches, error_samples=[])
    assert "170.0ms" in alert or "170ms" in alert
    assert "Nominal endpoints:" in alert
    assert PRODUCTS in alert
    # ground truth never leaks into the alert
    assert "deploy/r-" not in alert
    assert "scenario" not in alert.lower()


# -- recovery verification --------------------------------------------------


def test_recovered_requires_all_groups_back_within_tolerance():
    baseline = make_baseline()
    healthy_now = {CHECKOUT: stats(p95=28.0), PRODUCTS: stats(p95=3.1)}
    assert _recovered(baseline, healthy_now) is True

    still_degraded = {CHECKOUT: stats(p95=150.0), PRODUCTS: stats(p95=3.1)}
    assert _recovered(baseline, still_degraded) is False

    missing_group = {CHECKOUT: stats(p95=28.0)}
    assert _recovered(baseline, missing_group) is False

    errors_persist = {CHECKOUT: stats(p95=28.0, err=10.0), PRODUCTS: stats(p95=3.1)}
    assert _recovered(baseline, errors_persist) is False
