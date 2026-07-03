"""Builds ecommerce-app/ as its own real git repository: a small but genuinely
runnable FastAPI storefront whose performance characteristics are real —
every DB query checks a connection out of a fixed-size pool and holds it for
a simulated round-trip, and the catalog endpoint sits behind a TTL cache.
That means the seeded bad commits don't just *look* bad in a diff; deploying
them measurably degrades the running service under load.

Git topology:

    main            — healthy history (baseline + noise commits). HEAD is healthy.
    deploy/r-142    — noise + "perf: fetch product details individually..." (N+1) + noise
    deploy/r-143    — noise + "chore: tune cache TTL..." (300s -> 1s) + noise
    deploy/r-144    — noise + "refactor: simplify charge webhook handler" (guard removed) + noise
    deploy/r-145    — noise + "config: apply staging pool size override" (50 -> 5) + noise

Branch names are neutral on purpose: deploying one tells the incident
pipeline nothing about which fault it carries. The bad commit is never at
HEAD — the diagnosis step has to find it among noise.

Run: `python -m app.seed.seed_ecommerce_repo` (from backend/, venv active).
Safe to re-run — it wipes and rebuilds ecommerce-app/ each time.
"""

import shutil
from datetime import datetime, timedelta

from git import Actor, Repo

from app.config import settings
from app.seed.fault_scenarios import FAULT_SCENARIOS

REPO_PATH = settings.ecommerce_repo_path
BASE_DATE = datetime(2026, 6, 1, 9, 30, 0)


def _replace(base: str, old: str, new: str) -> str:
    """str.replace that fails loudly if the target text drifted."""
    if old not in base:
        raise ValueError(f"template drift: substring not found:\n{old!r}")
    return base.replace(old, new)


# ---------------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------------

CONFIG_V1 = '''CACHE_TTL_SECONDS = 300
DB_POOL_SIZE = 50

FEATURE_FLAGS = {
    "new_checkout_ui": True,
    "recommendation_engine": False,
}
'''

CONFIG_TTL_BAD = _replace(CONFIG_V1, "CACHE_TTL_SECONDS = 300", "CACHE_TTL_SECONDS = 1")
CONFIG_POOL_BAD = _replace(CONFIG_V1, "DB_POOL_SIZE = 50", "DB_POOL_SIZE = 5")

# ---------------------------------------------------------------------------
# db.py — simulated database with a real connection pool
# ---------------------------------------------------------------------------

