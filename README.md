# Autonomous AI Incident Response

A closed-loop AI SRE agent, demonstrated against a real running service:

**detect → diagnose → remediate → verify → document** — with no step scripted.

## The problem

When production breaks, most of the time-to-recovery is not spent fixing
anything — it's spent *figuring out what changed*. An on-call engineer gets
paged, stares at dashboards, digs through recent deploys, guesses at a
culprit, reverts, and watches the graphs. Mean time to recovery is dominated
by diagnosis, and diagnosis is exactly the kind of evidence-correlation work
LLMs are good at — *if* you can trust the loop around them.

This project builds that loop end-to-end, and — the part that matters —
**verifies the AI's work with measurements instead of taking its word for it**:

1. A toy e-commerce service runs for real, under continuous synthetic load
   (~450 req/s), with live p95/error-rate metrics per endpoint.
2. "Inject fault" **actually deploys a bad commit**: it checks out a branch
   whose git history contains a genuine regression (an N+1 query, a fat-
   fingered cache TTL, a deleted null-guard, a wrong pool size) buried among
   noise commits, and restarts the service. The service genuinely degrades.
3. An **anomaly detector** — which is never told a fault was injected —
   compares live metrics against a baseline it learned while the service was
   healthy, and opens an incident with alert text composed entirely from
   measured numbers.
4. An LLM reads that alert plus the last ~15 commits (message + full diff)
   and picks the culprit. The injected scenario is stored only as hidden
   ground truth; **the diagnosis is scored against it after the LLM commits
   to an answer**, and the dashboard shows ✓/✗ honestly.
5. A runbook is retrieved via RAG (local Chroma vector store), impact is
   estimated **from the measured traffic** (degraded throughput × error/
   abandonment fractions × average order value), and a Slack brief is posted
   with a proposed fix.
6. On one human click of approval, the system **`git revert`s the suspected
   commit, redeploys, and watches the metrics recover** before resolving.
   If the diagnosis was wrong, the metrics don't recover (or the revert
   doesn't apply) and the incident says so — the system cannot grade its own
   homework.
7. A full postmortem is generated from the recorded evidence.

A typical incident runs the whole loop in ~90 seconds, live on the dashboard.

## What's real vs. simulated (honesty ledger)

| Component | Real or simulated |
|---|---|
| Target app + traffic | **Real** — FastAPI service under continuous closed-loop load; latency/error measurements are genuine |
| DB latency | **Simulated latency, real concurrency** — each query holds a connection from a real fixed-size pool for a simulated round-trip, so query counts and pool sizing have true consequences under load |
| Fault injection | **Real deploys** — `git checkout` of a branch with a seeded bad commit + process restart |
| Anomaly detection | **Real** — learned baseline vs trailing window; it has no knowledge of what (or whether) anything was injected |
| Commit diagnosis | **Real LLM reasoning** over real git diffs; it can be (and sometimes is) wrong |
| Runbook retrieval | **Real vector search** (Chroma, local embeddings) |
| Impact estimate | **Measured** throughput/latency/errors × configured business constants (AOV) |
| Remediation + verification | **Real** — `git revert`, redeploy, recovery judged from live metrics against the learned baseline |
| Slack / GitHub | **Mocked by default** behind `Protocol` adapters; real implementations exist and swap in via env vars |
| Postmortem | **Real LLM generation** from recorded incident evidence |

The failure modes are real too: a wrong diagnosis leads to a revert that
either conflicts (caught, aborted, service restored, incident marked
"remediation failed") or applies without fixing anything (caught by the
metric verifier). Both paths are first-class UI states, not crashes.

## Architecture

```
┌─────────────────────────────  backend (FastAPI)  ─────────────────────────────┐
│                                                                               │
│  live/traffic.py ──► ecommerce-app (child uvicorn process, :8001)             │
│   32 virtual users      ▲ git checkout / revert + restart                     │
│        │                │                                                     │
│        ▼             live/app_manager.py ◄──────────── pipeline/remediation   │
│  live/metrics.py                                             ▲                │
│   rolling windows,      ┌──────────────────────────────┐     │ approve        │
│   p95 / error rate      │ pipeline/orchestrator        │     │                │
│        │                │  commit_analysis (LLM+diffs) │     │                │
│        ▼                │  runbook_rag     (Chroma)    │   incidents API      │
│  live/detector.py ────► │  impact_estimator (measured) │ ──► SSE stream ──► React
│   baseline vs window,   │  slack_brief     (adapter)   │       dashboard      │
│   opens incidents       │  postmortem      (LLM)       │                      │
│                         └──────────────────────────────┘                      │
│  state_machine.py — every status change validated, timelined, broadcast       │
└───────────────────────────────────────────────────────────────────────────────┘
```

