"""Builds ecommerce-app/ as its own real git repository: a small, plausible
FastAPI toy store with a realistic commit history — baseline commits,
interleaved "noise" commits, and four seeded bad commits scattered at
varying depths (not all at HEAD). This is what the commit-analysis pipeline
step reasons over: it must discriminate the real bad commit for a given
fault out of ~15 recent commits, most of which are innocuous.

Run: `python -m app.seed.seed_ecommerce_repo` (from backend/, with the venv
active). Safe to re-run — it wipes and rebuilds ecommerce-app/ each time.
"""

import shutil
from datetime import datetime, timedelta

from git import Actor, Repo

from app.config import settings

REPO_PATH = settings.ecommerce_repo_path
BASE_DATE = datetime(2026, 4, 1, 9, 0, 0)

# ---------------------------------------------------------------------------
# File content variants
# ---------------------------------------------------------------------------

MAIN_V1 = '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from db import get_product, get_products_by_ids, list_products

app = FastAPI(title="Toy E-Commerce App")


class CartItem(BaseModel):
    product_id: str
    quantity: int


class CheckoutRequest(BaseModel):
    items: list[CartItem]


@app.get("/products")
def products():
    return list_products()


@app.get("/products/{product_id}")
def product_detail(product_id: str):
    product = get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.post("/checkout/summary")
def checkout_summary(req: CheckoutRequest):
    """Returns line-item pricing for the cart. Uses a single batched lookup
    to avoid a query per line item."""
    ids = [item.product_id for item in req.items]
    products_by_id = {p.id: p for p in get_products_by_ids(ids)}

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

MAIN_V2 = MAIN_V1.replace(
    'from db import get_product, get_products_by_ids, list_products\n\napp = FastAPI(title="Toy E-Commerce App")',
    'from config import FEATURE_FLAGS\nfrom db import get_product, get_products_by_ids, list_products\n\napp = FastAPI(title="Toy E-Commerce App")',
) + '''

@app.get("/recommendations/{product_id}")
def recommendations(product_id: str):
    """Feature-flagged: returns a static placeholder list until the
    recommendation engine ships."""
    if not FEATURE_FLAGS.get("recommendation_engine", False):
        return {"recommendations": []}
    return {"recommendations": []}
'''

MAIN_V3 = MAIN_V2.replace(
    '''@app.post("/checkout/summary")
def checkout_summary(req: CheckoutRequest):
    """Returns line-item pricing for the cart. Uses a single batched lookup
    to avoid a query per line item."""
    ids = [item.product_id for item in req.items]
    products_by_id = {p.id: p for p in get_products_by_ids(ids)}

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

    return {"line_items": line_items, "subtotal_cents": subtotal_cents}''',
    '''@app.post("/checkout/summary")
def checkout_summary(req: CheckoutRequest):
    """Returns line-item pricing for the cart."""
    line_items = []
    subtotal_cents = 0
    for item in req.items:
        product = get_product(item.product_id)
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

    return {"line_items": line_items, "subtotal_cents": subtotal_cents}''',
)

MAIN_V4 = MAIN_V3 + '''

@app.get("/health")
def health():
    return {"status": "ok"}
'''

MAIN_V5 = MAIN_V4.replace(
    "from fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel\n\nfrom config import FEATURE_FLAGS\nfrom db import get_product, get_products_by_ids, list_products",
    "from config import FEATURE_FLAGS\nfrom db import get_product, get_products_by_ids, list_products\nfrom fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel",
)

PAYMENTS_V1 = '''from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChargeWebhookPayload(BaseModel):
    event_type: str
    charge: dict | None = None
    order_id: str | None = None


@router.post("/webhooks/payments")
def handle_payment_webhook(payload: ChargeWebhookPayload):
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

PAYMENTS_V1B = PAYMENTS_V1.replace(
    '@router.post("/webhooks/payments")\ndef handle_payment_webhook(payload: ChargeWebhookPayload):\n    if payload.charge is None:',
    '''@router.post("/webhooks/payments")
def handle_payment_webhook(payload: ChargeWebhookPayload):
    """Handles Stripe-style charge webhooks.

    NOTE: refund and dispute events may omit the `charge` object entirely
    (see provider docs, section 4.2), so callers MUST guard against that
    before touching charge fields.
    """
    if payload.charge is None:''',
)

PAYMENTS_V2 = '''from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChargeWebhookPayload(BaseModel):
    event_type: str
    charge: dict | None = None
    order_id: str | None = None


