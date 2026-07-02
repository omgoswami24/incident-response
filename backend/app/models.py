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
    resolved = "resolved"
    postmortem_generated = "postmortem_generated"


class TimelineEventType(StrEnum):
    fault_injected = "fault_injected"
    analyzing_started = "analyzing_started"
    commit_identified = "commit_identified"
    runbook_retrieved = "runbook_retrieved"
    impact_estimated = "impact_estimated"
    slack_brief_posted = "slack_brief_posted"
    resolved = "resolved"
    postmortem_generated = "postmortem_generated"
    error = "error"


class Incident(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    fault_scenario_id: str
    status: IncidentStatus = Field(default=IncidentStatus.firing)
    error_message: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    postmortem_generated_at: datetime | None = None

    # commit analysis
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
    resolution_notes: str | None = None
    postmortem_markdown: str | None = None


class TimelineEvent(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    incident_id: str = Field(foreign_key="incident.id", index=True)
    ts: datetime = Field(default_factory=utcnow)
    type: TimelineEventType
    title: str
    detail: str | None = None  # JSON-encoded string
