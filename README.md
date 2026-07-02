# Autonomous AI Incident Response System

A demo SRE-automation system: when a production alert fires, it identifies the
likely bad commit via LLM-powered diff reasoning, retrieves the relevant
runbook via RAG, estimates user/revenue impact, posts a structured Slack
brief, and — once resolved — generates a full postmortem. A React dashboard
shows the whole thing happening live.

The GitHub commit analysis is **self-referential**: `ecommerce-app/` is a
small, real toy storefront that is its own git repository, seeded with a
handful of genuinely bad commits mixed into realistic noise history. The
"Inject Fault" button tells the system which fault to hunt for, and the LLM
has to correctly pick the right commit out of ~15 recent candidates — a real
reasoning task, not a canned demo.

Slack and GitHub are mocked by default (no external accounts needed) but
built behind adapter interfaces so real integrations are a config change, not
a rewrite. Commit analysis and postmortem generation use real LLM calls.

## Setup

Requires Python 3.12, Node 18+, and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Get a free Gemini API key (no credit card required):
#    https://aistudio.google.com/apikey
cp .env.example .env
# edit .env and paste your key into GEMINI_API_KEY

# 2. Backend
cd backend
uv venv --python 3.12
uv sync --group dev
source .venv/bin/activate

# 3. Seed the ecommerce-app git repo (bad commits + noise history)
python -m app.seed.seed_ecommerce_repo

# 4. Seed the runbooks into the local Chroma vector store
python -m app.seed.seed_runbooks

# 5. Run the backend
uvicorn app.main:app --port 8000

# 6. In a separate terminal: frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, click a fault card, and watch the incident
timeline update live.

## Architecture

- `backend/app/pipeline/` — the 5-step pipeline: commit analysis, runbook
  RAG, impact estimation, Slack brief, postmortem generation.
  `orchestrator.py` runs it as a FastAPI `BackgroundTask` per incident.
- `backend/app/adapters/` — `GitHubAdapter` and `SlackAdapter` are defined as
  `Protocol`s in `github/base.py` / `slack/base.py`. `local_git_adapter.py`
  and `mock_slack_adapter.py` are the defaults; `real_github_adapter.py` and
  `real_slack_adapter.py` implement the same interface against the real
  APIs. `adapters/factory.py` picks mock vs real from env vars.
- `backend/app/state_machine.py` — the single choke point for incident
  status transitions (`firing → analyzing → briefed → resolved →
  postmortem_generated`); every transition also writes a `TimelineEvent` and
  broadcasts it over SSE.
- `backend/app/seed/` — `seed_ecommerce_repo.py` programmatically builds
  `ecommerce-app/`'s git history (18 commits: baseline + noise + 4 seeded bad
  commits at varying depths). `seed_runbooks.py` ingests `runbooks/*.md` into
  a local persistent Chroma collection.
- `frontend/src/` — React dashboard. `api.ts`'s `useIncidentStream` hook
  drives live updates via Server-Sent Events (`GET
  /api/incidents/{id}/stream`).

## Going live with real Slack/GitHub

Both adapters are mocked by default so the demo runs with zero external
accounts. To use the real APIs instead:

```bash
# .env
GITHUB_ADAPTER=real
GITHUB_OWNER=your-org
GITHUB_REPO=your-repo
GITHUB_TOKEN=ghp_...

SLACK_ADAPTER=real
SLACK_BOT_TOKEN=xoxb-...
```

No code changes are needed — the pipeline only ever depends on the
`GitHubAdapter`/`SlackAdapter` protocols, and `adapters/factory.py` swaps the
concrete implementation based on these env vars.
`tests/test_adapter_conformance.py` runs the same behavioral test suite
against both the mock and real adapters (the real ones are skipped
automatically when credentials aren't present).

## Tests

```bash
cd backend && source .venv/bin/activate && pytest tests/ -v
```
