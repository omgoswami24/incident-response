from datetime import datetime

from pydantic import BaseModel

from app.models import IncidentStatus, TimelineEventType


class InjectFaultRequest(BaseModel):
    fault_scenario_id: str


class InjectFaultResponse(BaseModel):
    incident_id: str


class ResolveIncidentRequest(BaseModel):
    resolution_notes: str | None = None


class TimelineEventOut(BaseModel):
    id: str
    ts: datetime
    type: TimelineEventType
    title: str
    detail: str | None = None


class IncidentSummaryOut(BaseModel):
    id: str
    fault_scenario_id: str
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime


class IncidentDetailOut(BaseModel):
    id: str
    fault_scenario_id: str
    status: IncidentStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    postmortem_generated_at: datetime | None

    suspected_commit_sha: str | None
    suspected_commit_message: str | None
    suspected_commit_author: str | None
    suspected_commit_diff: str | None
    commit_analysis_reasoning: str | None
    commit_analysis_confidence: float | None

    runbook_id: str | None
    runbook_title: str | None
    runbook_excerpt: str | None

    impact_json: str | None
    slack_brief_json: str | None
    resolution_notes: str | None
    postmortem_markdown: str | None


class FaultScenarioOut(BaseModel):
    id: str
    title: str
    alert_description: str
