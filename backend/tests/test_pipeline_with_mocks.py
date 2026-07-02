from datetime import datetime, timezone

from app.adapters.github.base import CommitInfo
from app.adapters.slack.mock_slack_adapter import MockSlackAdapter
from app.models import Incident, IncidentStatus
from app.pipeline import commit_analysis, orchestrator, postmortem, runbook_rag


class FakeGitHubAdapter:
    """Conforms to the GitHubAdapter protocol without touching real git."""

    def __init__(self):
        self._commits = [
            CommitInfo(
                sha="bad" * 13 + "a",
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


def test_run_pipeline_reaches_briefed_with_mocked_adapters_and_llm(session, monkeypatch):
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
        runbook_rag,
        "query_runbook",
        lambda *a, **k: {
            "runbook_id": "checkout-slow-query-runbook.md",
            "title": "Runbook: Checkout Latency / Slow Query",
            "excerpt": "1. Check APM for query counts...",
        },
    )

    incident = Incident(fault_scenario_id="checkout-n-plus-one")
    session.add(incident)
    session.commit()
    session.refresh(incident)

    orchestrator.run_pipeline(incident.id)

    session.refresh(incident)
    assert incident.status == IncidentStatus.briefed
    assert incident.suspected_commit_message == (
        "perf: fetch product details individually during checkout summary"
    )
    assert incident.commit_analysis_confidence == 0.92
    assert incident.runbook_id == "checkout-slow-query-runbook.md"
    assert incident.impact_json is not None
    assert incident.slack_brief_json is not None
    assert incident.error_message is None


def test_run_pipeline_records_error_on_llm_failure(session, monkeypatch):
    monkeypatch.setattr(orchestrator, "engine", session.get_bind())
    monkeypatch.setattr(orchestrator, "get_github_adapter", lambda: FakeGitHubAdapter())

    def boom(*a, **k):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(commit_analysis, "complete_json", boom)

    incident = Incident(fault_scenario_id="checkout-n-plus-one")
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

    incident = Incident(
        fault_scenario_id="checkout-n-plus-one",
        status=IncidentStatus.resolved,
    )
    session.add(incident)
    session.commit()
    session.refresh(incident)

    orchestrator.run_postmortem(incident.id)

    session.refresh(incident)
    assert incident.status == IncidentStatus.postmortem_generated
    assert incident.postmortem_markdown == "## Summary\nAll good now."