DB_V1 = '''"""Simulated database layer.

There is no external database: query latency is simulated. But the
concurrency behavior is real — every query checks a connection out of a
fixed-size pool (an asyncio semaphore sized by DB_POOL_SIZE) and holds it
for the duration of the simulated round-trip. Query counts and pool sizing
therefore have genuine, measurable latency consequences under load.
"""

import asyncio
import random
from dataclasses import dataclass

from config import DB_POOL_SIZE

QUERY_LATENCY_RANGE_S = (0.012, 0.024)
POOL_ACQUIRE_TIMEOUT_S = 1.5


class PoolExhaustedError(Exception):
    """Raised when no connection frees up within the acquire timeout."""


@dataclass
class Product:
    id: str
    name: str
    price_cents: int
    stock: int
    category: str


_PRODUCTS: dict[str, Product] = {
    "p1": Product("p1", "Wireless Mouse", 2499, 120, "accessories"),
    "p2": Product("p2", "Mechanical Keyboard", 8999, 45, "accessories"),
    "p3": Product("p3", "USB-C Hub", 3499, 200, "accessories"),
    "p4": Product("p4", "Laptop Stand", 4299, 80, "desk"),
    "p5": Product("p5", "Webcam 1080p", 5999, 30, "video"),
    "p6": Product("p6", "Ring Light", 2799, 65, "video"),
    "p7": Product("p7", "Desk Mat", 1899, 140, "desk"),
    "p8": Product("p8", "Noise-Cancelling Headset", 12999, 25, "audio"),
    "p9": Product("p9", "Condenser Microphone", 9499, 18, "audio"),
    "p10": Product("p10", "Monitor Arm", 6499, 52, "desk"),
}

_pool: asyncio.Semaphore | None = None


def _get_pool() -> asyncio.Semaphore:
    # Lazily created so the semaphore binds to the running event loop.
    global _pool
    if _pool is None:
        _pool = asyncio.Semaphore(DB_POOL_SIZE)
    return _pool


async def _execute(latency_range: tuple[float, float] = QUERY_LATENCY_RANGE_S) -> None:
    """One round-trip to the database: hold a pooled connection for the
    duration of the (simulated) query."""
    pool = _get_pool()
    try:
        await asyncio.wait_for(pool.acquire(), timeout=POOL_ACQUIRE_TIMEOUT_S)
    except TimeoutError:
        raise PoolExhaustedError(
            f"timed out waiting for a database connection (DB_POOL_SIZE={DB_POOL_SIZE})"
        ) from None
    try:
        await asyncio.sleep(random.uniform(*latency_range))
    finally:
        pool.release()


async def get_product(product_id: str) -> Product | None:
    await _execute()
    return _PRODUCTS.get(product_id)


async def get_related_products(product_id: str, limit: int = 4) -> list[Product]:
    """Same-category products, excluding the one being viewed."""
    await _execute()
    product = _PRODUCTS.get(product_id)
    if product is None:
        return []
    return [
        p
        for p in _PRODUCTS.values()
        if p.category == product.category and p.id != product_id
    ][:limit]


async def get_products_by_ids(product_ids: list[str]) -> list[Product]:
    """Batched lookup — one query regardless of how many ids are requested."""
    await _execute()
    return [p for pid in product_ids if (p := _PRODUCTS.get(pid)) is not None]


async def load_full_catalog() -> list[Product]:
    """Expensive catalog build: joins stock, pricing, and rating aggregates —
    several sequential queries. Callers are expected to cache the result."""
    for _ in range(8):
        await _execute((0.018, 0.032))
    return list(_PRODUCTS.values())
'''

DB_V2 = DB_V1 + '''

async def record_payment_event(event_type: str, order_id: str | None, amount: int) -> None:
    """Persist a payment event for reconciliation."""
    await _execute()
'''

DB_V3 = _replace(
    DB_V2,
    '"p5": Product("p5", "Webcam 1080p", 5999, 30, "video"),',
    '"p5": Product("p5", "Webcam 1080p", 5999, 12, "video"),',
)
DB_V3 = _replace(
    DB_V3,
    '"p8": Product("p8", "Noise-Cancelling Headset", 12999, 25, "audio"),',
    '"p8": Product("p8", "Noise-Cancelling Headset", 12999, 60, "audio"),',
)

# noise variant for deploy/r-143: docstring touch-ups only
DB_NOISE_DOCSTRINGS = _replace(
    DB_V3,
    '"""Batched lookup — one query regardless of how many ids are requested."""',
    '"""Batched product lookup.\n\n    Issues a single query no matter how many ids are requested — callers\n    should prefer this over per-id lookups in any hot path.\n    """',
)

# noise variant for deploy/r-144: restock numbers
DB_NOISE_RESTOCK = _replace(
    DB_V3,
    '"p9": Product("p9", "Condenser Microphone", 9499, 18, "audio"),',
    '"p9": Product("p9", "Condenser Microphone", 9499, 44, "audio"),',
)
DB_NOISE_RESTOCK = _replace(
    DB_NOISE_RESTOCK,
    '"p2": Product("p2", "Mechanical Keyboard", 8999, 45, "accessories"),',
    '"p2": Product("p2", "Mechanical Keyboard", 8999, 31, "accessories"),',
)

# ---------------------------------------------------------------------------
# cache.py
# ---------------------------------------------------------------------------

CACHE_V1 = '''"""Tiny in-process TTL cache for the product catalog."""

import time

from config import CACHE_TTL_SECONDS


class TTLCache:
    def __init__(self, ttl_seconds: float):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value) -> None:
        self._store[key] = (time.monotonic() + self.ttl, value)


catalog_cache = TTLCache(CACHE_TTL_SECONDS)
'''

