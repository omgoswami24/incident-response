from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Incident, IncidentStatus, TimelineEvent
from app.pipeline.orchestrator import run_pipeline, run_postmortem
from app.schemas import (
    IncidentDetailOut,
    IncidentSummaryOut,
    InjectFaultRequest,
    InjectFaultResponse,
    ResolveIncidentRequest,
    TimelineEventOut,
)
from app.seed.fault_scenarios import FAULT_SCENARIOS
from app.state_machine import ALLOWED_TRANSITIONS, transition
from app.models import TimelineEventType

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.post("/inject", response_model=InjectFaultResponse)
def inject_fault(
    req: InjectFaultRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    if req.fault_scenario_id not in FAULT_SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown fault_scenario_id")

    incident = Incident(fault_scenario_id=req.fault_scenario_id)
    session.add(incident)
    session.commit()
    session.refresh(incident)

    scenario = FAULT_SCENARIOS[req.fault_scenario_id]
    transition(
        session,
        incident,
        IncidentStatus.firing,
        TimelineEventType.fault_injected,
        f"Fault injected: {scenario.title}",
        {"alert_description": scenario.alert_description},
    )

    background_tasks.add_task(run_pipeline, incident.id)

    return InjectFaultResponse(incident_id=incident.id)


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


@router.post("/{incident_id}/resolve", response_model=IncidentDetailOut)
def resolve_incident(
    incident_id: str,
    req: ResolveIncidentRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
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
        "Incident resolved",
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
