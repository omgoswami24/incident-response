# Autonomous AI Incident Response — Technical Deep Dive

> This document is a complete, self-contained technical description of the
> project. It is written to be pasted into an LLM as context so you can ask
> detailed questions about the system. Everything below reflects the actual
> code in this repository.

---

## 0. One-paragraph summary

This is a **closed-loop AI Site-Reliability-Engineering (SRE) agent** demonstrated
against a **real running service**. It runs a toy e-commerce API under continuous
synthetic load, lets you inject a *real* regression by deploying a bad git commit,
and then autonomously: **detects** the degradation from live metrics, **diagnoses**
the offending commit with an LLM reading real git diffs, retrieves a **runbook**
via RAG, estimates **business impact** from measured traffic, posts a **Slack brief**,
and — on one human approval — **remediates** by `git revert` + redeploy, then
**verifies recovery** against the same metrics and writes a **postmortem**. The
design thesis is *verification over trust*: every claim the system makes about
itself is checked against a measurement, so a wrong diagnosis surfaces as a failed
remediation rather than a false success. The AI is never told the answer.

---

## 1. The core design principles (the "why")

1. **Nothing is scripted.** The load is identical whether the deployed code is
   healthy or broken; degradation shows up only in measurements. The detector is
   never told a fault was injected. The diagnosis LLM sees only what a human
   on-call engineer would: an alert composed from metrics, plus recent git history.

2. **The AI cannot grade its own homework.** The injected scenario is stored as
   *hidden ground truth* on the incident row and is used **only after** the LLM
   commits to an answer, to score it (`✓`/`✗`). Ground truth never enters any
   prompt. Remediation success is judged by whether live metrics actually recover,
   not by the model asserting success.

3. **Verification over trust.** Remediation is "done" only when the same baseline
   the detector learned says the service recovered. A wrong diagnosis leads either
   to a revert that conflicts (caught, aborted, service restored) or a revert that
   applies but doesn't fix anything (caught by the metric verifier). Both are
   first-class UI states, not crashes.

4. **Human-in-the-loop where it matters.** Detection, diagnosis, impact estimation,
   and evidence gathering are autonomous. The actual `git revert` requires one
   explicit human approval click.

5. **Everything free to run.** Google Gemini free tier (with a model fallback
   chain), local Chroma embeddings, SQLite, no paid external accounts required.

---

## 2. System topology: two apps, several concurrent runtimes

There are **two separate applications** in this repo:

- **`backend/`** — the "SRE agent" / control plane. A FastAPI app (port **8000**).
  This is where the intelligence lives: metrics store, anomaly detector, diagnosis
  pipeline, remediation, adapters, state machine, SQLite persistence, SSE.

- **`ecommerce-app/`** — the "target app" / victim. A separate FastAPI service
  (port **8001**) with its own git repository. This is the thing that breaks. It is
  **run as a child process** of the backend and is deployed to by checking out git
  branches.

- **`frontend/`** — a React + TypeScript + Vite dashboard (dev server port **5173**)
  that renders the whole thing.

### Concurrency model inside the backend (important)

The backend's single Python process hosts several concurrent runtimes:

- **The asyncio event loop** (uvicorn) serving the HTTP API.
- **The load generator**: `asyncio.gather` of **32 "virtual user" coroutines**
  (`load_workers`), each in a loop hammering the target app over HTTP.
- **The anomaly detector**: one long-running asyncio task ticking every **2s**.
- **The target app**: a **separate OS process** (`subprocess.Popen` running
  `uvicorn main:app` with `cwd=ecommerce-app/`), managed by `TargetAppManager`.
- **The diagnosis / remediation / postmortem pipelines**: run **off the event
  loop in threads** via `asyncio.to_thread(...)` (detector-triggered) or FastAPI
  `BackgroundTasks` (user-triggered), because they make blocking LLM HTTP calls
  and blocking `git` subprocess calls.

This mix of asyncio tasks + threads + a child process + a shared git working tree
is the source of the concurrency bugs described in §14, and why a lock
(`manager.repo_lock`) coordinates repo mutation against pipeline git reads.

---

## 3. The target app (`ecommerce-app/`) — the thing that breaks

A small FastAPI storefront. Files:

- **`main.py`** — routes:
  - `GET /products` — returns the full catalog. Reads from an in-process TTL cache;
    on a miss it calls `load_full_catalog()` (an *expensive* build: **8 sequential
    simulated DB queries**) and re-caches.
  - `GET /products/{id}` — one product + related products (2 DB queries).
  - `POST /checkout/summary` — prices a cart. **Healthy version uses a single
    batched query** (`get_products_by_ids`) regardless of cart size.
  - `POST /webhooks/payments` (in `payments.py`) — Stripe-style webhook. **Healthy
    version guards `if payload.charge is None`** because refund/dispute events
    legitimately omit the charge object.
  - `GET /recommendations/{id}` — feature-flagged placeholder (always empty).
  - `GET /health` — readiness probe used by the manager to know the child booted.

- **`db.py`** — **the clever part: a simulated DB with *real* concurrency.**
  - There is no external database. Query *latency* is simulated with
    `asyncio.sleep(random.uniform(0.012, 0.024))`.
  - But **concurrency is real**: every query first acquires a slot from an
    `asyncio.Semaphore(DB_POOL_SIZE)` (the "connection pool"), holds it for the
    simulated round-trip, then releases. Acquisition has a **1.5s timeout**; if no
    connection frees up in time it raises `PoolExhaustedError` → the app returns
    **HTTP 503**.
  - **Consequence:** query *count* and pool *size* have genuine, measurable latency
    effects under load. An N+1 query pattern or a shrunken pool actually starves
    the semaphore and inflates measured p95 — the metrics aren't faked.

- **`cache.py`** — a tiny monotonic-clock TTL cache. `catalog_cache` has TTL
  `CACHE_TTL_SECONDS` (healthy = **300s**).

- **`config.py`** — the knobs the faults target: `CACHE_TTL_SECONDS = 300`,
  `DB_POOL_SIZE = 50`, plus feature flags.

---

## 4. The four fault scenarios (exact mechanics)

Defined in `backend/app/seed/fault_scenarios.py`. Each maps to a **deploy branch**
whose git history contains one bad commit **buried among noise commits**. Branch
names are deliberately neutral release names (`deploy/r-142` … `r-145`) so nothing
the diagnosis sees encodes which fault is present. `target_commit_message` is the
**ground truth** (used only for post-hoc scoring; never shown to the LLM).

| id | title | branch | ground-truth commit | mechanism | signature |
|---|---|---|---|---|---|
| `checkout-n-plus-one` | Checkout N+1 query | `deploy/r-142` | `perf: fetch product details individually during checkout summary` | Replaces the single batched `get_products_by_ids` with a **per-item `get_product` loop** (N queries per checkout) | Checkout p95 spikes and scales with cart size; other endpoints stay healthy |
| `cache-ttl-misconfigured` | Cache TTL misconfigured | `deploy/r-143` | `chore: tune cache TTL for product catalog` | Drops catalog cache TTL **300s → 1s** | `GET /products` constantly rebuilds the catalog (8 queries each) → its latency + DB query volume jump; checkout stays fast |
| `null-pointer-payment-webhook` | Payment webhook null pointer | `deploy/r-144` | `refactor: simplify charge webhook handler` | **Removes the `if charge is None` guard** | ~35% of webhooks (refunds/disputes, which carry no charge) start throwing → **HTTP 500** on `POST /webhooks/payments` |
| `connection-pool-config-rollout` | DB connection pool slashed | `deploy/r-145` | `config: apply staging pool size override` | `DB_POOL_SIZE` **50 → 5** | The semaphore starves under load → latency inflates across **every** endpoint at once, plus `PoolExhaustedError` **503s** |

These are deliberately diverse: a code perf bug (N+1), a config value (TTL), a
deleted null-guard (500s), and an infra/resource config (pool size / 503s). They
exercise latency-only, error-only, single-endpoint, and all-endpoint signatures.

---

## 5. Git-based fault injection & deployment (`app_manager.py`)

`TargetAppManager` (singleton `manager`) owns the target app process and its git
working tree. Key operations, **all guarded by `self.repo_lock` (a `threading.RLock`)**:

- **`start()` / `stop()`** — spawn/terminate the child `uvicorn` process
  (`cwd=ecommerce-app/`), waiting on `GET /health` up to 20s to confirm readiness.
- **`deploy_scenario(scenario)`** ("inject a fault"):
  1. `stop()` the child,
  2. `seed()` — **`shutil.rmtree` the repo and rebuild it from scratch** (this
     restores pristine branches, undoing any prior revert commits),
  3. `git checkout <deploy_branch>`,
  4. `start()` the child on the bad code,
  5. record `last_deploy_ts` and `deployed_scenario_id`.
