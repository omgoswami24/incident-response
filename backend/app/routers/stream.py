import asyncio

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.events import broadcaster

router = APIRouter(prefix="/api/incidents", tags=["stream"])


@router.get("/{incident_id}/stream")
async def stream_incident(incident_id: str, request: Request):
    queue = broadcaster.subscribe(incident_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield {"event": "timeline_event", "data": event.model_dump_json()}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            broadcaster.unsubscribe(incident_id, queue)

    return EventSourceResponse(event_generator())