@router.post("/webhooks/payments")
def handle_payment_webhook(payload: ChargeWebhookPayload):
    """Handles Stripe-style charge webhooks."""
    amount = payload.charge["amount"]
    status = payload.charge["status"]

    return {
        "status": "processed",
        "order_id": payload.order_id,
        "amount": amount,
        "charge_status": status,
    }
'''

CONFIG_V1 = '''CACHE_TTL_SECONDS = 300
DB_POOL_SIZE = 50

FEATURE_FLAGS = {
    "new_checkout_ui": True,
    "recommendation_engine": False,
}
'''

CONFIG_V2 = CONFIG_V1.replace("CACHE_TTL_SECONDS = 300", "CACHE_TTL_SECONDS = 3")

CONFIG_V3 = CONFIG_V2.replace("DB_POOL_SIZE = 50", "DB_POOL_SIZE = 5")

DB_V1 = '''from dataclasses import dataclass


@dataclass
class Product:
    id: str
    name: str
    price_cents: int
    stock: int


_PRODUCTS: dict[str, Product] = {
    "p1": Product("p1", "Wireless Mouse", 2499, 120),
    "p2": Product("p2", "Mechanical Keyboard", 8999, 45),
    "p3": Product("p3", "USB-C Hub", 3499, 200),
    "p4": Product("p4", "Laptop Stand", 4299, 80),
    "p5": Product("p5", "Webcam 1080p", 5999, 30),
}


def get_product(product_id: str) -> Product | None:
    return _PRODUCTS.get(product_id)


def get_products_by_ids(product_ids: list[str]) -> list[Product]:
    return [p for pid in product_ids if (p := _PRODUCTS.get(pid)) is not None]


def list_products() -> list[Product]:
    return list(_PRODUCTS.values())
'''

DB_V2 = '''from dataclasses import dataclass


@dataclass
class Product:
    id: str
    name: str
    price_cents: int
    stock: int


_PRODUCTS: dict[str, Product] = {
    "p1": Product("p1", "Wireless Mouse", 2499, 120),
    "p2": Product("p2", "Mechanical Keyboard", 8999, 45),
    "p3": Product("p3", "USB-C Hub", 3499, 200),
    "p4": Product("p4", "Laptop Stand", 4299, 80),
    "p5": Product("p5", "Webcam 1080p", 5999, 30),
}


def get_product(product_id: str) -> Product | None:
    """Look up a single product by id."""
    return _PRODUCTS.get(product_id)


def get_products_by_ids(product_ids: list[str]) -> list[Product]:
    """Batched lookup — one pass instead of N individual lookups."""
    return [p for pid in product_ids if (p := _PRODUCTS.get(pid)) is not None]


def list_products() -> list[Product]:
    """Return all catalog products."""
    return list(_PRODUCTS.values())
'''

DB_V3 = DB_V2.replace(
    '"p1": Product("p1", "Wireless Mouse", 2499, 120),\n    "p2": Product("p2", "Mechanical Keyboard", 8999, 45),\n    "p3": Product("p3", "USB-C Hub", 3499, 200),\n    "p4": Product("p4", "Laptop Stand", 4299, 80),\n    "p5": Product("p5", "Webcam 1080p", 5999, 30),',
    '"p1": Product("p1", "Wireless Mouse", 2499, 86),\n    "p2": Product("p2", "Mechanical Keyboard", 8999, 12),\n    "p3": Product("p3", "USB-C Hub", 3499, 154),\n    "p4": Product("p4", "Laptop Stand", 4299, 41),\n    "p5": Product("p5", "Webcam 1080p", 5999, 9),',
)

README_V1 = '''# Toy E-Commerce App

A minimal FastAPI storefront used as the target application for the
Autonomous AI Incident Response System demo.
'''

README_V2 = README_V1 + '''
## API

- `GET /products` — list catalog products
- `GET /products/{id}` — fetch a single product
- `POST /checkout/summary` — price a cart: `{"items": [{"product_id": "p1", "quantity": 2}]}`
'''

README_V3 = README_V2 + '''
## Changelog

