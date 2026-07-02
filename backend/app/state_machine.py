import json
from datetime import datetime, timezone

from sqlmodel import Session

from app.events import broadcaster
from app.models import Incident, IncidentStatus, TimelineEvent, TimelineEventType
from app.schemas import TimelineEventOut

ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.firing: {IncidentStatus.analyzing},
    IncidentStatus.analyzing: {IncidentStatus.briefed},
    IncidentStatus.briefed: {IncidentStatus.resolved},
    IncidentStatus.resolved: {IncidentStatus.postmortem_generated},
    IncidentStatus.postmortem_generated: set(),
}


class InvalidTransitionError(Exception):
    pass


def transition(
    session: Session,
    incident: Incident,
    new_status: IncidentStatus,
    timeline_type: TimelineEventType,
    title: str,
    detail: dict | None = None,
) -> Incident:
    """The single choke point for status changes: validates the transition,
    updates the incident, appends a TimelineEvent, and broadcasts it over SSE.
    """
    allowed = ALLOWED_TRANSITIONS.get(incident.status, set())
    if new_status != incident.status and new_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition incident {incident.id} from {incident.status} to {new_status}"
        )

    incident.status = new_status
    incident.updated_at = datetime.now(timezone.utc)
    if new_status == IncidentStatus.resolved:
        incident.resolved_at = incident.updated_at
    if new_status == IncidentStatus.postmortem_generated:
        incident.postmortem_generated_at = incident.updated_at

    session.add(incident)

    event = TimelineEvent(
        incident_id=incident.id,
        type=timeline_type,
        title=title,
        detail=json.dumps(detail) if detail is not None else None,
    )
    session.add(event)
    session.commit()
    session.refresh(incident)
    session.refresh(event)

    broadcaster.publish(
        incident.id,
        TimelineEventOut(
            id=event.id,
            ts=event.ts,
            type=event.type,
            title=event.title,
            detail=event.detail,
        ),
    )
    return incident


def record_error(session: Session, incident: Incident, message: str) -> Incident:
    """Records a pipeline failure without advancing status — the incident
    simply stops progressing and the error is surfaced to the UI."""
    incident.error_message = message
    incident.updated_at = datetime.now(timezone.utc)
    session.add(incident)

    event = TimelineEvent(
        incident_id=incident.id,
        type=TimelineEventType.error,
        title="Pipeline error",
        detail=json.dumps({"message": message}),
    )
    session.add(event)
    session.commit()
    session.refresh(incident)
    session.refresh(event)

    broadcaster.publish(
        incident.id,
        TimelineEventOut(
            id=event.id,
            ts=event.ts,
            type=event.type,
            title=event.title,
            detail=event.detail,
        ),
    )
    return incident
