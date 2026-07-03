"""Closed-loop load generator: N virtual users continuously exercising the
target app from inside the backend's event loop. Every request lands one
sample in the metrics store.

The workload is identical whether the deployed code is healthy or broken —
degradation shows up in the measurements, never in the traffic. This is what
lets the anomaly detector (and the demo) be honest: nothing is scripted.
"""

import asyncio
import logging
import random
import time

import httpx

from app.config import settings
from app.live.metrics import store

logger = logging.getLogger(__name__)

PRODUCT_IDS = [f"p{i}" for i in range(1, 11)]
THINK_TIME_RANGE_S = (0.02, 0.08)


async def _one_request(client: httpx.AsyncClient) -> None:
    roll = random.random()
    if roll < 0.35:
        group = "GET /products"
        req = client.get("/products")
    elif roll < 0.60:
        group = "GET /products/{id}"
        req = client.get(f"/products/{random.choice(PRODUCT_IDS)}")
    elif roll < 0.85:
        group = "POST /checkout/summary"
        items = [
            {"product_id": pid, "quantity": random.randint(1, 3)}
            for pid in random.sample(PRODUCT_IDS, k=random.randint(4, 9))
        ]
        req = client.post("/checkout/summary", json={"items": items})
    else:
        group = "POST /webhooks/payments"
        # ~35% of webhook events are refunds/disputes, which legitimately
        # carry no charge object — exactly the case the guard protects.
        if random.random() < 0.35:
            payload = {"event_type": "refund.created", "order_id": f"o-{random.randint(1, 9999)}"}
        else:
            payload = {
                "event_type": "charge.succeeded",
                "order_id": f"o-{random.randint(1, 9999)}",
                "charge": {"amount": random.randint(1500, 15000), "status": "succeeded"},
            }
        req = client.post("/webhooks/payments", json=payload)

    t0 = time.perf_counter()
    try:
        resp = await req
    except httpx.HTTPError:
        # target app is restarting mid-deploy; back off without recording
        await asyncio.sleep(0.5)
        return
    latency_ms = (time.perf_counter() - t0) * 1000
    error_body = resp.text if resp.status_code >= 500 else None
    store.record(group, latency_ms, resp.status_code, error_body)


async def _worker(client: httpx.AsyncClient, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await _one_request(client)
        except Exception:  # noqa: BLE001 — a worker must never die
            logger.exception("load worker request failed unexpectedly")
            await asyncio.sleep(1)
        await asyncio.sleep(random.uniform(*THINK_TIME_RANGE_S))


async def run_load(stop_event: asyncio.Event) -> None:
    async with httpx.AsyncClient(
        base_url=settings.target_app_url,
        timeout=10,
        limits=httpx.Limits(max_connections=settings.load_workers + 5),
    ) as client:
        await asyncio.gather(
            *(_worker(client, stop_event) for _ in range(settings.load_workers))
        )
