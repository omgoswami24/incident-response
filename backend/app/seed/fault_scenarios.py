"""Registry of the four seedable regressions.

Each scenario maps to a deploy branch in the target app's git repository
(built by seed_ecommerce_repo.py) whose history contains the bad commit
buried among noise commits. Branch names are deliberately neutral release
names — nothing the diagnosis pipeline sees encodes which fault a branch
contains. Injecting a fault deploys the branch to the running target app;
from there the fault has to be *detected* from live metrics and *diagnosed*
from the git history. `target_commit_message` is ground truth used only to
score the diagnosis after the fact — it is never fed to the LLM.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FaultScenario:
    id: str
    title: str
    description: str  # shown on the demo's fault-picker card, human-only
    deploy_branch: str
    target_commit_message: str  # ground truth, never shown to the pipeline
    runbook_filename: str


FAULT_SCENARIOS: dict[str, FaultScenario] = {
    "checkout-n-plus-one": FaultScenario(
        id="checkout-n-plus-one",
        title="Checkout N+1 query",
        description=(
            "Replaces the batched product lookup in checkout with a per-item "
            "query loop. Checkout latency spikes with cart size while every "
            "other endpoint stays healthy."
        ),
        deploy_branch="deploy/r-142",
        target_commit_message="perf: fetch product details individually during checkout summary",
        runbook_filename="checkout-slow-query-runbook.md",
    ),
    "cache-ttl-misconfigured": FaultScenario(
        id="cache-ttl-misconfigured",
        title="Cache TTL misconfigured",
        description=(
            "Drops the catalog cache TTL from 300s to 1s. The catalog endpoint "
            "starts rebuilding constantly, so its latency and DB query volume "
            "jump while checkout stays fast."
        ),
        deploy_branch="deploy/r-143",
        target_commit_message="chore: tune cache TTL for product catalog",
        runbook_filename="cache-ttl-runbook.md",
    ),
    "null-pointer-payment-webhook": FaultScenario(
        id="null-pointer-payment-webhook",
        title="Payment webhook null pointer",
        description=(
            "Removes the guard for refund/dispute webhooks that arrive without "
            "a charge object. A chunk of payment webhooks starts returning 500."
        ),
        deploy_branch="deploy/r-144",
        target_commit_message="refactor: simplify charge webhook handler",
        runbook_filename="payment-webhook-null-pointer-runbook.md",
    ),
    "connection-pool-config-rollout": FaultScenario(
        id="connection-pool-config-rollout",
        title="DB connection pool slashed",
        description=(
            "A staging override (DB_POOL_SIZE 50 → 5) lands on main. Requests "
            "queue for connections under load, so latency inflates across every "
            "endpoint at once."
        ),
        deploy_branch="deploy/r-145",
        target_commit_message="config: apply staging pool size override",
        runbook_filename="connection-pool-config-runbook.md",
    ),
}