- `backend/app/live/` — the environment: target-app process manager
  (deploy/revert/reset), closed-loop load generator, rolling metrics store,
  anomaly detector.
- `backend/app/pipeline/` — the agent: diagnosis, RAG, impact, brief,
  remediation + verification, postmortem.
- `backend/app/state_machine.py` — single choke point for incident status
  transitions (`firing → analyzing → briefed → remediating → resolved →
  postmortem_generated`, `closed` as operator override); every transition
  writes a timeline event and broadcasts over SSE.
- `backend/app/seed/seed_ecommerce_repo.py` — builds the target app's git
  repo: healthy `main` plus four neutral-named `deploy/r-*` branches, each
  hiding one real regression among noise commits. The app is genuinely
  runnable; its performance characteristics are what the detector measures.
- `backend/app/adapters/` — `GitHubAdapter` / `SlackAdapter` `Protocol`s with
  local/mock defaults and real API implementations
  (`tests/test_adapter_conformance.py` runs the same suite against both).
- `frontend/` — React dashboard: live per-endpoint sparklines vs baseline,
  incident timeline over SSE, diagnosis + ground-truth reveal, remediation
  approval, before/after recovery table, Slack brief, postmortem.

## Setup

Requires Python 3.12, Node 18+, and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Get a free Gemini API key (no credit card required):
#    https://aistudio.google.com/apikey
cp .env.example .env      # paste your key into GEMINI_API_KEY

# 2. Backend (also seeds + runs the target app and load generator)
cd backend
uv venv --python 3.12
uv sync --group dev
source .venv/bin/activate
python -m app.seed.seed_runbooks     # one-time: runbooks -> Chroma
uvicorn app.main:app --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The detector needs ~1 minute of healthy traffic
to learn its baseline; then pick a fault card and watch:

1. The deployed branch changes in the environment bar; metrics degrade for real.
2. The detector opens an incident (~15–30s) with measured alert text.
3. The LLM names a commit, with reasoning and confidence; ground truth is
   revealed alongside it (✓/✗).
4. Approve the remediation and watch the before/after recovery table fill in
   from live metrics, followed by the postmortem.

`POST /api/environment/reset` (or the Reset button) returns to pristine main.

## Tests

```bash
cd backend && source .venv/bin/activate && pytest tests/ -v
```

Covers the state machine (including failure/override paths), the diagnosis
pipeline with a mocked LLM (both correct and wrong diagnoses), metrics
windowing, detector breach logic (including the jitter guard and the
no-ground-truth-leak property of alert text), recovery verification, and
adapter conformance (real adapters exercised automatically when credentials
are present).

## Going live with real Slack/GitHub

```bash
# .env
GITHUB_ADAPTER=real
GITHUB_OWNER=your-org
GITHUB_REPO=your-repo
GITHUB_TOKEN=ghp_...

SLACK_ADAPTER=real
SLACK_BOT_TOKEN=xoxb-...
```

No code changes — the pipeline depends only on the adapter `Protocol`s and
`adapters/factory.py` swaps implementations from env vars.

## Design notes

- **The AI is never told the answer.** Alert text is composed from metrics;
  branch names are neutral (`deploy/r-142`); the injected scenario lives only
  in `ground_truth_*` fields used for post-hoc scoring. The prompt applies
  standard RCA priors (recency, config-change suspicion) rather than
  scenario-specific hints.
- **Verification over trust.** Remediation is only "done" when the same
  detector baseline says the service recovered. Wrong diagnoses surface as
  failed remediations, visibly.
- **Human-in-the-loop where it matters.** Detection, diagnosis, and evidence
  gathering are autonomous; the revert requires one explicit approval.
- **Everything free to run.** Gemini free tier (with model fallback chain),
  local Chroma embeddings, SQLite, no external accounts.
