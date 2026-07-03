import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.live.app_manager import manager
from app.live.detector import TERMINAL_STATUSES, detector
from app.live.traffic import run_load
from app.models import Incident, IncidentStatus, TimelineEventType
from app.routers import environment, fault_scenarios, incidents, live_metrics, stream
from app.state_machine import transition

logger = logging.getLogger(__name__)


def _close_stale_incidents() -> None:
    """Open incidents reference an environment that no longer exists after a
    backend restart (the target app is reset to pristine main at boot)."""
    with Session(engine) as session:
        stale = session.exec(
            select(Incident).where(Incident.status.not_in(TERMINAL_STATUSES))
        ).all()
        for incident in stale:
            transition(
                session,
                incident,
                IncidentStatus.closed,
                TimelineEventType.closed,
                "Incident closed on backend restart (environment was reset)",
            )
        if stale:
            logger.info("closed %d stale incident(s) at boot", len(stale))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _close_stale_incidents()
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if settings.live_env_enabled:
        # pristine healthy main + fresh target app process on every boot
        await asyncio.to_thread(manager.reset)
        tasks = [
            asyncio.create_task(run_load(stop_event)),
            asyncio.create_task(detector.run(stop_event)),
        ]
        logger.info(
            "live environment up: target app on :%s, %s load workers, detector armed",
            settings.target_app_port,
            settings.load_workers,
        )
    yield
    stop_event.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    manager.stop()


app = FastAPI(title="Autonomous AI Incident Response System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(incidents.router)
app.include_router(fault_scenarios.router)
app.include_router(stream.router)
app.include_router(environment.router)
app.include_router(live_metrics.router)