# ---------------------------------------------------------------------------
# payments.py
# ---------------------------------------------------------------------------

PAYMENTS_V1 = '''from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChargeWebhookPayload(BaseModel):
    event_type: str
    charge: dict | None = None
    order_id: str | None = None


@router.post("/webhooks/payments")
async def handle_payment_webhook(payload: ChargeWebhookPayload):
    if payload.charge is None:
        return {"status": "ignored", "reason": "no charge object present"}

    amount = payload.charge["amount"]
    status = payload.charge["status"]

    return {
        "status": "processed",
        "order_id": payload.order_id,
        "amount": amount,
        "charge_status": status,
    }
'''

PAYMENTS_V2 = _replace(
    PAYMENTS_V1,
    "from fastapi import APIRouter\nfrom pydantic import BaseModel\n",
    "from fastapi import APIRouter\nfrom pydantic import BaseModel\n\nfrom db import record_payment_event\n",
)
PAYMENTS_V2 = _replace(
    PAYMENTS_V2,
    '''    amount = payload.charge["amount"]
    status = payload.charge["status"]

    return {''',
    '''    amount = payload.charge["amount"]
    status = payload.charge["status"]
    await record_payment_event(payload.event_type, payload.order_id, amount)

    return {''',
)

PAYMENTS_V3 = _replace(
    PAYMENTS_V2,
    '''@router.post("/webhooks/payments")
async def handle_payment_webhook(payload: ChargeWebhookPayload):
    if payload.charge is None:''',
    '''@router.post("/webhooks/payments")
async def handle_payment_webhook(payload: ChargeWebhookPayload):
    """Handles Stripe-style charge webhooks.

    NOTE: refund and dispute events may omit the `charge` object entirely
    (see provider docs, section 4.2), so this handler MUST guard against
    that before touching charge fields.
    """
    if payload.charge is None:''',
)

# BAD: guard removed — refund/dispute events (charge=None) now raise TypeError -> 500
PAYMENTS_BAD = _replace(
    PAYMENTS_V3,
    '''    """Handles Stripe-style charge webhooks.

    NOTE: refund and dispute events may omit the `charge` object entirely
    (see provider docs, section 4.2), so this handler MUST guard against
    that before touching charge fields.
    """
    if payload.charge is None:
        return {"status": "ignored", "reason": "no charge object present"}

    amount = payload.charge["amount"]''',
    '''    """Handles Stripe-style charge webhooks."""
    amount = payload.charge["amount"]''',
)

# ---------------------------------------------------------------------------
# main.py
# ---------------------------------------------------------------------------

MAIN_V1 = '''from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db import (
    PoolExhaustedError,
    get_product,
    get_products_by_ids,
    get_related_products,
    load_full_catalog,
)
from payments import router as payments_router

app = FastAPI(title="Toy E-Commerce App")
app.include_router(payments_router)


@app.exception_handler(PoolExhaustedError)
async def pool_exhausted_handler(request: Request, exc: PoolExhaustedError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


class CartItem(BaseModel):
    product_id: str
    quantity: int


class CheckoutRequest(BaseModel):
    items: list[CartItem]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/products")
async def products():
    return await load_full_catalog()


@app.get("/products/{product_id}")
async def product_detail(product_id: str):
    product = await get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    related = await get_related_products(product_id)
    return {"product": product, "related": related}


@app.post("/checkout/summary")
async def checkout_summary(req: CheckoutRequest):
    """Returns line-item pricing for the cart. Uses a single batched lookup
    to avoid a query per line item."""
    ids = [item.product_id for item in req.items]
    products_by_id = {p.id: p for p in await get_products_by_ids(ids)}

    line_items = []
    subtotal_cents = 0
    for item in req.items:
        product = products_by_id.get(item.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail=f"Unknown product {item.product_id}")
        line_total = product.price_cents * item.quantity
        subtotal_cents += line_total
        line_items.append(
            {
                "product_id": product.id,
                "name": product.name,
                "quantity": item.quantity,
                "line_total_cents": line_total,
            }
        )

    return {"line_items": line_items, "subtotal_cents": subtotal_cents}
'''

