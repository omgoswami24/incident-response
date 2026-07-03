import json
from datetime import datetime, timezone

from app.adapters.github.base import CommitInfo
from app.adapters.slack.mock_slack_adapter import MockSlackAdapter
from app.models import Incident, IncidentStatus
from app.pipeline import commit_analysis, orchestrator, postmortem

BAD_SHA = "bad" * 13 + "a"

BASELINE = {
    "POST /checkout/summary": {
        "count": 500,
        "rps": 40.0,
        "p50_ms": 20.0,
        "p95_ms": 26.0,
        "error_rate_pct": 0.0,
    },
    "GET /products": {
        "count": 700,
        "rps": 60.0,
        "p50_ms": 1.5,
        "p95_ms": 3.0,
        "error_rate_pct": 0.0,
    },
}

DETECTION = {
    "POST /checkout/summary": {
        "count": 480,
        "rps": 38.0,
        "p50_ms": 120.0,
        "p95_ms": 170.0,
        "error_rate_pct": 0.0,
    },
    "GET /products": {
        "count": 700,
        "rps": 60.0,
        "p50_ms": 1.5,
        "p95_ms": 3.2,
        "error_rate_pct": 0.0,
    },
}


def make_incident(**overrides) -> Incident:
    defaults = dict(
        detected_alert_text="AUTO-DETECTED ANOMALY — checkout p95 170ms vs baseline 26ms",
        baseline_json=json.dumps(BASELINE),
        detection_stats_json=json.dumps(DETECTION),
        ground_truth_commit_sha=BAD_SHA,
    )
    defaults.update(overrides)
    return Incident(**defaults)


class FakeGitHubAdapter:
    """Conforms to the GitHubAdapter protocol without touching real git."""

    def __init__(self):
        self._commits = [
            CommitInfo(
                sha=BAD_SHA,
                message="perf: fetch product details individually during checkout summary",
                author="Test Author",
                date=datetime.now(timezone.utc),
                files_changed=["main.py"],
            ),
            CommitInfo(
                sha="good" * 10,
                message="docs: update README",
                author="Test Author",
                date=datetime.now(timezone.utc),
                files_changed=["README.md"],
            ),
        ]

    def list_recent_commits(self, limit: int = 20):
        return self._commits[:limit]

    def get_diff(self, sha: str) -> str:
        return f"diff for {sha}"

    def get_commit(self, sha: str) -> CommitInfo:
        return next(c for c in self._commits if c.sha == sha)


def test_run_pipeline_reaches_briefed_and_scores_diagnosis(session, monkeypatch):
    monkeypatch.setattr(orchestrator, "engine", session.get_bind())
    monkeypatch.setattr(orchestrator, "get_github_adapter", lambda: FakeGitHubAdapter())
    monkeypatch.setattr(orchestrator, "get_slack_adapter", lambda: MockSlackAdapter())
    monkeypatch.setattr(
        commit_analysis,
        "complete_json",
        lambda *a, **k: {
            "suspected_candidate_number": 0,
            "reasoning": "This commit introduced a per-item DB lookup.",
            "confidence": 0.92,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "query_runbook",
        lambda *a, **k: {
            "runbook_id": "checkout-slow-query-runbook.md",
            "title": "Runbook: Checkout Latency / Slow Query",
            "excerpt": "1. Check APM for query counts...",
        },
    )

    incident = make_incident()
    session.add(incident)
    session.commit()
    session.refresh(incident)

    orchestrator.run_pipeline(incident.id)

    session.refresh(incident)
    assert incident.status == IncidentStatus.briefed
    assert incident.suspected_commit_sha == BAD_SHA
    assert incident.diagnosis_correct is True
    assert incident.commit_analysis_confidence == 0.92
    assert incident.runbook_id == "checkout-slow-query-runbook.md"
    assert incident.error_message is None

    impact = json.loads(incident.impact_json)
    assert impact["severity"] == "high"
    assert "POST /checkout/summary" in impact["degraded_endpoints"]
    assert "GET /products" not in impact["degraded_endpoints"]
    assert impact["est_revenue_at_risk_per_hr_usd"] > 0

    brief = json.loads(incident.slack_brief_json)
    assert brief["ok"] is True


def test_run_pipeline_scores_wrong_diagnosis(session, monkeypatch):
    monkeypatch.setattr(orchestrator, "engine", session.get_bind())
    monkeypatch.setattr(orchestrator, "get_github_adapter", lambda: FakeGitHubAdapter())
    monkeypatch.setattr(orchestrator, "get_slack_adapter", lambda: MockSlackAdapter())
    monkeypatch.setattr(
        commit_analysis,
        "complete_json",
        lambda *a, **k: {
            "suspected_candidate_number": 1,  # the README noise commit
            "reasoning": "wrong pick",
            "confidence": 0.4,
        },
    )
    monkeypatch.setattr(orchestrator, "query_runbook", lambda *a, **k: None)

    incident = make_incident()
    session.add(incident)
    session.commit()
    session.refresh(incident)

    orchestrator.run_pipeline(incident.id)

    session.refresh(incident)
    assert incident.status == IncidentStatus.briefed
    assert incident.diagnosis_correct is False


def test_run_pipeline_records_error_on_llm_failure(session, monkeypatch):
    monkeypatch.setattr(orchestrator, "engine", session.get_bind())
    monkeypatch.setattr(orchestrator, "get_github_adapter", lambda: FakeGitHubAdapter())

    def boom(*a, **k):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(commit_analysis, "complete_json", boom)

    incident = make_incident()
    session.add(incident)
    session.commit()
    session.refresh(incident)

    orchestrator.run_pipeline(incident.id)

    session.refresh(incident)
    assert incident.status == IncidentStatus.analyzing  # never advanced past this
    assert "LLM unavailable" in incident.error_message


def test_run_postmortem_generates_markdown_with_mocked_llm(session, monkeypatch):
    monkeypatch.setattr(orchestrator, "engine", session.get_bind())
    monkeypatch.setattr(postmortem, "complete", lambda *a, **k: "## Summary\nAll good now.")

    incident = make_incident(status=IncidentStatus.resolved)
    session.add(incident)
    session.commit()
    session.refresh(incident)

    orchestrator.run_postmortem(incident.id)

    session.refresh(incident)
    assert incident.status == IncidentStatus.postmortem_generated
    assert incident.postmortem_markdown == "## Summary\nAll good now."
