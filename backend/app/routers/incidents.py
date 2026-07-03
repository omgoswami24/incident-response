from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Incident, IncidentStatus, TimelineEvent, TimelineEventType
from app.pipeline.orchestrator import run_pipeline, run_postmortem
from app.pipeline.remediation import run_remediation
from app.schemas import (
    IncidentDetailOut,
    IncidentSummaryOut,
    ResolveIncidentRequest,
    TimelineEventOut,
)
from app.state_machine import ALLOWED_TRANSITIONS, transition

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentSummaryOut])
def list_incidents(session: Session = Depends(get_session)):
    incidents = session.exec(select(Incident).order_by(Incident.created_at.desc())).all()
    return incidents


@router.get("/{incident_id}", response_model=IncidentDetailOut)
def get_incident(incident_id: str, session: Session = Depends(get_session)):
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/{incident_id}/timeline", response_model=list[TimelineEventOut])
def get_timeline(incident_id: str, session: Session = Depends(get_session)):
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    events = session.exec(
        select(TimelineEvent)
        .where(TimelineEvent.incident_id == incident_id)
        .order_by(TimelineEvent.ts)
    ).all()
    return events


@router.post("/{incident_id}/retry", response_model=IncidentDetailOut)
def retry_pipeline(
    incident_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Re-run the diagnosis pipeline after a transient failure (e.g. the LLM
    provider was briefly unavailable)."""
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status not in (IncidentStatus.firing, IncidentStatus.analyzing):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot retry pipeline in status {incident.status}",
        )

    incident.error_message = None
    session.add(incident)
    session.commit()
    session.refresh(incident)

    background_tasks.add_task(run_pipeline, incident.id)
    return incident


@router.post("/{incident_id}/remediate", response_model=IncidentDetailOut)
def remediate_incident(
    incident_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Approve the proposed remediation: revert the suspected commit, redeploy,
    and verify recovery against live metrics (human-in-the-loop by design)."""
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status != IncidentStatus.briefed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot remediate incident in status {incident.status}",
        )
    if not incident.suspected_commit_sha:
        raise HTTPException(status_code=409, detail="No suspected commit to revert")

    background_tasks.add_task(run_remediation, incident.id)
    return incident


@router.post("/{incident_id}/resolve", response_model=IncidentDetailOut)
def resolve_incident(
    incident_id: str,
    req: ResolveIncidentRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Manual resolve — the fallback path when auto-remediation is skipped or
    failed verification."""
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if IncidentStatus.resolved not in ALLOWED_TRANSITIONS.get(incident.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot resolve incident in status {incident.status}",
        )

    incident.resolution_notes = req.resolution_notes
    session.add(incident)
    session.commit()
    session.refresh(incident)

    transition(
        session,
        incident,
        IncidentStatus.resolved,
        TimelineEventType.resolved,
        "Incident resolved manually",
        {"resolution_notes": req.resolution_notes} if req.resolution_notes else None,
    )

    background_tasks.add_task(run_postmortem, incident.id)

    return incident


@router.get("/{incident_id}/postmortem")
def get_postmortem(incident_id: str, session: Session = Depends(get_session)):
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.postmortem_markdown is None:
        raise HTTPException(status_code=404, detail="Postmortem not yet generated")
    return {"markdown": incident.postmortem_markdown}
