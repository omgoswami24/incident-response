import asyncio
from collections import defaultdict

from app.schemas import TimelineEventOut


class IncidentEventBroadcaster:
    """In-process pub/sub, one asyncio.Queue per incident, fanned out to any
    number of SSE subscribers for that incident."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, incident_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[incident_id].append(queue)
        return queue

    def unsubscribe(self, incident_id: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(incident_id, [])
        if queue in subs:
            subs.remove(queue)

    def publish(self, incident_id: str, event: TimelineEventOut) -> None:
        for queue in self._subscribers.get(incident_id, []):
            queue.put_nowait(event)


broadcaster = IncidentEventBroadcaster()