# V2: catalog endpoint goes behind the TTL cache, warmed at startup
MAIN_V2 = _replace(
    MAIN_V1,
    "from db import (\n    PoolExhaustedError,",
    "from cache import catalog_cache\nfrom db import (\n    PoolExhaustedError,",
)
MAIN_V2 = _replace(
    MAIN_V2,
    '''@app.get("/products")
async def products():
    return await load_full_catalog()''',
    '''@app.get("/products")
async def products():
    catalog = catalog_cache.get("catalog")
    if catalog is None:
        catalog = await load_full_catalog()
        catalog_cache.set("catalog", catalog)
    return catalog''',
)
MAIN_V2 = _replace(
    MAIN_V2,
    '''@app.get("/health")
async def health():
    return {"status": "ok"}''',
    '''@app.on_event("startup")
async def warm_catalog_cache():
    catalog_cache.set("catalog", await load_full_catalog())


@app.get("/health")
async def health():
    return {"status": "ok"}''',
)

# V3: feature-flagged recommendations endpoint
MAIN_V3 = _replace(
    MAIN_V2,
    "from cache import catalog_cache\nfrom db import",
    "from cache import catalog_cache\nfrom config import FEATURE_FLAGS\nfrom db import",
) + '''

@app.get("/recommendations/{product_id}")
async def recommendations(product_id: str):
    """Feature-flagged: returns a static placeholder list until the
    recommendation engine ships."""
    if not FEATURE_FLAGS.get("recommendation_engine", False):
        return {"recommendations": []}
    return {"recommendations": []}
'''

# noise for deploy/r-142: import order shuffle
MAIN_NOISE_IMPORTS = _replace(
    MAIN_V3,
    '''from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cache import catalog_cache
from config import FEATURE_FLAGS
from db import (
    PoolExhaustedError,
    get_product,
    get_products_by_ids,
    get_related_products,
    load_full_catalog,
)
from payments import router as payments_router''',
    '''from cache import catalog_cache
from config import FEATURE_FLAGS
from db import (
    PoolExhaustedError,
    get_product,
    get_products_by_ids,
    get_related_products,
    load_full_catalog,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from payments import router as payments_router
from pydantic import BaseModel''',
)

# BAD: N+1 — batched lookup replaced with a per-item query loop
MAIN_N_PLUS_ONE_BAD = _replace(
    MAIN_NOISE_IMPORTS,
    '''@app.post("/checkout/summary")
async def checkout_summary(req: CheckoutRequest):
    """Returns line-item pricing for the cart. Uses a single batched lookup
    to avoid a query per line item."""
    ids = [item.product_id for item in req.items]
    products_by_id = {p.id: p for p in await get_products_by_ids(ids)}

    line_items = []
    subtotal_cents = 0
    for item in req.items:
        product = products_by_id.get(item.product_id)
        if product is None:''',
    '''@app.post("/checkout/summary")
async def checkout_summary(req: CheckoutRequest):
    """Returns line-item pricing for the cart."""
    line_items = []
    subtotal_cents = 0
    for item in req.items:
        product = await get_product(item.product_id)
        if product is None:''',
)

# noise for deploy/r-145: docstring clarification on checkout
MAIN_NOISE_DOCSTRING = _replace(
    MAIN_V3,
    '"""Returns line-item pricing for the cart. Uses a single batched lookup\n    to avoid a query per line item."""',
    '"""Price a cart and return line items plus subtotal.\n\n    Uses a single batched lookup to avoid a query per line item.\n    """',
)

# ---------------------------------------------------------------------------
# README, requirements, tests (noise material)
# ---------------------------------------------------------------------------

README_V1 = '''# Toy E-Commerce App

A minimal FastAPI storefront used as the live target application for the
Autonomous AI Incident Response System demo. It genuinely runs: the DB layer
simulates query latency behind a real fixed-size connection pool, and the
catalog endpoint sits behind a TTL cache — so bad deploys degrade it for real.
'''

