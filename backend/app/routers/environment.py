"""Environment control: what's deployed, whether the detector is armed, and
a reset that returns the target app to pristine healthy main."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.live.app_manager import manager
from app.live.detector import TERMINAL_STATUSES, detector
from app.models import Incident, IncidentStatus, TimelineEventType
from app.state_machine import transition

router = APIRouter(prefix="/api/environment", tags=["environment"])


@router.get("")
def get_environment():
    return {
        "app": manager.status(),
        "detector": detector.public_state(),
        "load_workers": settings.load_workers,
    }


@router.post("/reset")
def reset_environment(session: Session = Depends(get_session)):
    # operator override: close any incident that never reached a terminal state
    open_incidents = session.exec(
        select(Incident).where(Incident.status.not_in(TERMINAL_STATUSES))
    ).all()
    for incident in open_incidents:
        transition(
            session,
            incident,
            IncidentStatus.closed,
            TimelineEventType.closed,
            "Incident closed by environment reset",
        )

    status = manager.reset()
    return {"app": status, "closed_incidents": len(open_incidents)}
