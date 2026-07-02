from fastapi import APIRouter

from app.schemas import FaultScenarioOut
from app.seed.fault_scenarios import FAULT_SCENARIOS

router = APIRouter(prefix="/api/fault-scenarios", tags=["fault-scenarios"])


@router.get("", response_model=list[FaultScenarioOut])
def list_fault_scenarios():
    return [
        FaultScenarioOut(id=s.id, title=s.title, alert_description=s.alert_description)
        for s in FAULT_SCENARIOS.values()
    ]