README_V2 = README_V1 + '''
## API

- `GET /products` — list catalog products (cached)
- `GET /products/{id}` — fetch a single product
- `POST /checkout/summary` — price a cart: `{"items": [{"product_id": "p1", "quantity": 2}]}`
- `POST /webhooks/payments` — Stripe-style charge webhook receiver
'''

README_V3 = README_V2 + '''
## Changelog

- Catalog responses are now cached (TTL in `config.py`)
- Payment events recorded for reconciliation
- Feature-flagged `/recommendations/{product_id}` endpoint
'''

README_NOISE_DEVNOTES = README_V3 + '''
## Local development

```bash
pip install -r requirements.txt
uvicorn main:app --port 8001
```
'''

README_NOISE_WEBHOOK_CHANGELOG = README_V3 + '''
## Recent changes

- Simplified the charge webhook handler
'''

REQUIREMENTS_V1 = "fastapi==0.111.0\nuvicorn==0.30.0\npydantic==2.7.0\n"
REQUIREMENTS_V2 = "fastapi==0.115.4\nuvicorn==0.32.0\npydantic==2.9.2\n"

GITIGNORE = "__pycache__/\n*.pyc\n.venv/\n.env\n"

TEST_PRODUCTS = '''import asyncio

from db import get_product, load_full_catalog


def test_catalog_nonempty():
    assert len(asyncio.run(load_full_catalog())) > 0


def test_get_product_unknown_returns_none():
    assert asyncio.run(get_product("does-not-exist")) is None
'''

TEST_CHECKOUT = '''import asyncio

from db import get_products_by_ids


def test_get_products_by_ids_batched():
    products = asyncio.run(get_products_by_ids(["p1", "p2"]))
    assert {p.id for p in products} == {"p1", "p2"}
'''

TEST_PAYMENTS_WEBHOOK = '''# TODO: flesh out webhook test coverage — currently only smoke-tests
# construction of the payload model, not the handler itself.
from payments import ChargeWebhookPayload


def test_charge_webhook_payload_parses():
    payload = ChargeWebhookPayload(event_type="charge.succeeded", order_id="o1")
    assert payload.event_type == "charge.succeeded"
'''

TEST_CACHE = '''from cache import TTLCache


def test_ttl_cache_roundtrip():
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", 42)
    assert cache.get("k") == 42


def test_ttl_cache_miss():
    cache = TTLCache(ttl_seconds=60)
    assert cache.get("missing") is None
'''

# ---------------------------------------------------------------------------
# Commit plans: (message, {relative_path: content}, day_offset)
# ---------------------------------------------------------------------------

MAIN_BRANCH_STEPS: list[tuple[str, dict[str, str], int]] = [
    (
        "init: scaffold toy storefront service",
        {
            "main.py": MAIN_V1,
            "payments.py": PAYMENTS_V1,
            "config.py": CONFIG_V1,
            "db.py": DB_V1,
            "README.md": README_V1,
            "requirements.txt": REQUIREMENTS_V1,
            ".gitignore": GITIGNORE,
        },
        0,
    ),
    ("test: add product catalog tests", {"tests/test_products.py": TEST_PRODUCTS}, 1),
    (
        "perf: cache the product catalog response",
        {"main.py": MAIN_V2, "cache.py": CACHE_V1},
        3,
    ),
    ("docs: expand README with API usage examples", {"README.md": README_V2}, 4),
    (
        "feat: record payment events for reconciliation",
        {"payments.py": PAYMENTS_V2, "db.py": DB_V2},
        6,
    ),
    ("docs: document payment webhook contract", {"payments.py": PAYMENTS_V3}, 7),
    (
        "feat: add recommendation endpoint behind feature flag",
        {"main.py": MAIN_V3},
        8,
    ),
    ("test: add checkout summary test", {"tests/test_checkout.py": TEST_CHECKOUT}, 9),
    ("chore: bump dependency versions", {"requirements.txt": REQUIREMENTS_V2}, 10),
    ("chore: update product stock levels", {"db.py": DB_V3}, 11),
    ("docs: update README changelog", {"README.md": README_V3}, 12),
]

