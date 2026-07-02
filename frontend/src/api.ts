import { useEffect, useRef, useState } from "react";
import type {
  FaultScenario,
  IncidentDetail,
  IncidentSummary,
  TimelineEvent,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`);
  }
  return resp.json() as Promise<T>;
}

export async function fetchFaultScenarios(): Promise<FaultScenario[]> {
  return json(await fetch(`${API_BASE}/api/fault-scenarios`));
}

export async function fetchIncidents(): Promise<IncidentSummary[]> {
  return json(await fetch(`${API_BASE}/api/incidents`));
}

export async function fetchIncident(id: string): Promise<IncidentDetail> {
  return json(await fetch(`${API_BASE}/api/incidents/${id}`));
}

export async function fetchTimeline(id: string): Promise<TimelineEvent[]> {
  return json(await fetch(`${API_BASE}/api/incidents/${id}/timeline`));
}

export async function injectFault(
  faultScenarioId: string,
): Promise<{ incident_id: string }> {
  return json(
    await fetch(`${API_BASE}/api/incidents/inject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fault_scenario_id: faultScenarioId }),
    }),
  );
}

export async function resolveIncident(
  id: string,
  resolutionNotes?: string,
): Promise<IncidentDetail> {
  return json(
    await fetch(`${API_BASE}/api/incidents/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution_notes: resolutionNotes ?? null }),
    }),
  );
}

/** Live-updates a timeline via SSE, re-fetching the full incident on every
 * event so the UI stays in sync with derived fields (status, commit, etc.),
 * not just the raw event log. */
export function useIncidentStream(incidentId: string | null): {
  incident: IncidentDetail | null;
  events: TimelineEvent[];
} {
  const [incident, setIncident] = useState<IncidentDetail | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setIncident(null);
    setEvents([]);
    if (!incidentId) return;

    let cancelled = false;
    const seenIds = new Set<string>();
    const addEvents = (newEvents: TimelineEvent[]) => {
      const fresh = newEvents.filter((e) => !seenIds.has(e.id));
      fresh.forEach((e) => seenIds.add(e.id));
      if (fresh.length) {
        setEvents((prev) =>
          [...prev, ...fresh].sort((a, b) => a.ts.localeCompare(b.ts)),
        );
      }
    };

    // Subscribe before backfilling so events can't land in the gap.
    const source = new EventSource(
      `${API_BASE}/api/incidents/${incidentId}/stream`,
    );
    sourceRef.current = source;

    source.addEventListener("timeline_event", (e) => {
      const event: TimelineEvent = JSON.parse((e as MessageEvent).data);
      addEvents([event]);
      fetchIncident(incidentId).then((inc) => {
        if (!cancelled) setIncident(inc);
      });
    });

    fetchIncident(incidentId).then((inc) => {
      if (!cancelled) setIncident(inc);
    });
    fetchTimeline(incidentId).then((initial) => {
      if (!cancelled) addEvents(initial);
    });

    return () => {
      cancelled = true;
      source.close();
    };
  }, [incidentId]);

  return { incident, events };
}
