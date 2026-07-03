"""Live metrics feed for the dashboard charts."""

from fastapi import APIRouter

from app.live.detector import detector
from app.live.metrics import store

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("")
def get_metrics():
    return {
        "current": store.group_stats(seconds=15),
        "series": store.series(seconds=300, bucket_s=5),
        "baseline": detector.baseline,
        "baseline_ready": detector.baseline is not None,
        "recent_errors": store.recent_error_samples(seconds=60),
    }