# Per-scenario deploy branches: noise, THE BAD COMMIT, noise — so the bad
# commit is never at HEAD and never alone.
DEPLOY_BRANCH_STEPS: dict[str, list[tuple[str, dict[str, str], int]]] = {
    "checkout-n-plus-one": [
        ("style: sort imports in main module", {"main.py": MAIN_NOISE_IMPORTS}, 13),
        (
            "perf: fetch product details individually during checkout summary",
            {"main.py": MAIN_N_PLUS_ONE_BAD},
            14,
        ),
        ("docs: add local development notes to README", {"README.md": README_NOISE_DEVNOTES}, 14),
    ],
    "cache-ttl-misconfigured": [
        (
            "test: add webhook payload parsing test",
            {"tests/test_payments_webhook.py": TEST_PAYMENTS_WEBHOOK},
            13,
        ),
        ("chore: tune cache TTL for product catalog", {"config.py": CONFIG_TTL_BAD}, 14),
        ("style: reformat product catalog helpers", {"db.py": DB_NOISE_DOCSTRINGS}, 14),
    ],
    "null-pointer-payment-webhook": [
        ("chore: update stock levels for June restock", {"db.py": DB_NOISE_RESTOCK}, 13),
        ("refactor: simplify charge webhook handler", {"payments.py": PAYMENTS_BAD}, 14),
        (
            "docs: add changelog entry for webhook refactor",
            {"README.md": README_NOISE_WEBHOOK_CHANGELOG},
            14,
        ),
    ],
    "connection-pool-config-rollout": [
        ("docs: clarify checkout summary docstring", {"main.py": MAIN_NOISE_DOCSTRING}, 13),
        ("config: apply staging pool size override", {"config.py": CONFIG_POOL_BAD}, 14),
        ("test: add cache helper tests", {"tests/test_cache.py": TEST_CACHE}, 14),
    ],
}

AUTHORS = ["Priya Shah", "Marcus Lee", "Dana Ortiz"]
_commit_counter = 0


def _apply_steps(repo: Repo, steps: list[tuple[str, dict[str, str], int]]) -> None:
    global _commit_counter
    for message, files, day_offset in steps:
        for rel_path, content in files.items():
            file_path = REPO_PATH / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

        repo.index.add(list(files.keys()))
        # spread commits within a day so ordering is deterministic
        commit_date = (
            BASE_DATE + timedelta(days=day_offset, minutes=17 * _commit_counter)
        ).isoformat()
        author_name = AUTHORS[_commit_counter % len(AUTHORS)]
        actor = Actor(author_name, f"{author_name.split()[0].lower()}@example.com")
        repo.index.commit(
            message,
            author_date=commit_date,
            commit_date=commit_date,
            author=actor,
            committer=actor,
        )
        _commit_counter += 1


def seed() -> None:
    global _commit_counter
    _commit_counter = 0

    if REPO_PATH.exists():
        shutil.rmtree(REPO_PATH)
    REPO_PATH.mkdir(parents=True)

    repo = Repo.init(REPO_PATH, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Demo Seed")
        cw.set_value("user", "email", "demo-seed@example.com")

    _apply_steps(repo, MAIN_BRANCH_STEPS)
    main_commits = len(MAIN_BRANCH_STEPS)

    for scenario_id, steps in DEPLOY_BRANCH_STEPS.items():
        scenario = FAULT_SCENARIOS[scenario_id]
        branch = repo.create_head(scenario.deploy_branch, "main")
        branch.checkout()
        _apply_steps(repo, steps)
        # sanity: the branch must actually contain the ground-truth commit
        messages = [c.message.strip() for c in repo.iter_commits(scenario.deploy_branch)]
        if scenario.target_commit_message not in messages:
            raise RuntimeError(
                f"seed bug: {scenario.deploy_branch} missing bad commit for {scenario_id}"
            )

    repo.heads.main.checkout()
    print(
        f"Seeded {REPO_PATH}: main ({main_commits} commits) + "
        f"{len(DEPLOY_BRANCH_STEPS)} deploy branches (3 commits each)"
    )


if __name__ == "__main__":
    seed()