- Added `/health` endpoint
- Added feature-flagged `/recommendations/{product_id}` endpoint
'''

REQUIREMENTS_V1 = "fastapi==0.111.0\nuvicorn==0.30.0\npydantic==2.7.0\n"
REQUIREMENTS_V2 = "fastapi==0.115.4\nuvicorn==0.32.0\npydantic==2.9.2\n"

GITIGNORE = "__pycache__/\n*.pyc\n.venv/\n.env\n"

TEST_PRODUCTS = '''from db import list_products, get_product


def test_list_products_nonempty():
    assert len(list_products()) > 0


def test_get_product_unknown_returns_none():
    assert get_product("does-not-exist") is None
'''

TEST_CHECKOUT = '''from db import get_products_by_ids


def test_get_products_by_ids_batched():
    products = get_products_by_ids(["p1", "p2"])
    assert {p.id for p in products} == {"p1", "p2"}
'''

TEST_PAYMENTS_WEBHOOK = '''# TODO: flesh out webhook test coverage — currently only smoke-tests
# construction of the payload model, not the handler itself.
from payments import ChargeWebhookPayload


def test_charge_webhook_payload_parses():
    payload = ChargeWebhookPayload(event_type="charge.succeeded", order_id="o1")
    assert payload.event_type == "charge.succeeded"
'''

# ---------------------------------------------------------------------------
# Commit plan: (message, {relative_path: content}, day_offset)
# ---------------------------------------------------------------------------

STEPS: list[tuple[str, dict[str, str], int]] = [
    (
        "init: scaffold toy e-commerce app",
        {
            "main.py": MAIN_V1,
            "payments.py": PAYMENTS_V1,
            "config.py": CONFIG_V1,
            "db.py": DB_V1,
            "README.md": README_V1,
            "requirements.txt": REQUIREMENTS_V1,
        },
        0,
    ),
    ("chore: add .gitignore", {".gitignore": GITIGNORE}, 1),
    ("test: add product listing tests", {"tests/test_products.py": TEST_PRODUCTS}, 2),
    ("docs: expand README with API usage examples", {"README.md": README_V2}, 3),
    ("feat: add recommendation endpoint behind feature flag", {"main.py": MAIN_V2}, 5),
    ("chore: tune cache TTL for product catalog", {"config.py": CONFIG_V2}, 6),
    ("style: reformat product catalog helpers", {"db.py": DB_V2}, 7),
    ("test: add checkout summary test", {"tests/test_checkout.py": TEST_CHECKOUT}, 8),
    (
        "perf: fetch product details individually during checkout summary",
        {"main.py": MAIN_V3},
        9,
    ),
    ("chore: bump dependency versions", {"requirements.txt": REQUIREMENTS_V2}, 10),
    ("docs: document payment webhook contract", {"payments.py": PAYMENTS_V1B}, 11),
    ("refactor: simplify charge webhook handler", {"payments.py": PAYMENTS_V2}, 12),
    ("feat: add health check endpoint", {"main.py": MAIN_V4}, 13),
    (
        "test: add payment webhook test stub",
        {"tests/test_payments_webhook.py": TEST_PAYMENTS_WEBHOOK},
        14,
    ),
    ("config: apply staging pool size override", {"config.py": CONFIG_V3}, 15),
    ("chore: update product stock levels", {"db.py": DB_V3}, 16),
    ("style: sort imports in main module", {"main.py": MAIN_V5}, 17),
    ("docs: update README changelog", {"README.md": README_V3}, 18),
]

AUTHORS = ["Priya Shah", "Marcus Lee", "Dana Ortiz"]


def seed() -> None:
    if REPO_PATH.exists():
        shutil.rmtree(REPO_PATH)
    REPO_PATH.mkdir(parents=True)

    repo = Repo.init(REPO_PATH, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Demo Seed")
        cw.set_value("user", "email", "demo-seed@example.com")

    for i, (message, files, day_offset) in enumerate(STEPS):
        for rel_path, content in files.items():
            file_path = REPO_PATH / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

        repo.index.add(list(files.keys()))
        commit_date = (BASE_DATE + timedelta(days=day_offset)).isoformat()
        author_name = AUTHORS[i % len(AUTHORS)]
        actor = Actor(author_name, f"{author_name.split()[0].lower()}@example.com")
        repo.index.commit(
            message,
            author_date=commit_date,
            commit_date=commit_date,
            author=actor,
            committer=actor,
        )

    print(f"Seeded {len(STEPS)} commits into {REPO_PATH}")


if __name__ == "__main__":
    seed()