- **`revert_commit(sha)`** ("approve the fix"): `stop()`, `git revert <sha>
  --no-edit`, `start()`. On a merge conflict it `git revert --abort`s, restarts on
  the unchanged code, and raises `RevertFailedError` (surfaced as "remediation
  failed"). Returns the revert commit's SHA.
- **`reset()`**: back to pristine healthy `main` + fresh child process.
- **`ground_truth_commit_sha()`**: finds the SHA of the seeded bad commit on the
  deployed branch by matching `target_commit_message`. Used only for scoring.

The repo itself is generated by `seed_ecommerce_repo.py`: it builds `main`
(11 commits) plus 4 deploy branches (each = main + a few commits, one of which is
the real regression, the rest noise like docstring tweaks and reformatting).

**Why the rmtree matters:** because injecting/resetting rebuilds the repo, commit
SHAs are regenerated each time, and the working directory momentarily disappears —
this is exactly what the pipeline's git reads have to be synchronized against
(§14).

---

## 6. Metrics engine (`live/metrics.py`)

A thread-safe in-memory observability store (`store`), deliberately ignorant of
fault scenarios — it's plain telemetry.

- **`Sample`** = `(ts, group, latency_ms, status)`. Endpoint "groups" are the 4
  route templates (e.g. `POST /checkout/summary`).
- **`record(...)`** appends a sample (bounded `deque(maxlen=100_000)`) under a lock,
  plus keeps the last 50 5xx **response bodies** (real diagnostic signal — e.g. a
  pool-exhaustion 503 names the pool in its `detail`).
- **`group_stats(seconds)`** — per-group over a trailing window: `count`, `rps`,
  `p50_ms`, `p95_ms`, `error_rate_pct`. Percentile is a simple sorted-index method.
- **`recent_error_samples(seconds)`** — recent 5xx body snippets.
- **`series(seconds=240, bucket_s=5)`** — bucketed p95/error-rate time series for
  the dashboard sparklines.

Everyone reads this one store: the detector, the remediation verifier, the impact
estimator, and the dashboard.

---

## 7. Load generator (`live/traffic.py`)

- `run_load()` opens one shared `httpx.AsyncClient` and runs **32 worker
  coroutines** (`settings.load_workers`).
- Each worker loops: issue one request → record the sample → `sleep` a random
  "think time" of **20–80ms**. Aggregate throughput is on the order of **~450 req/s**.
- **Workload mix** (per request, by random roll): **35%** `GET /products`, **25%**
  `GET /products/{id}`, **25%** `POST /checkout/summary` (cart of 4–9 items),
  **15%** `POST /webhooks/payments` (of which **~35% are refunds/disputes with no
  charge object** — precisely the case the null-guard protects).
- If the target app is mid-restart (HTTP error), the worker backs off **without**
  recording a sample, so deploys don't pollute metrics. Workers never die
  (broad try/except).

The mix is fixed regardless of deployed code — degradation must emerge from
measurement, not workload.

---

## 8. The anomaly detector (`live/detector.py`) — "blind" detection

A singleton `detector` running one asyncio task, ticking every **`TICK_S = 2.0s`**.
It has **no knowledge of what (or whether) a fault was injected**.

**Baseline learning.** It maintains a per-endpoint baseline (p95, error rate),
learned **only while demonstrably healthy**:
- no active incident, AND
- the entire baseline window post-dates the last deploy
  (`since_deploy > BASELINE_WINDOW_S(45) + DEPLOY_GRACE_S(12)`), AND
- refreshed at most every `BASELINE_REFRESH_S(20)`,
- and only if every group has ≥ `MIN_SAMPLES(20)` samples in the
  `BASELINE_WINDOW_S(45s)` window.

**Breach rule** (`_find_breaches`, over the trailing `DETECTION_WINDOW_S = 15s`):
a group is breaching if
```
(p95 > 2 * baseline_p95  AND  p95 > baseline_p95 + 30ms)   # latency
   OR
 error_rate > max(5.0, baseline_error + 5)                  # errors
```
The **`+30ms` absolute floor** stops fast/low-baseline endpoints from tripping on
noise. (The frontend's "DEGRADED" chip was later aligned to this exact rule — §14.)

**Persistence & grace.** A breach must persist for **`CONSECUTIVE_TICKS = 2`**
consecutive ticks before firing (anti-flap). Detection is suppressed for
`DEPLOY_GRACE_S = 12s` after a deploy (cold-start noise) and whenever an incident
is already active.

**Firing.** On a confirmed breach it composes an **alert text entirely from
measured numbers** (degraded endpoints with p95/ratio/throughput, nominal
endpoints, and recent 5xx body snippets), creates an `Incident` row, snapshots the
baseline and detection-window stats onto it, stamps the **hidden ground truth**
(`ground_truth_scenario_id`, `ground_truth_commit_sha`), transitions it to
`firing`, and launches the diagnosis pipeline via `asyncio.to_thread(run_pipeline)`.
The detector is a watchdog: its tick loop never dies (broad try/except).

---

## 9. The diagnosis pipeline (`pipeline/orchestrator.py`)

`run_pipeline(incident_id)` runs in a thread. It sees only the alert text + the
deployed branch's git history. Sequence of state transitions & steps:

1. **`analyzing`** — transition + timeline event.
2. **Commit analysis** (`pipeline/commit_analysis.py`):
   - **Snapshots** the last 15 commits and *all their diffs* up front **while
     holding `manager.repo_lock`** (so a concurrent reseed can't delete the repo
     mid-read or invalidate SHAs during the slow LLM call — §14).
   - Builds a candidate list (`### Candidate i` with message/author/date/files/diff).
   - Calls the LLM (`complete_json`) with a **system prompt encoding standard RCA
     priors**: prefer recent commits (the anomaly is new), distinguish
     *introducing* a subsystem long ago from *recently changing* it, treat
     config-only changes (timeouts, TTLs, pool sizes, flags) as prime suspects,
     only pick an old commit if no recent one explains the alert. Output is strict
     JSON: `{suspected_candidate_number, reasoning, confidence}`.
   - Validates the index, and **reuses the snapshotted diff** for the suspected
     commit (no post-LLM git read).
   - **Scoring:** back in the orchestrator, `diagnosis_correct` is computed
     **server-side, after** the answer, by comparing the picked SHA to
     `ground_truth_commit_sha`. This comparison never happens in a prompt.
   - Transition/timeline: `commit_identified`.
3. **Runbook RAG** (`pipeline/runbook_rag.py`):
   - Local **Chroma** persistent vector store (`chromadb.PersistentClient`),
     collection `runbooks`, seeded from `runbooks/*.md` by `seed_runbooks.py`
     (Chroma computes the embeddings with its default local model).
   - Query text is **not** the raw alert — it's the alert **plus the diagnosed
     commit message + the LLM's reasoning**, because "alert text alone is generic
     metric-speak; anchoring on the diagnosed change makes retrieval far more
     discriminating." Returns the single nearest runbook.
   - Timeline: `runbook_retrieved`.
4. **Impact estimate** (`pipeline/impact_estimator.py`) — see §10.
5. **Slack brief** (`pipeline/slack_brief.py`) — builds Slack Block Kit blocks
   (header, alert, severity/traffic/revenue/requests fields, suspected commit,
   reasoning, proposed remediation, runbook), posts via the Slack adapter, and
   transitions to **`briefed`** (awaiting human approval).

Error handling: an `InvalidTransitionError` caused by the incident being
closed/superseded mid-flight is caught and the pipeline **abandons quietly**;
other exceptions are recorded via `record_error` (sets `error_message`, keeps the
incident where it is, surfaces a Retry button). Rate-limit exhaustion produces a
clear "LLM rate-limited, wait ~60s" message.

---

## 10. Impact estimation (`pipeline/impact_estimator.py`) — measured, not canned

Inputs are the frozen healthy baseline and the degraded detection-window stats
captured on the incident. The **only** assumption is a business constant, average
order value (`avg_order_value_usd = $74`); throughput, error rates, and latency
inflation are all **measured**.

- A group is "degraded" if `latency_ratio ≥ 2` or `error_delta ≥ 5`.
- **Revenue at risk / hr** is computed only over revenue-bearing endpoints
  (`POST /checkout/summary`, `POST /webhooks/payments`):
  `rps * 3600 * failure_fraction * AOV`, where `failure_fraction = min(1,
  error_rate/100 + abandonment)` and abandonment = **10% at ≥2× latency, 25% at
  ≥3×** (hard errors always count fully).
- **Severity**: `critical` if payments are broken (webhook error ≥5%) or ≥3
  endpoints degraded; `high` if checkout degraded; `medium` if any degraded; else
  `low`.
- Also reports `affected_traffic_pct` and `requests_affected_per_hr`, plus a
  `method` string documenting the calculation.

---

## 11. Remediation & verification (`pipeline/remediation.py`)

`run_remediation(incident_id)` runs after the human clicks **Approve Fix** (only
valid from `briefed`, requires a suspected SHA):

1. Transition **`remediating`**.
2. **`manager.revert_commit(suspected_sha)`** → `git revert` + redeploy. On
   conflict → `RevertFailedError` → mark `remediation_verified = False`, timeline
   `remediation_failed` ("service is back up on unreverted code; manual
   intervention required"), stop.
3. **Verify recovery from live metrics** (the honest part):
   - Wait `VERIFY_GRACE_S = 10s` for fresh traffic to hit the redeployed app.
   - Poll every `VERIFY_POLL_S = 3s`, up to `VERIFY_TIMEOUT_S = 90s`, computing
     stats over a `VERIFY_WINDOW_S = 12s` window.
   - "Recovered" (`_recovered`) requires **every** baselined group back within
     tolerance: `p95 ≤ max(1.6×baseline, baseline+25ms)` **and**
     `error_rate ≤ max(2%, baseline+2)`, and this must hold for
     `CONSECUTIVE_OK_POLLS = 2` consecutive polls.
   - **If recovered:** record before/after summary + recovery stats, transition
     **`resolved`** (timeline `recovery_verified`), then generate the postmortem.
   - **If not recovered within timeout:** `remediation_verified = False`, timeline
     `remediation_failed` ("metrics did not recover — the diagnosis may be wrong").
     The system cannot fake success; a wrong diagnosis reverts the wrong commit,
     metrics don't recover, and it says so.

The alternative path is **Resolve Manually** (from `briefed`), which skips
auto-remediation and jumps to `resolved` + postmortem.

---

## 12. Postmortem, state machine, data model, real-time layer, adapters

- **Postmortem** (`pipeline/postmortem.py`): an LLM generates a markdown report
  (Summary / Timeline / Root Cause / Impact / Detection / Resolution / Action
  Items) strictly from recorded incident evidence (alert, timeline, diagnosed
  commit + diff, runbook, measured impact, revert + recovery stats). Transition
  **`postmortem_generated`** (terminal).

- **State machine** (`state_machine.py`): the single choke point for status
  changes. `ALLOWED_TRANSITIONS` enforces the legal graph:
  `firing → analyzing → briefed → {remediating|resolved} → …`, with `closed`
  reachable from any non-terminal state (operator override). `transition()`
  validates, updates timestamps, appends a `TimelineEvent`, commits, and
  **broadcasts over SSE**. `record_error()` sets an error without advancing status.
  Invalid transitions raise `InvalidTransitionError`.

- **Data model** (`models.py`, SQLModel over SQLite): two tables.
  - `Incident` — one wide row holding *everything*: status, the detection evidence
    (`detected_alert_text`, `baseline_json`, `detection_stats_json`), the hidden
    ground truth (`ground_truth_*`, `diagnosis_correct`), the diagnosis
    (`suspected_commit_*`, reasoning, confidence), runbook fields, `impact_json`,
    `slack_brief_json`, remediation fields (`remediation_revert_sha`,
    `remediation_verified`, `recovery_stats_json`), and `postmortem_markdown`.
  - `TimelineEvent` — append-only event log per incident (type, title, JSON detail).

- **Real-time layer**: `events.py` is an in-process pub/sub (`IncidentEventBroadcaster`),
  one `asyncio.Queue` per incident fanned out to SSE subscribers. `routers/stream.py`
  exposes `GET /api/incidents/{id}/stream` as Server-Sent Events (15s ping
  heartbeat). The frontend also **polls** incidents (3s), metrics (2s), and
  environment (5s) as a simpler backstop for list/metrics views.

- **Adapter pattern** (`adapters/`): `GitHubAdapter` and `SlackAdapter` are
  `typing.Protocol`s. Defaults are **mock/local** (`LocalGitAdapter` reads the real
  local git repo; `MockSlackAdapter` records the payload). Real implementations
  (`RealGitHubAdapter`, `RealSlackAdapter`) swap in purely via env vars through
  `adapters/factory.py` — no pipeline code changes. `factory.py` deliberately
  builds a **fresh adapter per call** (never cached), because a cached GitPython
  `Repo` would point at git objects deleted by the next reseed.
  `tests/test_adapter_conformance.py` runs the same suite against both mock and
  real adapters (real ones only when credentials are present).

- **LLM client** (`adapters/llm/llm_client.py`): wraps **LiteLLM**. A **model chain**
  (`gemini-2.5-flash-lite` → `gemini-2.5-flash`) with **3 retries per model** and
  exponential backoff (3s, 6s, 12s) over retryable errors (rate limit, service
  unavailable, timeout, connection, internal). `complete_json` extracts the first
  `{...}` JSON object from the response. If the whole chain fails on rate limits,
  it raises a clear, actionable `RuntimeError`.

---

## 13. Frontend (`frontend/`, React 19 + TS + Vite)

Single-page dashboard. Key pieces:

- **`App.tsx`** — orchestrates state; polls incidents/metrics/environment; renders
  the sidebar incident list + main column. When no incident is selected it shows
  the live metrics, a **pipeline strip** (`deploy → detect → diagnose → verify`),
  and the fault picker. When an incident is selected it shows a three-column ops
  console: **Timeline + detected alert** | **AI diagnosis + ground-truth verdict +
  measured impact + runbook** | **Slack brief + postmortem**.
- **`MetricsPanel.tsx`** — per-endpoint cards with inline SVG **sparklines** (p95
  over ~4 min, dashed baseline line, red dots on error buckets). The **"DEGRADED"
  chip logic mirrors the backend detector's breach rule** (`2× baseline AND
  +30ms`, or `error > max(5, base+5)`) so the UI never contradicts the detector.
- **`IncidentTimeline.tsx`**, **`SlackBriefCard.tsx`**, **`PostmortemView.tsx`**
  (react-markdown), **`FaultPicker.tsx`**, **`EnvironmentBar.tsx`**.
- **`api.ts`** — fetch helpers + polling/SSE hooks. **`types.ts`** — shared types.
- Styling is a hand-written dark design system in `index.css` (CSS custom
  properties, tabular numerals, reduced-motion handling).

---

## 14. Concurrency bugs that were found & fixed (real engineering story)

The system originally cascaded into errors when a user clicked around quickly.
Root causes and fixes:

1. **Reseed-vs-pipeline git race.** `seed()` does `shutil.rmtree(ecommerce-app)`
   on every inject/reset, while the diagnosis pipeline reads that repo with `git`
   in a background thread. Nothing synchronized them, so a reseed could delete the
   working directory out from under a running `git diff` →
   `fatal: Unable to read current working directory`, cascading into every
   subsequent operation.
   **Fix:** the pipeline now **snapshots all commits + diffs up front while holding
   `manager.repo_lock`** — the same lock reseeds take — so the two can't interleave.

2. **Stale commit SHAs after reseed.** Every reseed regenerates SHAs; an old
   suspected SHA (or a diff re-read after the slow LLM call) could resolve to
   `SHA … missing`.
   **Fix:** the slow LLM call now runs against the in-memory snapshot and the
   suspected diff is **reused** (no post-LLM git read to go stale).

3. **Closing an incident mid-pipeline crashed it.** A reset closes the active
   incident; a still-running pipeline then hit
   `InvalidTransitionError: Cannot transition from closed to briefed`.
   **Fix:** all three pipeline entry points (diagnosis, remediation, postmortem)
   detect a superseded/closed incident and **abandon quietly** instead of crashing.
   Covered by a regression test.

4. **Opaque rate-limit failures.** Gemini's free tier gets exhausted under heavy
   testing; failures surfaced as generic pipeline errors.
   **Fix:** exhaustion of the model chain on rate limits now raises a clear,
   actionable message; the app degrades gracefully instead of cascading.

5. **Over-sensitive frontend "degraded" chip.** The dashboard used
   `p95 > 2×baseline + 1ms` (no absolute floor, no persistence), so fast endpoints
   flickered "DEGRADED" on normal jitter even with no fault deployed.
   **Fix:** aligned the chip to the detector's real rule (`2× AND +30ms`).

**Verification:** ran the exact trigger (inject → reset mid-flight → inject again)
and confirmed **0** working-directory errors, **0** stale-SHA errors, **0**
uncaught tracebacks, with a subsequent incident diagnosing correctly. Backend
suite: 24 passed, 2 skipped.

---

## 15. How to run it

```bash
# .env at repo root: paste a free Gemini key into GEMINI_API_KEY
#   (https://aistudio.google.com/apikey)

# Backend (also seeds + runs the target app + load generator + detector)
cd backend
uv venv --python 3.12 && uv sync --group dev && source .venv/bin/activate
python -m app.seed.seed_runbooks          # one-time: runbooks -> Chroma
uvicorn app.main:app --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev  # http://localhost:5173
```

On boot the backend's `lifespan` closes stale incidents, resets the target app to
pristine `main`, and starts the load generator + detector. The detector needs
~1 minute of healthy traffic to learn a baseline before fault injection unlocks.
`POST /api/environment/reset` (or the Reset button) returns to pristine main.

**Tests:** `cd backend && source .venv/bin/activate && python -m pytest tests/ -q`
(run as a module so `app` is importable). Covers the state machine, the pipeline
with a mocked LLM (correct/wrong/superseded/error paths), metrics windowing,
detector breach logic, recovery verification, and adapter conformance.

**Selected constants** (all tunable): `TICK_S=2`, `DETECTION_WINDOW_S=15`,
`BASELINE_WINDOW_S=45`, `DEPLOY_GRACE_S=12`, `CONSECUTIVE_TICKS=2`,
`VERIFY_TIMEOUT_S=90`, `CONSECUTIVE_OK_POLLS=2`, `load_workers=32`,
`DB_POOL_SIZE=50` (healthy), `CACHE_TTL_SECONDS=300` (healthy),
`avg_order_value_usd=74`.

---

## 16. Honesty ledger (what's real vs. simulated)

| Component | Real or simulated |
|---|---|
| Target app + traffic | **Real** — FastAPI service under continuous closed-loop load; latency/error measurements are genuine |
| DB latency | **Simulated latency, real concurrency** — each query holds a real fixed-size semaphore slot for a simulated round-trip, so query counts and pool sizing have true consequences under load |
| Fault injection | **Real deploys** — `git checkout` of a branch with a seeded bad commit + process restart |
| Anomaly detection | **Real** — learned baseline vs trailing window; no knowledge of what/whether anything was injected |
| Commit diagnosis | **Real LLM reasoning** over real git diffs; can be (and sometimes is) wrong |
| Runbook retrieval | **Real vector search** (Chroma, local embeddings) |
| Impact estimate | **Measured** throughput/latency/errors × a configured AOV constant |
| Remediation + verification | **Real** — `git revert`, redeploy, recovery judged from live metrics against the learned baseline |
| Slack / GitHub | **Mocked by default** behind `Protocol` adapters; real implementations exist and swap in via env vars |
| Postmortem | **Real LLM generation** from recorded incident evidence |

---

## 17. Known limitations / honest caveats (good interview fodder)

- **LLM quota:** the free Gemini tier rate-limits under rapid injection; the fix
  makes this degrade gracefully (clear message + Retry), not cascade. A paid key
  removes it.
- **Single-node, in-process:** metrics store, event bus, and the target-app
  manager are all in one process; there's no horizontal scaling or durability of
  metrics across restarts (incidents *are* persisted in SQLite).
- **Simulated DB:** latency is simulated (concurrency is real). A real DB would add
  query-plan realism but wouldn't change the detection/diagnosis loop.
- **Resetting mid-incident** abandons an in-flight pipeline by design; the diagnosis
  it was producing is discarded rather than reconciled against the new environment
  generation.
- **RAG corpus is tiny** (4 runbooks, 1-nearest retrieval) — it demonstrates the
  pattern rather than production-scale retrieval.

---

## 18. Suggested questions to explore (for the reader)

- Why does blind detection (baseline learned only while healthy, 2-tick
  persistence, +30ms floor) matter, and what false positives/negatives does each
  guard prevent?
- Walk through what happens end-to-end for the `connection-pool-config-rollout`
  fault, from semaphore starvation to the 503 body appearing in the alert text.
- Why is `diagnosis_correct` computed server-side after the LLM answers instead of
  asking the model to self-assess?
- How does the metric-based recovery verifier catch a *wrong* diagnosis?
- Why snapshot git under a lock before the LLM call instead of just retrying on
  failure? What class of bug does that eliminate?
- How would you extend the adapters to real GitHub + real Slack, and what stays
  unchanged?
