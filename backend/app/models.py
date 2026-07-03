import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class IncidentStatus(StrEnum):
    firing = "firing"
    analyzing = "analyzing"
    briefed = "briefed"
    remediating = "remediating"
    resolved = "resolved"
    postmortem_generated = "postmortem_generated"
    closed = "closed"  # operator override (environment reset), terminal


class TimelineEventType(StrEnum):
    alert_detected = "alert_detected"
    analyzing_started = "analyzing_started"
    commit_identified = "commit_identified"
    runbook_retrieved = "runbook_retrieved"
    impact_estimated = "impact_estimated"
    slack_brief_posted = "slack_brief_posted"
    remediation_started = "remediation_started"
    remediation_applied = "remediation_applied"
    recovery_verified = "recovery_verified"
    remediation_failed = "remediation_failed"
    resolved = "resolved"
    postmortem_generated = "postmortem_generated"
    closed = "closed"
    error = "error"


class Incident(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    status: IncidentStatus = Field(default=IncidentStatus.firing)
    error_message: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    postmortem_generated_at: datetime | None = None

    # detection — everything the pipeline is allowed to see
    detected_alert_text: str = ""
    baseline_json: str | None = None  # healthy per-endpoint stats at detection time
    detection_stats_json: str | None = None  # degraded window stats at detection time

    # ground truth — what was actually injected; used ONLY to score the
    # diagnosis after the fact, never fed to the LLM
    ground_truth_scenario_id: str | None = None
    ground_truth_commit_sha: str | None = None
    diagnosis_correct: bool | None = None

    # commit analysis (diagnosis)
    suspected_commit_sha: str | None = None
    suspected_commit_message: str | None = None
    suspected_commit_author: str | None = None
    suspected_commit_diff: str | None = None
    commit_analysis_reasoning: str | None = None
    commit_analysis_confidence: float | None = None

    # runbook RAG
    runbook_id: str | None = None
    runbook_title: str | None = None
    runbook_excerpt: str | None = None

    # impact + brief
    impact_json: str | None = None
    slack_brief_json: str | None = None

    # remediation
    remediation_revert_sha: str | None = None
    remediation_verified: bool | None = None
    recovery_stats_json: str | None = None

    resolution_notes: str | None = None
    postmortem_markdown: str | None = None


class TimelineEvent(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    incident_id: str = Field(foreign_key="incident.id", index=True)
    ts: datetime = Field(default_factory=utcnow)
    type: TimelineEventType
    title: str
    detail: str | None = None  # JSON-encoded string
