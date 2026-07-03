"""Fault injection = a real deployment of a bad branch to the running target
app. No incident is created here — the anomaly detector has to notice the
degradation in live metrics and open the incident itself."""

from fastapi import APIRouter, HTTPException

from app.live.app_manager import manager
from app.live.detector import detector
from app.schemas import FaultScenarioOut, InjectFaultRequest, InjectFaultResponse
from app.seed.fault_scenarios import FAULT_SCENARIOS

router = APIRouter(prefix="/api", tags=["faults"])


@router.get("/fault-scenarios", response_model=list[FaultScenarioOut])
def list_fault_scenarios():
    return [
        FaultScenarioOut(
            id=s.id,
            title=s.title,
            description=s.description,
            deploy_branch=s.deploy_branch,
        )
        for s in FAULT_SCENARIOS.values()
    ]


@router.post("/faults/inject", response_model=InjectFaultResponse)
def inject_fault(req: InjectFaultRequest):
    scenario = FAULT_SCENARIOS.get(req.fault_scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Unknown fault_scenario_id")
    if detector.has_active_incident():
        raise HTTPException(
            status_code=409,
            detail="An incident is already active — resolve it or reset the environment first",
        )
    if not manager.is_running():
        raise HTTPException(status_code=503, detail="Target app is not running")

    status = manager.deploy_scenario(scenario)
    return InjectFaultResponse(
        deployed_branch=status["branch"],
        head_sha=status["head_sha"],
        note=(
            "Bad commit deployed to the live target app. The anomaly detector "
            "should fire within ~20–40 seconds once degradation shows in the metrics."
        ),
    )
